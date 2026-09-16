import os
import sys
import time
import json
import datetime
import subprocess
import signal
import atexit
import psutil
import logging
import asyncio
import re
import html
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import Flask, request, jsonify
from pyngrok import ngrok, conf
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
load_dotenv()

# Fail-fast: weryfikacja krytycznych sekretow przy starcie
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    print("FATAL: Brak TELEGRAM_BOT_TOKEN w .env. Serwer nie zostanie uruchomiony.", file=sys.stderr)
    sys.exit(1)

ngrok_token = os.environ.get("NGROK_AUTH_TOKEN", "")
if not ngrok_token:
    print("FATAL: Brak NGROK_AUTH_TOKEN w .env. Serwer nie zostanie uruchomiony.", file=sys.stderr)
    sys.exit(1)

# Globalny timeout dla wywolan sieciowych (connect, read) w sekundach
DEFAULT_TIMEOUT = (3.05, 27.0)

# Monkeypatch subprocess.Popen to hide console windows on Windows (specifically for ngrok.exe)
original_popen = subprocess.Popen
class PatchedPopen(original_popen):
    def __init__(self, *args, **kwargs):
        if os.name == 'nt':
            startupinfo = kwargs.get('startupinfo')
            if startupinfo is None:
                startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs['startupinfo'] = startupinfo
        super().__init__(*args, **kwargs)
subprocess.Popen = PatchedPopen

# Dodanie katalogu skryptow do sciezki importu
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from etl_parser import process_data
from gemini_pool import GeminiKeyPool, AllKeysExhaustedError

# Konfiguracja Ngrok
ngrok_config = conf.PyngrokConfig(auth_token=ngrok_token)
conf.set_default(ngrok_config)

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR.parent.parent / "kalistenika"
OUTPUT_FILE = WORKSPACE_DIR / "workouts.json"
LOG_FILE = WORKSPACE_DIR / "server_log.txt"
os.makedirs(WORKSPACE_DIR, exist_ok=True)

logger = logging.getLogger("server")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(handler)

# Podlaczenie handlera logow do puli kluczy
pool_logger = logging.getLogger("GeminiKeyPool")
pool_logger.setLevel(logging.INFO)
pool_logger.addHandler(handler)


def log(msg):
    """Zapis logu za pomoca logging z RotatingFileHandler."""
    logger.info(msg)


# Inicjalizacja zarzadcy puli kluczy API
default_model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
key_pool = GeminiKeyPool(model_name=default_model)


import threading
import requests
from faster_whisper import WhisperModel

# Dodajemy lokalny folder bin do PATH, żeby Whisper widział przeniesiony ffmpeg.exe
ffmpeg_path = os.path.join(BASE_DIR, 'bin')
os.environ['PATH'] += os.pathsep + ffmpeg_path

import site
site_packages_dir = site.getusersitepackages()
if isinstance(site_packages_dir, list):
    site_packages_dir = site_packages_dir[0]

try:
    os.add_dll_directory(os.path.join(site_packages_dir, 'nvidia', 'cublas', 'bin'))
    os.add_dll_directory(os.path.join(site_packages_dir, 'nvidia', 'cudnn', 'bin'))
except Exception as e:
    log(f"Blad przy dodawaniu dll_directory: {e}")

whisper_model = None

def init_whisper():
    global whisper_model
    if whisper_model is None:
        log("Ladowanie lokalnego modelu Whisper (CUDA float16, model large-v3)...")
        try:
            whisper_model = WhisperModel('large-v3', device='cuda', compute_type='float16')
            log("Model Whisper zaladowany pomyslnie na GPU.")
        except Exception as e:
            log(f"Blad ladowania Whispera: {e}")
            whisper_model = None
    return whisper_model

