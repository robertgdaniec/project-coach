import os
import sys

# Ochrona przed środowiskiem bezokienkowym pythonw.exe (gdzie sys.stdout/stderr są None na Windows)
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')

import time
import json
import datetime
import logging
import asyncio
import re
import html
import uuid
from typing import List, Optional, Dict, Any
from pathlib import Path
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ConfigDict
from fastapi import FastAPI, Request, Response, BackgroundTasks, status
from fastapi.responses import JSONResponse

# 1. Konfiguracja środowiska i ścieżek
BASE_DIR = Path(__file__).resolve().parent

env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path)
load_dotenv()

kalistenika_env = os.environ.get("KALISTENIKA_DIR")
if kalistenika_env:
    WORKSPACE_DIR = Path(kalistenika_env).resolve()
else:
    WORKSPACE_DIR = BASE_DIR.parent.parent / "kalistenika"

OUTPUT_FILE = WORKSPACE_DIR / "workouts.json"
LOG_FILE = WORKSPACE_DIR / "server_log.txt"
os.makedirs(WORKSPACE_DIR, exist_ok=True)

# Dodanie katalogu bin do PATH (ffmpeg dla Whispera)
ffmpeg_path = os.path.join(BASE_DIR, 'bin')
if os.path.exists(ffmpeg_path) and ffmpeg_path not in os.environ.get('PATH', ''):
    os.environ['PATH'] += os.pathsep + ffmpeg_path

# Monkeypatch subprocess.Popen dla cichego uruchamiania procesów pomocniczych (np. ngrok.exe na Windows)
if sys.platform == "win32":
    import subprocess
    original_popen = subprocess.Popen
    class PatchedPopen(original_popen):
        def __init__(self, *args, **kwargs):
            if 'creationflags' not in kwargs:
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            else:
                kwargs['creationflags'] |= subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)
    subprocess.Popen = PatchedPopen

# Konfiguracja Ngrok
ngrok_token = os.environ.get("NGROK_AUTH_TOKEN", "")
if ngrok_token:
    try:
        from pyngrok import conf
        ngrok_config = conf.PyngrokConfig(auth_token=ngrok_token)
        conf.set_default(ngrok_config)
    except Exception:
        pass

# Dodanie ścieżek NVIDIA CUDA/cuDNN jeśli istnieją
import site
site_packages_dir = site.getusersitepackages()
if isinstance(site_packages_dir, list):
    site_packages_dir = site_packages_dir[0]

try:
    if site_packages_dir:
        cublas_bin = os.path.join(site_packages_dir, 'nvidia', 'cublas', 'bin')
        cudnn_bin = os.path.join(site_packages_dir, 'nvidia', 'cudnn', 'bin')
        if os.path.exists(cublas_bin):
            os.add_dll_directory(cublas_bin)
        if os.path.exists(cudnn_bin):
            os.add_dll_directory(cudnn_bin)
except Exception:
    pass

# Dołączenie modułów lokalnych
sys.path.insert(0, str(BASE_DIR))
from etl_parser import process_data
from gemini_pool import GeminiKeyPool, AllKeysExhaustedError

# 2. System Logowania
logger = logging.getLogger("server_fastapi")
logger.setLevel(logging.INFO)
if not logger.handlers:
    try:
        handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('[%(asctime)s] [FastAPI] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        logger.addHandler(handler)
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter('[%(asctime)s] [FastAPI] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        logger.addHandler(console_handler)
    except Exception as e:
        print(f"Blad konfiguracji loggera: {e}", file=sys.stderr)

def log(msg: str):
    logger.info(msg)

# Inicjalizacja zarządcy puli kluczy API
default_model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
key_pool = GeminiKeyPool(model_name=default_model)

# Globalny timeout dla zapytań sieciowych
HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)

# Lazy loading modelu Whisper
whisper_model = None

def init_whisper():
    global whisper_model
    if whisper_model is None:
        target_device = os.environ.get("WHISPER_DEVICE", "cuda").lower()
        if target_device == "cpu":
            log("Ladowanie lokalnego modelu Whisper w trybie CPU (model base, int8)...")
            try:
                from faster_whisper import WhisperModel
                whisper_model = WhisperModel('base', device='cpu', compute_type='int8')
                log("Model Whisper zaladowany pomyslnie na CPU.")
            except Exception as e:
                log(f"Krytyczny blad ladowania Whispera na CPU: {e}")
                whisper_model = None
            return whisper_model

        log("Ladowanie lokalnego modelu Whisper (CUDA float16, model large-v3)...")
        try:
            from faster_whisper import WhisperModel
            whisper_model = WhisperModel('large-v3', device='cuda', compute_type='float16')
            log("Model Whisper zaladowany pomyslnie na GPU.")
        except Exception as e:
            log(f"Blad ladowania Whispera na GPU: {e}. Proba fallback do CPU...")
            try:
                from faster_whisper import WhisperModel
                whisper_model = WhisperModel('base', device='cpu', compute_type='int8')
                log("Model Whisper zaladowany w trybie awaryjnym (CPU base).")
            except Exception as e2:
                log(f"Krytyczny blad ladowania Whispera: {e2}")
                whisper_model = None
    return whisper_model


# ==============================================================================
# MODELE PYDANTIC (V2) - Typowanie i Walidacja Webhooków
# ==============================================================================

# --- A. Telegram Bot API Schemas ---

class TelegramUser(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    is_bot: Optional[bool] = None
    first_name: str = ""
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None

class TelegramChat(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    type: Optional[str] = None
    title: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

class TelegramFileReference(BaseModel):
    model_config = ConfigDict(extra="allow")
    file_id: str
    file_unique_id: Optional[str] = None
    duration: Optional[int] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None

class TelegramPhotoSize(BaseModel):
    model_config = ConfigDict(extra="allow")
    file_id: str
    file_unique_id: Optional[str] = None
    width: int
    height: int
    file_size: Optional[int] = None

class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    message_id: int
    from_user: Optional[TelegramUser] = Field(default=None, alias="from")
    date: Optional[int] = None
    chat: Optional[TelegramChat] = None
    text: Optional[str] = None
    voice: Optional[TelegramFileReference] = None
    audio: Optional[TelegramFileReference] = None
    video: Optional[TelegramFileReference] = None
    document: Optional[TelegramFileReference] = None
    photo: Optional[List[TelegramPhotoSize]] = None
    caption: Optional[str] = None

class TelegramWebhookUpdate(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    update_id: int
    message: Optional[TelegramMessage] = None
    edited_message: Optional[TelegramMessage] = None
    channel_post: Optional[TelegramMessage] = None


# --- B. Voice Inbox Schemas ---

class VoiceInboxRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Transkrybowana tresc notatki glosowej z zegarka", examples=["Zjadlem omlet z 3 jaj i 100g borowek"])

class VoiceInboxResponse(BaseModel):
    status: str = "success"
    message: str = "Zapisano w skrzynce odbiorczej"
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))


# --- C. Samsung Health & Telemetry Schemas ---

class StepRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    start_time: str = Field(..., description="Czas pomiaru w formacie ISO8601")
    count: int = Field(..., ge=0, description="Liczba krokow w przedziale")

class CalorieRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    start_time: str
    calories: float = Field(..., ge=0)

class HrvRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    time: str
    rmssd_millis: float

class Vo2MaxRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    time: str
    ml_per_kg_per_min: float

class RestingHeartRateRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    time: str
    bpm: int

class ExerciseRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    start_time: str
    end_time: Optional[str] = None
    type: Optional[str] = "unknown"
    duration_seconds: Optional[float] = 0.0
    distance_meters: Optional[float] = None
    avg_cadence_spm: Optional[float] = None
    stride_length_m: Optional[float] = None
    heart_rate: Optional[List[Dict[str, Any]]] = None

class SamsungHealthPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    steps: Optional[List[StepRecord]] = None
    total_calories: Optional[List[CalorieRecord]] = None
    heart_rate_variability: Optional[List[HrvRecord]] = None
    vo2_max: Optional[List[Vo2MaxRecord]] = None
    resting_heart_rate: Optional[List[RestingHeartRateRecord]] = None
    exercise: Optional[List[ExerciseRecord]] = None

class StandardResponse(BaseModel):
    status: str
    message: Optional[str] = None


# ==============================================================================
# IDEMPOTENCJA & AUTO-PURGE (Wear OS Guard)
# ==============================================================================

class TelegramDeduplicator:
    """Rejestr idempotencji i deduplikacji z oknem czasowym TTL."""
    def __init__(self):
        self._lock = asyncio.Lock()
        self._entries: Dict[str, float] = {}

    async def is_duplicate(self, key: str, ttl: float = 60.0) -> bool:
        if not key:
            return False
        now = time.time()
        async with self._lock:
            # Czyszczenie przedawnionych wpisow
            expired = [k for k, exp in self._entries.items() if exp <= now]
            for k in expired:
                del self._entries[k]

            if key in self._entries:
                return True

            self._entries[key] = now + ttl
            return False

deduplicator = TelegramDeduplicator()

chat_locks: Dict[int, asyncio.Lock] = {}
chat_locks_guard = asyncio.Lock()

async def get_chat_lock(chat_id: int) -> asyncio.Lock:
    """Zwraca asynchroniczna blokade per-chat zapobiegajac wyscigom w sesji agenta."""
    async with chat_locks_guard:
        if chat_id not in chat_locks:
            chat_locks[chat_id] = asyncio.Lock()
        return chat_locks[chat_id]

def extract_dedup_info(msg: TelegramMessage) -> tuple[Optional[str], float]:
    """Wyciaga unikalna sygnature wiadomosci oraz czas TTL."""
    chat_id = msg.chat.id if msg.chat else 0

    # 1. Sprawdzenie mediow z unikalnym identyfikatorem Telegrama
    for media in (msg.voice, msg.audio, msg.video, msg.document):
        if media and (media.file_unique_id or media.file_id):
            uid = media.file_unique_id or media.file_id
            return f"media:{uid}", 300.0

    if msg.photo and len(msg.photo) > 0:
        uid = msg.photo[-1].file_unique_id or msg.photo[-1].file_id
        if uid:
            return f"photo:{uid}", 300.0

    # 2. Wiadomosci tekstowe - okno 5 sekund na identyczna tresc od tego samego nadawcy
    if msg.text:
        normalized_text = msg.text.strip().lower()
        return f"text:{chat_id}:{normalized_text}", 5.0

    return None, 0.0

async def delete_telegram_message_async(chat_id: int, message_id: int):
    """Asynchroniczne usuwanie zduplikowanej wiadomosci z czatu Telegrama (Auto-Purge)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or not chat_id or not message_id:
        return
    url = f"https://api.telegram.org/bot{token}/deleteMessage"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            res = await client.post(url, json={"chat_id": chat_id, "message_id": message_id})
            log(f"[DEDUPLICATION] Auto-Purge: usunieto zduplikowana wiadomosc {message_id} z czatu {chat_id} (status: {res.status_code})")
    except Exception as e:
        log(f"[DEDUPLICATION] Blad usuwania zduplikowanej wiadomosci {message_id}: {e}")


# ==============================================================================
# TELEGRAM UX: TYPING ACTION & FORMATOWANIE WIADOMOŚCI
# ==============================================================================

class TelegramTypingAction:
    """Asynchroniczny context manager wysylajacy okresowo akcje typing do czatu Telegrama."""
    def __init__(self, chat_id: Optional[int]):
        self.chat_id = chat_id
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def _loop(self):
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token or not self.chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendChatAction"
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            while self._running:
                try:
                    await client.post(url, json={"chat_id": self.chat_id, "action": "typing"})
                except Exception:
                    pass
                await asyncio.sleep(4.0)

    async def __aenter__(self):
        if self.chat_id:
            self._running = True
            self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


def convert_markdown_tables(text: str) -> str:
    """
    Wykrywa tabele Markdown i przeksztalca je w pionowe, czytelne karty na ekran telefonu.
    Obsluguje rowniez uciekane znaki potoku (\\|).
    """
    lines = text.splitlines()
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith('|') and stripped.endswith('|') and stripped.count('|') >= 2:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            
            is_valid_table = False
            parsed_rows = []
            for tl in table_lines:
                placeholder = "§_PIPE_§"
                safe_tl = tl.replace(r'\|', placeholder)
                cells = [c.strip().replace(placeholder, '|') for c in safe_tl.split('|')[1:-1]]
                if all(re.match(r'^:?-+:?$', c.replace(' ', '')) for c in cells if c):
                    is_valid_table = True
                    continue
                parsed_rows.append(cells)
            
            if is_valid_table and len(parsed_rows) >= 2:
                headers = parsed_rows[0]
                data_rows = parsed_rows[1:]
                num_cols = len(headers)
                
                if num_cols >= 3:
                    card_blocks = []
                    for col_idx in range(1, num_cols):
                        card_title = headers[col_idx]
                        items = []
                        for row in data_rows:
                            if col_idx < len(row):
                                label = row[0] if len(row) > 0 else ""
                                val = row[col_idx]
                                if label and val:
                                    items.append(f"• {label}: {val}")
                                elif val:
                                    items.append(f"• {val}")
                        card_blocks.append(f"**{card_title}**\n" + "\n".join(items))
                    result.append("\n\n".join(card_blocks))
                elif num_cols == 2:
                    items = []
                    for row in data_rows:
                        k = row[0] if len(row) > 0 else ""
                        v = row[1] if len(row) > 1 else ""
                        if k and v:
                            items.append(f"• {k}: {v}")
                        elif k or v:
                            items.append(f"• {k or v}")
                    result.append("\n".join(items))
                else:
                    for row in parsed_rows:
                        result.append(" | ".join(row))
            else:
                result.extend(table_lines)
        else:
            result.append(line)
            i += 1
            
    return "\n".join(result)

def format_telegram_message(raw_text: str) -> str:
    """Konwertuje odpowiedz agenta na estetyczny, bezpieczny HTML Telegrama (Mobile-First)."""
    if not raw_text:
        return ""
        
    text = raw_text
    
    # 0. Usuniecie wyciekow technicznych z polityk bezpieczenstwa / harnessu
    text = re.sub(r'Denied by policy "[^"]*"\.\s*(\("?[^"\)]*"?\)\s*)?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(?"?denied by pre-tool hook:[^\)]*\)?"?', '', text, flags=re.IGNORECASE)

    # 1. Usuniecie linkow lokalnych file:/// oraz referencji typu (patrz: ...)
    text = re.sub(r'\(patrz:\s*\[?[^\]\)]*\]?\(?file:///[^\)]*\)?\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(patrz:[^\)]*\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[([^\]]+)\]\(file:///[^\)]+\)', r'\1', text)
    text = re.sub(r'file:///[^\s\)]+', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\.md\)', r'\1', text)
    text = re.sub(r'\(\s*\)', '', text)
    
    # Czyszczenie spacji przed przecinkami/kropkami
    text = re.sub(r'\s+([,\.\?!])', r'\1', text)
    
    # 2. Usuniecie poziomych kresek markdown
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    
    # 2b. Zamiana GitHub alerts (> [!NOTE], > [!TIP] etc.) oraz cytowań markdown na czytelne prefiksy
    text = re.sub(r'^[ \t]*>[ \t]*\[!(NOTE|INFO)\][ \t]*\n?', '💡\n', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^[ \t]*>[ \t]*\[!TIP\][ \t]*\n?', '🎯\n', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^[ \t]*>[ \t]*\[!(IMPORTANT|WARNING|CAUTION)\][ \t]*\n?', '⚠️\n', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^[ \t]*>[ \t]*', '', text, flags=re.MULTILINE)
    
    # 3. Konwersja tabel Markdown na pionowe karty mobilne
    text = convert_markdown_tables(text)
    
    # 4. Zamiana naglowkow markdown na pogrubienie z odstepem
    text = re.sub(r'^\s*#{1,6}\s*(.+)$', r'\n**\1**\n', text, flags=re.MULTILINE)
    
    # 5. Escapowanie znakow specjalnych HTML (&, <, >)
    text = html.escape(text, quote=False)
    
    # 6. Konwersja formatowania Markdown na Telegram HTML
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'(?<![\w\*])\*([^\*\n]+?)\*(?![\w\*])', r'<i>\1</i>', text)
    text = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', text)
    text = text.replace(r'\|', '|')
    
    # 7. Normalizacja pustych linii
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def clean_plain_text(raw_text: str) -> str:
    """Awaryjny sanitizer czystego tekstu (fallback bez formatowania)."""
    if not raw_text:
        return ""
    text = raw_text
    text = re.sub(r'\(patrz:\s*\[?[^\]\)]*\]?\(?file:///[^\)]*\)?\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(patrz:[^\)]*\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[([^\]]+)\]\(file:///[^\)]+\)', r'\1', text)
    text = re.sub(r'file:///[^\s\)]+', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\.md\)', r'\1', text)
    text = re.sub(r'\(\s*\)', '', text)
    text = re.sub(r'\s+([,\.\?!])', r'\1', text)
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[ \t]*>[ \t]*\[!(NOTE|INFO)\][ \t]*\n?', '💡\n', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^[ \t]*>[ \t]*\[!TIP\][ \t]*\n?', '🎯\n', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^[ \t]*>[ \t]*\[!(IMPORTANT|WARNING|CAUTION)\][ \t]*\n?', '⚠️\n', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^[ \t]*>[ \t]*', '', text, flags=re.MULTILINE)
    text = convert_markdown_tables(text)
    text = re.sub(r'^\s*#{1,6}\s*(.+)$', r'\n\1\n', text, flags=re.MULTILINE)
    text = text.replace('**', '').replace('__', '').replace(r'\|', '')
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

async def send_telegram_message(chat_id: int, text: str, use_formatting: bool = True) -> bool:
    """
    Asynchroniczna wysylka wiadomosci na Telegram z obsluga parse_mode='HTML'
    oraz odpornym mechanizmem Fail-Safe Fallback do czystego tekstu.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        log("[TELEGRAM] Blad: Brak TELEGRAM_BOT_TOKEN w srodowisku.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        if use_formatting:
            formatted_html = format_telegram_message(text)
            payload = {
                "chat_id": chat_id,
                "text": formatted_html,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            try:
                res = await client.post(url, json=payload)
                res_data = res.json()
                if res_data.get("ok"):
                    log("[TELEGRAM] Wiadomosc wyslana w formacie HTML.")
                    return True
                log(f"[TELEGRAM] HTML send failed ({res_data.get('description')}). Wykonuje awaryjny fallback...")
            except Exception as e:
                log(f"[TELEGRAM] Wyjatek podczas wysylki HTML: {e}. Wykonuje fallback...")

        # Awaryjny Fail-Safe Fallback: czysty tekst bez parse_mode
        clean_text = clean_plain_text(text) if use_formatting else text
        try:
            res = await client.post(url, json={"chat_id": chat_id, "text": clean_text})
            ok = res.json().get("ok", False)
            if ok:
                log("[TELEGRAM] Wiadomosc wyslana w trybie awaryjnym (Plain Text).")
            return ok
        except Exception as e:
            log(f"[TELEGRAM] Krytyczny blad wysylki wiadomosci na Telegram: {e}")
            return False

async def download_telegram_file(file_id: str, save_path: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    api_url = f"https://api.telegram.org/bot{token}"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        res = (await client.get(f"{api_url}/getFile", params={"file_id": file_id})).json()
        if not res.get("ok"):
            raise Exception(f"Blad pobierania sciezki pliku z Telegrama: {res}")
        
        file_path = res["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        
        audio_res = await client.get(download_url)
        with open(save_path, "wb") as f:
            f.write(audio_res.content)


# ==============================================================================
# ORKIESTRACJA AGENTA AI (Google Antigravity & GeminiKeyPool)
# ==============================================================================

async def reply_with_agent(text: str, chat_id: int):
    """Wywolanie agenta AI z dynamiczna rotacja kluczy Gemini i ochrona sesji."""
    from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
    from google.antigravity.hooks import policy
    from google.antigravity.types import SessionContinuationMode

    log(f"[AGENT] Uruchamianie agenta dla wiadomosci: {text[:30]}...")
    kalistenika_dir = str(WORKSPACE_DIR)

    coach_path = os.path.join(kalistenika_dir, '.agents', 'rules', 'project_coach.md')
    coach_rule = open(coach_path, encoding='utf-8').read() if os.path.exists(coach_path) else "Brak pliku project_coach.md"

    today_str = datetime.date.today().strftime('%Y-%m-%d')
    conv_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"telegram-{chat_id}-{today_str}"))
    current_model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

    total_slots = len(key_pool.slots)
    if total_slots == 0:
        log("[AGENT] Blad krytyczny: Brak skonfigurowanych kluczy API w GeminiKeyPool!")
        await send_telegram_message(chat_id, "❌ Błąd serwera: Brak aktywnych kluczy API w puli.", use_formatting=False)
        return

    attempt = 0
    while attempt < total_slots:
        slot = key_pool.get_active_slot()
        if not slot:
            wait_sec = key_pool.get_min_wait_time()
            log(f"[POOL] Wszystkie klucze ({total_slots}) sa w cooldownie. Najblizszy dostepny za {wait_sec}s.")
            break

        log(f"[POOL] Proba wywolania agenta z kluczem {slot.name} (model: {current_model}, proba {attempt + 1}/{total_slots})...")

        config = LocalAgentConfig(
            system_instructions=coach_rule,
            capabilities=CapabilitiesConfig(),
            policies=[policy.allow_all()],
            workspace=kalistenika_dir,
            model=current_model,
            conversation_id=conv_id,
            session_continuation_mode=SessionContinuationMode.CREATE_OR_RESUME,
            api_key=slot.key
        )

        try:
            async with Agent(config) as agent:
                response = await agent.chat(text)
                reply_text = ""
                async for token in response:
                    reply_text += token

                log(f"[AGENT] Odpowiedz wygenerowana pomyslnie ({len(reply_text)} znakow).")
                key_pool.mark_slot_success(slot)
                await send_telegram_message(chat_id, reply_text, use_formatting=True)
                log("[AGENT] Wiadomosc wyslana na Telegram.")
                return

        except Exception as e:
            error_str = str(e)
            log(f"[AGENT] Blad techniczny na kluczu {slot.name}: {error_str}")

            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                is_daily = "GenerateRequestsPerDay" in error_str
                cooldown = 86400 if is_daily else 300
                key_pool.mark_slot_exhausted(slot, cooldown_seconds=cooldown)
                attempt += 1
                limit_type = "limit dobowy RPD" if is_daily else "limit per-minuta RPM"
                log(f"[POOL] Klucz {slot.name} wyczerpany ({limit_type}). Failover...")
                continue
            elif "503" in error_str or "UNAVAILABLE" in error_str:
                log("[POOL] Blad 503 (serwery Google chwilowo niedostepne). Pauza 2s i failover...")
                key_pool.rotate_to_next_slot()
                attempt += 1
                await asyncio.sleep(2)
                continue
            elif "API_KEY_INVALID" in error_str or "403" in error_str:
                log(f"[POOL] Klucz {slot.name} jest nieprawidlowy! Oznaczam jako wykluczony.")
                key_pool.mark_slot_exhausted(slot, cooldown_seconds=86400)
                attempt += 1
                continue
            else:
                log(f"[AGENT] Blad krytyczny niezwiazany z limitami API: {error_str}")
                break

    wait_time = key_pool.get_min_wait_time()
    if wait_time > 0:
        error_msg = f"⏳ Wszystkie klucze API w puli wyczerpały swoje limity. Najbliższy klucz zwolni się za ok. {wait_time}s. Spróbuj ponownie za chwilę."
    else:
        error_msg = "❌ Wystąpił błąd przetwarzania wiadomości przez agenta AI. Spróbuj ponownie za jakiś czas."

    await send_telegram_message(chat_id, error_msg, use_formatting=False)


async def process_telegram_update_task(data: dict):
    """Zadanie asynchroniczne do obslugi Telegram Update w tle."""
    try:
        msg_dict = data.get('message')
        if not msg_dict:
            return
        
        # Parsowanie obiektem Pydantic
        msg = TelegramMessage.model_validate(msg_dict)
        sender = msg.from_user.first_name if msg.from_user else "User"
        chat_id = msg.chat.id if msg.chat else None
        if not chat_id:
            return

        final_text = None

        async with TelegramTypingAction(chat_id):
            if msg.text:
                final_text = msg.text
                log(f"[TELEGRAM] Tekst od {sender}: {final_text}")
            elif msg.voice:
                file_id = msg.voice.file_id
                log(f"[TELEGRAM] Pobieranie notatki glosowej od {sender}...")
                
                audio_path = os.path.join(BASE_DIR, f'temp_audio_{uuid.uuid4().hex}.ogg')
                await download_telegram_file(file_id, audio_path)
                
                model = init_whisper()
                if model is not None:
                    log("[TELEGRAM] Transkrypcja w toku...")
                    try:
                        def _transcribe():
                            segments, _ = model.transcribe(audio_path, beam_size=5, language='pl')
                            return "".join([s.text for s in segments])
                        
                        final_text = await asyncio.to_thread(_transcribe)
                        log(f"[TELEGRAM] Transkrypcja zakonczona: {final_text}")
                    except Exception as e:
                        log(f"[TELEGRAM] Blad transkrypcji Whisper: {e}")
                else:
                    log("[TELEGRAM] Blad: Brak dostepnego modelu Whisper.")
                
                if os.path.exists(audio_path):
                    try:
                        os.remove(audio_path)
                    except Exception:
                        pass
            else:
                log(f"[TELEGRAM] Nieobslugiwany typ wiadomosci od {sender}.")

            if final_text and chat_id:
                chat_lock = await get_chat_lock(chat_id)
                async with chat_lock:
                    await reply_with_agent(final_text, chat_id)

    except Exception as e:
        import traceback
        log(f"[TELEGRAM] Blad przetwarzania update: {e}\n{traceback.format_exc()}")


# ==============================================================================
# TELEMETRIA DATA LAKE & PARSER ETL
# ==============================================================================

def save_raw_telemetry_atomic(payload: dict):
    """Atomowy zapis danych ze smartwatcha do Data Lake workouts.json."""
    existing_data = {"workouts": []}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                if isinstance(existing_data, list):
                    existing_data = {"workouts": existing_data}
        except Exception:
            existing_data = {"workouts": []}

    if "workouts" not in existing_data:
        existing_data["workouts"] = []

    existing_data['workouts'].append(payload)
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    tmp_file = Path(OUTPUT_FILE).with_suffix('.json.tmp')
    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, OUTPUT_FILE)
    log("[DATA LAKE] Surowy JSON telemetrii zapisany atomowo na dysku.")


# ==============================================================================
# FASTAPI APPLICATION & LIFESPAN
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    log("=== START SERWERA FASTAPI (Uvicorn Runner) ===")
    yield
    log("=== ZATRZYMANIE SERWERA FASTAPI ===")

app = FastAPI(
    title="Project Coach API",
    description="Asynchroniczny potok danych, orkiestracja agenta AI oraz telemetria Samsung Health",
    version="2.0.0",
    lifespan=lifespan
)


# --- Endpointy API ---

@app.get(
    "/",
    summary="Podstawowy Healthcheck",
    description="Szybka weryfikacja zywotnosci serwera",
    tags=["System"]
)
async def root_healthcheck():
    return {"status": "ok", "server": "FastAPI", "version": "2.0.0"}


@app.get(
    "/health",
    summary="Rozszerzony Stan SRE",
    description="Zwraca szczegolowe metryki gotowosci puli kluczy Gemini oraz bazy SQLite",
    tags=["System"]
)
async def advanced_health():
    db_ok = (WORKSPACE_DIR / "baza_kalistenika.db").exists()
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "database_connected": db_ok,
        "gemini_pool": key_pool.get_status(),
        "whisper_ready": whisper_model is not None
    }


@app.post(
    "/voice",
    response_model=VoiceInboxResponse,
    summary="Skrzynka Notatek Głosowych (Voice Inbox)",
    description="Odbiera transkrybowana notatke z zegarka lub telefonu i dopisuje do bufora voice_inbox.md",
    tags=["Telemetria"]
)
async def voice_inbox(req: VoiceInboxRequest):
    text = req.text.strip()
    inbox_path = os.path.join(WORKSPACE_DIR, 'voice_inbox.md')
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    
    entry = f'[{timestamp}] ZEGAREK: {text}\n'
    def _write_inbox():
        with open(inbox_path, 'a', encoding='utf-8') as f:
            f.write(entry)
            
    await asyncio.to_thread(_write_inbox)
    log(f"[VOICE] Odebrano i zapisano notatke glosowa: {text}")
    return VoiceInboxResponse(message="Zapisano w skrzynce odbiorczej", timestamp=timestamp)


@app.post(
    "/telegram-webhook",
    summary="Telegram Bot Webhook",
    description="Odbiera aktualizacje z Telegram Bot API, zarzadza deduplikacja, weryfikuje idempotencje i dispatchuje agenta AI",
    tags=["Telegram"]
)
async def telegram_webhook(update: TelegramWebhookUpdate, background_tasks: BackgroundTasks):
    # 1. Idempotencja na poziomie update_id
    if await deduplicator.is_duplicate(f"update:{update.update_id}", ttl=300.0):
        log(f"[DEDUPLICATION] Odrzucono powtorzony webhook update_id: {update.update_id}")
        return {"ok": True}

    msg = update.message
    if msg:
        chat_id = msg.chat.id if msg.chat else None
        message_id = msg.message_id
        dedup_key, ttl = extract_dedup_info(msg)

        if dedup_key and await deduplicator.is_duplicate(dedup_key, ttl=ttl):
            log(f"[DEDUPLICATION] Wykryto zduplikowana wiadomosc ({dedup_key}, msg_id: {message_id}). Auto-purge...")
            if chat_id and message_id:
                background_tasks.add_task(delete_telegram_message_async, chat_id, message_id)
            return {"ok": True}

        # Asynchroniczne przetwarzanie w tle
        background_tasks.add_task(process_telegram_update_task, update.model_dump(by_alias=True))

    return {"ok": True}


@app.post(
    "/samsung-health",
    response_model=StandardResponse,
    summary="Odbior Telemetrii Samsung Health",
    description="Odbiera pakiet metryk (kroki, kalorie, HRV, VO2, treningi), zapisuje do Data Lake i triggeruje ETL SQLite",
    tags=["Telemetria"]
)
async def receive_samsung_health(payload: SamsungHealthPayload, background_tasks: BackgroundTasks):
    data_dict = payload.model_dump(exclude_none=True)
    
    # 1. Zapis atomowy w tle
    await asyncio.to_thread(save_raw_telemetry_atomic, data_dict)
    
    # 2. Uruchomienie parsera ETL w tle (nie blokujemy odpowiedzi HTTP do zegarka)
    background_tasks.add_task(process_data)
    
    return StandardResponse(status="success", message="Dane telemetryczne zapisane i przetworzone w bazie SQLite.")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
async def catch_all_compatibility(request: Request, path: str, background_tasks: BackgroundTasks):
    """
    Catch-all route gwarantujacy 100% kompatybilnosci wstecznej z zegarkiem Samsung
    i dotychczasowym serwerem Flask (ktory odbieral telemetrie na POST /).
    """
    log(f"[CATCH-ALL] {request.method} /{path}")
    if request.method == "POST":
        try:
            body = await request.json()
            if body and isinstance(body, dict):
                await asyncio.to_thread(save_raw_telemetry_atomic, body)
                background_tasks.add_task(process_data)
                return JSONResponse({"status": "success", "message": "Dane przetworzone i zapisane w bazie SQL."}, status_code=200)
        except Exception as e:
            log(f"[CATCH-ALL] Blad odczytu body: {e}")

    return JSONResponse({"status": "ok"}, status_code=200)


# ==============================================================================
# SRE WATCHDOG & ZARZĄDZANIE PROCESAMI (ADR-017 & ADR-019)
# ==============================================================================

def kill_port(port: int):
    try:
        import psutil
        for conn in psutil.net_connections():
            if conn.laddr.port == port and conn.status == 'LISTEN':
                try:
                    if conn.pid and conn.pid != os.getpid():
                        p = psutil.Process(conn.pid)
                        p.terminate()
                        try:
                            p.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
    except Exception as e:
        log(f"Blad przy zwalnianiu portu {port}: {e}")

def cleanup_ngrok():
    try:
        from pyngrok import ngrok
        ngrok.kill()
    except Exception:
        pass
    try:
        import psutil
        for p in psutil.process_iter(['name']):
            if p.info['name'] and 'ngrok' in p.info['name'].lower():
                p.terminate()
    except Exception:
        pass

def enforce_singleton_and_cleanup(port: int = 8000):
    kill_port(port)
    kill_port(5000)  # Zamknięcie legacy serwera Flask w celu zwolnienia tunelu i zasobów
    cleanup_ngrok()

def register_telegram_webhook(domain: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or not domain:
        return
    webhook_url = f"https://{domain}/telegram-webhook"
    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}").json()
            if res.get("ok"):
                log(f"[TELEGRAM] Webhook pomyslnie zarejestrowany na: {webhook_url}")
            else:
                log(f"[TELEGRAM] Odpowiedz Telegram API przy setWebhook: {res}")
    except Exception as e:
        log(f"[TELEGRAM] Blad rejestracji webhooka: {e}")

def start_watchdog(domain=None, port=8000):
    """
    Watchdog SRE w tle dbajacy o 100% dostepnosc:
    1. Sprawdza co 60s czy tunel Ngrok jest aktywny. Jesli spadl, podnosi go automatycznie.
    2. Sprawdza co 5 min status webhooka w Telegramie (getWebhookInfo). Jesli Telegram ma blad/oczekujace wiadomosci, wykonuje setWebhook.
    """
    if not domain:
        return

    import threading
    def _watch_loop():
        time.sleep(15)  # Czas na pelny rozruch serwera i wstepne polaczenie
        webhook_check_counter = 0
        while True:
            try:
                time.sleep(60)
                # 1. Kontrola tunelu Ngrok
                try:
                    from pyngrok import ngrok
                    tunnels = ngrok.get_tunnels()
                    is_tunnel_up = any(domain in t.public_url for t in tunnels)
                    if not is_tunnel_up:
                        log(f"[WATCHDOG] Tunel Ngrok dla {domain} jest nieaktywny! Proba automatycznego wznowienia...")
                        new_url = ngrok.connect(port, domain=domain)
                        log(f"[WATCHDOG] Tunel Ngrok pomyslnie wznowiony: {new_url}")
                except Exception as e:
                    log(f"[WATCHDOG] Blad monitorowania/wznawiania Ngrok: {e}")

                # 2. Kontrola Telegram Webhook (co 5 minut)
                webhook_check_counter += 1
                if webhook_check_counter >= 5:
                    webhook_check_counter = 0
                    token = os.environ.get("TELEGRAM_BOT_TOKEN")
                    if token:
                        try:
                            with httpx.Client(timeout=10.0) as client:
                                res = client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo").json()
                                if res.get("ok"):
                                    info = res.get("result", {})
                                    last_err = info.get("last_error_message")
                                    pending = info.get("pending_update_count", 0)
                                    webhook_url = f"https://{domain}/telegram-webhook"
                                    curr_url = info.get("url", "")
                                    if last_err or (pending > 2) or curr_url != webhook_url:
                                        log(f"[WATCHDOG] Problem z webhookiem Telegrama (url: {curr_url}, pending: {pending}, err: {last_err}). Re-rejestracja...")
                                        client.get(f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}")
                                        log(f"[WATCHDOG] Webhook Telegrama zaktualizowany na {webhook_url}.")
                        except Exception as e:
                            log(f"[WATCHDOG] Blad sprawdzania webhooka Telegrama: {e}")

            except Exception as e:
                log(f"[WATCHDOG] Wyjatek w petli watchdoga: {e}")

    t = threading.Thread(target=_watch_loop, daemon=True, name="SRE-Watchdog")
    t.start()


# ==============================================================================
# PRODUKCYJNY RUNNER UVICORN
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    import atexit
    import signal
    from pyngrok import ngrok

    host = os.environ.get("FASTAPI_HOST", "0.0.0.0")
    port = int(os.environ.get("FASTAPI_PORT", 8000))

    enforce_singleton_and_cleanup(port=port)
    log("=== START SERWERA FASTAPI (Uvicorn Runner) ===")

    # Rejestracja czyszczenia zasobow wylacznie w procesie serwera (ADR-017)
    atexit.register(cleanup_ngrok)
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    # Wstepna inicjalizacja modelu Whisper na GPU
    init_whisper()

    ngrok_domain = os.environ.get("NGROK_DOMAIN")
    try:
        if ngrok_domain:
            public_url = ngrok.connect(port, domain=ngrok_domain)
        else:
            public_url = ngrok.connect(port)
        log(f"Ngrok tunel aktywny dla portu {port}: {public_url}")
    except Exception as e:
        log(f"Ngrok blad (moze juz dziala): {e}")

    if ngrok_domain:
        register_telegram_webhook(domain=ngrok_domain)
        start_watchdog(domain=ngrok_domain, port=port)

    print(f"Uruchamianie serwera FastAPI na http://{host}:{port}")
    print(f"Interaktywna dokumentacja Swagger UI pod: http://localhost:{port}/docs")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=False
    )