def download_telegram_file(file_id, save_path):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    api_url = f"https://api.telegram.org/bot{token}"
    res = requests.get(f"{api_url}/getFile", params={"file_id": file_id}, timeout=DEFAULT_TIMEOUT).json()
    if not res.get("ok"):
        raise Exception(f"Blad pobierania sciezki pliku z Telegrama: {res}")
    
    file_path = res["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    
    audio_data = requests.get(download_url, timeout=DEFAULT_TIMEOUT).content
    with open(save_path, "wb") as f:
        f.write(audio_data)

class TelegramDeduplicator:
    """Wielowatkowy rejestr idempotencji i deduplikacji z oknem czasowym TTL."""
    def __init__(self):
        self._lock = threading.Lock()
        self._entries = {}  # key -> expire_at (float timestamp)

    def is_duplicate(self, key: str, ttl: float = 60.0) -> bool:
        if not key:
            return False
        now = time.time()
        with self._lock:
            # Czyszczenie przedawnionych wpisow
            expired_keys = [k for k, exp in self._entries.items() if exp <= now]
            for k in expired_keys:
                del self._entries[k]

            if key in self._entries:
                return True

            self._entries[key] = now + ttl
            return False

deduplicator = TelegramDeduplicator()

chat_locks = {}
chat_locks_guard = threading.Lock()

def get_chat_lock(chat_id):
    """Zwraca blokade serializacji per chat_id, zapobiegajac wyscigom w sesji agenta."""
    with chat_locks_guard:
        if chat_id not in chat_locks:
            chat_locks[chat_id] = threading.Lock()
        return chat_locks[chat_id]

def extract_dedup_info(msg):
    """Wyciaga unikalna sygnature wiadomosci oraz czas TTL."""
    if not isinstance(msg, dict):
        return None, 0.0

    chat_id = msg.get('chat', {}).get('id')

    # 1. Sprawdzenie mediow z unikalnym identyfikatorem Telegrama (file_unique_id)
    for media_type in ('voice', 'audio', 'video', 'document'):
        if media_type in msg and isinstance(msg[media_type], dict):
            file_unique_id = msg[media_type].get('file_unique_id') or msg[media_type].get('file_id')
            if file_unique_id:
                return f"{media_type}:{file_unique_id}", 300.0

    if 'photo' in msg and isinstance(msg['photo'], list) and len(msg['photo']) > 0:
        file_unique_id = msg['photo'][-1].get('file_unique_id') or msg['photo'][-1].get('file_id')
        if file_unique_id:
            return f"photo:{file_unique_id}", 300.0

    # 2. Wiadomosci tekstowe - okno 5 sekund na identyczna tresc od tego samego nadawcy
    if 'text' in msg and msg['text']:
        normalized_text = msg['text'].strip().lower()
        return f"text:{chat_id}:{normalized_text}", 5.0

    return None, 0.0

def delete_telegram_message_async(chat_id, message_id):
    """Asynchroniczne usuwanie zduplikowanej wiadomosci z czatu Telegrama (Auto-Purge)."""
    def _delete():
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token or not chat_id or not message_id:
            return
        url = f"https://api.telegram.org/bot{token}/deleteMessage"
        try:
            res = requests.post(url, json={"chat_id": chat_id, "message_id": message_id}, timeout=DEFAULT_TIMEOUT)
            log(f"[DEDUPLICATION] Auto-Purge: usunieto zduplikowana wiadomosc {message_id} z czatu {chat_id} (status: {res.status_code})")
        except Exception as e:
            log(f"[DEDUPLICATION] Blad usuwania zduplikowanej wiadomosci {message_id}: {e}")

    threading.Thread(target=_delete, daemon=True).start()

class TelegramTypingAction:
    """Wysyla okresowo akcje 'typing' do czatu Telegrama w trakcie transkrypcji i generowania odpowiedzi."""
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self._stop_event = threading.Event()
        self._thread = None

    def _loop(self):
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token or not self.chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendChatAction"
        while not self._stop_event.is_set():
            try:
                requests.post(url, json={"chat_id": self.chat_id, "action": "typing"}, timeout=DEFAULT_TIMEOUT)
            except Exception:
                pass
            self._stop_event.wait(4.0)

    def __enter__(self):
        if self.chat_id:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="TelegramTyping")
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)

def process_telegram_update(data):
    """Przetwarzanie wiadomości z Telegrama w osobnym wątku."""
    global whisper_model
    try:
        if 'message' in data:
            msg = data['message']
            sender = msg.get('from', {}).get('first_name', 'User')
            chat_id = msg.get('chat', {}).get('id')
            final_text = None
            
            with TelegramTypingAction(chat_id):
                if 'text' in msg:
                    final_text = msg['text']
                    log(f"[TELEGRAM] Tekst od {sender}: {final_text}")
                elif 'voice' in msg:
                    file_id = msg['voice']['file_id']
                    log(f"[TELEGRAM] Pobieranie notatki glosowej od {sender}...")
                    
                    import uuid
                    audio_path = os.path.join(BASE_DIR, f'temp_audio_{uuid.uuid4().hex}.ogg')
                    download_telegram_file(file_id, audio_path)
                    
                    if whisper_model is not None:
                        log("[TELEGRAM] Transkrypcja w toku...")
                        try:
                            segments, _ = whisper_model.transcribe(audio_path, beam_size=5, language='pl')
                            final_text = "".join([s.text for s in segments])
                            log(f"[TELEGRAM] Transkrypcja zakonczona: {final_text}")
                        except Exception as e:
                            log(f"[TELEGRAM] Blad CUDA/transkrypcji (mozliwa utrata kontekstu po hibernacji): {e}")
                            log("[TELEGRAM] Proba ponownego zaladowania modelu na GPU...")
                            try:
                                whisper_model = WhisperModel('large-v3', device='cuda', compute_type='float16')
                                segments, _ = whisper_model.transcribe(audio_path, beam_size=5, language='pl')
                                final_text = "".join([s.text for s in segments])
                                log(f"[TELEGRAM] Transkrypcja (po restarcie GPU) zakonczona: {final_text}")
                            except Exception as e2:
                                log(f"[TELEGRAM] Ponowna proba zawiodla: {e2}")
                    else:
                        log("[TELEGRAM] Blad: Model Whisper nie jest zaladowany na starcie, proba ladowania...")
                        try:
                            whisper_model = WhisperModel('large-v3', device='cuda', compute_type='float16')
                            segments, _ = whisper_model.transcribe(audio_path, beam_size=5, language='pl')
                            final_text = "".join([s.text for s in segments])
                            log(f"[TELEGRAM] Transkrypcja zakonczona: {final_text}")
                        except Exception as e3:
                            log(f"[TELEGRAM] Ostateczny blad ladowania Whispera: {e3}")
                else:
                    log(f"[TELEGRAM] Nieobslugiwany typ wiadomosci od {sender}. Klucze: {list(msg.keys())}")
                
                # Cleanup pliku audio (thread-safe)
                if 'audio_path' in dir() and audio_path and os.path.exists(audio_path):
                    try:
                        os.remove(audio_path)
                    except Exception:
                        pass
                
                if final_text and chat_id:
                    # Uruchomienie agenta i wyslanie odpowiedzi z blokada per-chat (ochrona przed wyscigiem)
                    with get_chat_lock(chat_id):
                        asyncio.run(reply_with_agent(final_text, chat_id))
                
    except Exception as e:
        import traceback
        log(f"[TELEGRAM] Blad przetwarzania: {e}\n{traceback.format_exc()}")

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
    
    # Czyszczenie spacji przed przecinkami/kropkami po wycieciu linkow
    text = re.sub(r'\s+([,\.\?!])', r'\1', text)
    
    # 2. Usuniecie poziomych kresek markdown (---, ***)
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    
    # 3. Konwersja tabel Markdown na pionowe karty mobilne
    text = convert_markdown_tables(text)
    
    # 4. Zamiana naglowkow markdown (### Tytul) na pogrubienie z odstepem
    text = re.sub(r'^\s*#{1,6}\s*(.+)$', r'\n**\1**\n', text, flags=re.MULTILINE)
    
    # 5. Escapowanie znakow specjalnych HTML (&, <, >)
    text = html.escape(text, quote=False)
    
    # 6. Konwersja formatowania Markdown na Telegram HTML
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'(?<![\w\*])\*([^\*\n]+?)\*(?![\w\*])', r'<i>\1</i>', text)
    text = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', text)
    text = text.replace(r'\|', '|')
    
    # 7. Normalizacja pustych linii (max 1 pusta linia miedzy blokami)
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
    text = convert_markdown_tables(text)
    text = re.sub(r'^\s*#{1,6}\s*(.+)$', r'\n\1\n', text, flags=re.MULTILINE)
    text = text.replace('**', '').replace('__', '').replace(r'\|', '')
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def send_telegram_message(chat_id, text, use_formatting=True):
    """
    Wysyla wiadomosc na Telegram z obsluga parse_mode='HTML',
    automatyczna sanityzacja tekstu oraz odpornym mechanizmem Fail-Safe (fallback plain-text).
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        log("[TELEGRAM] Blad: Brak TELEGRAM_BOT_TOKEN")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    if use_formatting:
        formatted_html = format_telegram_message(text)
        payload = {
            "chat_id": chat_id,
            "text": formatted_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            res = requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
            res_data = res.json()
            if res_data.get("ok"):
                log("[TELEGRAM] Wiadomosc wyslana w formacie HTML.")
                return True
            log(f"[TELEGRAM] HTML send failed ({res_data.get('description')}). Wykonuje awaryjny fallback do czystego tekstu...")
        except Exception as e:
            log(f"[TELEGRAM] Wyjatek podczas wysylki HTML: {e}. Wykonuje fallback...")

    # Awaryjny Fail-Safe Fallback: czysty tekst bez parse_mode
    clean_text = clean_plain_text(text) if use_formatting else text
    try:
        res = requests.post(url, json={"chat_id": chat_id, "text": clean_text}, timeout=DEFAULT_TIMEOUT)
        ok = res.json().get("ok", False)
        if ok:
            log("[TELEGRAM] Wiadomosc wyslana w trybie awaryjnym (Plain Text).")
        return ok
    except Exception as e:
        log(f"[TELEGRAM] Krytyczny blad wysylki wiadomosci na Telegram: {e}")
        return False

async def reply_with_agent(text, chat_id):
    from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
    from google.antigravity.hooks import policy
    from google.antigravity.types import SessionContinuationMode
    import uuid
    import datetime

    log(f"[AGENT] Uruchamianie agenta dla wiadomosci: {text[:30]}...")

    kalistenika_dir = str(WORKSPACE_DIR)

    # Wczytanie zunifikowanej tozsamosci z pliku
    coach_path = os.path.join(kalistenika_dir, '.agents', 'rules', 'project_coach.md')
    coach_rule = open(coach_path, encoding='utf-8').read() if os.path.exists(coach_path) else "Brak pliku project_coach.md"

    # Deterministyczny Dobowy RAM (reset o polnocy):
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    conv_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"telegram-{chat_id}-{today_str}"))
    current_model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    total_slots = len(key_pool.slots)
    if total_slots == 0:
        log("[AGENT] Blad krytyczny: Brak skonfigurowanych kluczy API w GeminiKeyPool!")
        send_telegram_message(chat_id, "❌ Błąd serwera: Brak aktywnych kluczy API w puli.", use_formatting=False)
        return

    # Pętla failover po slotach w puli (bez ślepego ponawiania na wyczerpanym kluczu)
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
                send_telegram_message(chat_id, reply_text, use_formatting=True)
                log("[AGENT] Wiadomosc wyslana na Telegram.")
                return  # Sukces!

        except Exception as e:
            error_str = str(e)
            log(f"[AGENT] Blad techniczny na kluczu {slot.name}: {error_str}")

            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                # Quota exceeded - natychmiastowy failover bez czekania i bez zapychania API
                is_daily = "GenerateRequestsPerDay" in error_str
                cooldown = 86400 if is_daily else 300
                key_pool.mark_slot_exhausted(slot, cooldown_seconds=cooldown)
                attempt += 1
                limit_type = "limit dobowy RPD" if is_daily else "limit per-minuta RPM"
                log(f"[POOL] Klucz {slot.name} wyczerpany ({limit_type}). Natychmiastowy failover na kolejny klucz w puli...")
                continue

            elif "503" in error_str or "UNAVAILABLE" in error_str:
                # Przeciążenie serwerów Google - krótka pauza 2s i rotacja
                log(f"[POOL] Blad 503 (serwery Google chwilowo niedostepne). Pauza 2s i failover...")
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
                # Inny krytyczny błąd (np. błąd logiczny) - nie marnujemy pozostałych kluczy w pętli
                log(f"[AGENT] Blad krytyczny niezwiązany z limitami API: {error_str}")
                break

    # Jeśli żaden klucz nie mógł zrealizować zapytania:
    wait_time = key_pool.get_min_wait_time()
    if wait_time > 0:
        error_msg = f"⏳ Wszystkie klucze API w puli wyczerpały swoje limity. Najbliższy klucz zwolni się za ok. {wait_time}s. Spróbuj ponownie za chwilę."
    else:
        error_msg = "❌ Wystąpił błąd przetwarzania wiadomości przez agenta AI. Spróbuj ponownie za jakiś czas."

    send_telegram_message(chat_id, error_msg, use_formatting=False)

@app.route('/telegram-webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"ok": True}), 200

    # 1. Idempotencja na poziomie calego obiektu Update (ochrona przed powtorzonym webhookiem)
    update_id = data.get('update_id')
    if update_id and deduplicator.is_duplicate(f"update:{update_id}", ttl=300.0):
        log(f"[DEDUPLICATION] Odrzucono powtorzony webhook update_id: {update_id}")
        return jsonify({"ok": True}), 200

    # 2. Deduplikacja i Auto-Purge na poziomie tresci wiadomosci (np. sync glitch z Wear OS)
    msg = data.get('message')
    if msg:
        chat_id = msg.get('chat', {}).get('id')
        message_id = msg.get('message_id')
        dedup_key, ttl = extract_dedup_info(msg)

        if dedup_key and deduplicator.is_duplicate(dedup_key, ttl=ttl):
            log(f"[DEDUPLICATION] Wykryto zduplikowana wiadomosc ({dedup_key}, msg_id: {message_id}). Auto-purge z czatu...")
            if chat_id and message_id:
                delete_telegram_message_async(chat_id, message_id)
            return jsonify({"ok": True}), 200

        # Odpalamy przetwarzanie w tle, żeby natychmiast zwrócić 200 OK do Telegrama
        threading.Thread(target=process_telegram_update, args=(data,)).start()

    return jsonify({"ok": True}), 200

@app.route('/voice', methods=['POST'])
def voice_inbox():
    data = request.get_json(silent=True)
    if not data or 'text' not in data:
        return jsonify({"status": "error", "message": "Brak pola text w JSON"}), 400
        
    text = data['text']
    inbox_path = os.path.join(WORKSPACE_DIR, 'voice_inbox.md')
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    
    with open(inbox_path, 'a', encoding='utf-8') as f:
        f.write(f'[{timestamp}] ZEGAREK: {text}\n')
        
    log(f'Odebrano notatke glosowa: {text}')
    return jsonify({"status": "success", "message": "Zapisano w skrzynce odbiorczej"}), 200

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
def catch_all(path):
    log(f"{request.method} {request.url}")

    data = request.get_json(silent=True)
    if request.method == 'POST' and data:
        # 1. Zapis surowego JSON (Data Lake)
        existing_data = {"workouts": []}
        if os.path.exists(OUTPUT_FILE):
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                try:
                    existing_data = json.load(f)
                    if isinstance(existing_data, list):
                        existing_data = {"workouts": existing_data}
                except Exception:
                    pass

        if "workouts" not in existing_data:
            existing_data["workouts"] = []

        existing_data['workouts'].append(data)
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        tmp_file = Path(OUTPUT_FILE).with_suffix('.json.tmp')
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, OUTPUT_FILE)

        log("Surowy JSON zapisany na dysku.")

        # 2. Automatyczne uruchomienie Parsera ETL -> SQLite
        try:
            process_data()
            log("Parser ETL ukonczyl prace. Baza SQLite zaktualizowana.")
        except Exception as e:
            log(f"BLAD PARSERA ETL: {e}")

        return jsonify({"status": "success", "message": "Dane przetworzone i zapisane w bazie SQL."}), 200

    return jsonify({"status": "ok"}), 200


def kill_port_5000():
    try:
        for conn in psutil.net_connections():
            if conn.laddr.port == 5000 and conn.status == 'LISTEN':
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
        log(f"Blad przy zwalnianiu portu 5000: {e}")

def cleanup_ngrok():
    try:
        ngrok.kill()
    except Exception:
        pass
    try:
        for p in psutil.process_iter(['name']):
            if p.info['name'] and 'ngrok' in p.info['name'].lower():
                p.terminate()
    except Exception:
        pass

def enforce_singleton_and_cleanup():
    kill_port_5000()
    cleanup_ngrok()

def start_watchdog(domain=None, port=5000):
    """
    Watchdog SRE w tle dbajacy o 100% dostepnosc:
    1. Sprawdza co 60s czy tunel Ngrok jest aktywny. Jesli spadl, podnosi go automatycznie.
    2. Sprawdza co 5 min status webhooka w Telegramie (getWebhookInfo). Jesli Telegram ma blad/oczekujace wiadomosci, wykonuje setWebhook.
    """
    if not domain:
        return

    def _watch_loop():
        time.sleep(15)  # Czas na pelny rozruch serwera i wstepne polaczenie
        webhook_check_counter = 0
        while True:
            try:
                time.sleep(60)
                # 1. Kontrola tunelu Ngrok
                try:
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
                            res = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=DEFAULT_TIMEOUT).json()
                            if res.get("ok"):
                                info = res.get("result", {})
                                last_err = info.get("last_error_message")
                                pending = info.get("pending_update_count", 0)
                                if last_err or (pending > 2):
                                    log(f"[WATCHDOG] Wykryto problem z webhookiem Telegrama (pending: {pending}, err: {last_err}). Re-rejestracja...")
                                    webhook_url = f"https://{domain}/telegram-webhook"
                                    requests.get(f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}", timeout=DEFAULT_TIMEOUT)
                                    log("[WATCHDOG] Webhook Telegrama zresetowany i odblokowany.")
                        except Exception as e:
                            log(f"[WATCHDOG] Blad sprawdzania webhooka Telegrama: {e}")

            except Exception as e:
                log(f"[WATCHDOG] Wyjatek w petli watchdoga: {e}")

    t = threading.Thread(target=_watch_loop, daemon=True, name="SRE-Watchdog")
    t.start()


if __name__ == '__main__':
    enforce_singleton_and_cleanup()
    log("=== START SERWERA ===")

    # Rejestracja czyszczenia zasobow wylacznie w procesie serwera
    atexit.register(cleanup_ngrok)
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    # Wstepna inicjalizacja modelu Whisper na GPU
    init_whisper()

    ngrok_domain = os.environ.get("NGROK_DOMAIN")
    try:
        if ngrok_domain:
            public_url = ngrok.connect(5000, domain=ngrok_domain)
        else:
            public_url = ngrok.connect(5000)
        log(f"Ngrok tunel aktywny: {public_url}")
    except Exception as e:
        log(f"Ngrok blad (moze juz dziala): {e}")

    if ngrok_domain:
        start_watchdog(domain=ngrok_domain, port=5000)
    app.run(host='0.0.0.0', port=5000, use_reloader=False)
