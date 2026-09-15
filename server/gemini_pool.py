import os
import time
import logging
import threading
from typing import List, Optional, Dict, Any

logger = logging.getLogger("GeminiKeyPool")


class AllKeysExhaustedError(Exception):
    """Wyjątek rzucany, gdy wszystkie klucze w puli przekroczyły swoje limity quota."""
    pass


class KeySlot:
    def __init__(self, key: str, index: int):
        self.key = key.strip()
        self.name = f"Key-{index + 1} (..{self.key[-6:] if len(self.key) >= 6 else self.key})"
        self.cooldown_until: float = 0.0
        self.failures: int = 0
        self.successes: int = 0

    @property
    def is_available(self) -> bool:
        return time.time() >= self.cooldown_until

    def mark_exhausted(self, cooldown_seconds: int = 300):
        self.cooldown_until = time.time() + cooldown_seconds
        self.failures += 1
        logger.warning(
            f"Klucz {self.name} przekroczył limit (429 Quota Exceeded). "
            f"Trafia na ławkę rezerwowych na {cooldown_seconds}s."
        )

    def mark_success(self):
        self.successes += 1
        self.cooldown_until = 0.0


class GeminiKeyPool:
    """
    Client-Side API Key Pool & Failover Router dla Google Gemini API / Antigravity SDK.
    Obsługuje automatyczną rotację, cooldown przy kodzie 429 i natychmiastowy failover między wieloma kontami.
    """
    def __init__(
        self,
        model_name: str = "gemini-3.5-flash-lite",
        default_cooldown: int = 300,
        keys: Optional[List[str]] = None
    ):
        self.model_name = model_name
        self.default_cooldown = default_cooldown
        self._lock = threading.Lock()
        self._current_index = 0

        # Odkrywanie kluczy z argumentów lub zmiennych środowiskowych
        discovered_keys = keys or self._discover_keys_from_env()
        if not discovered_keys:
            logger.error("Brak dostępnych kluczy GEMINI_API_KEY w środowisku!")

        self.slots: List[KeySlot] = [
            KeySlot(k, i) for i, k in enumerate(discovered_keys) if k and k.strip()
        ]
        logger.info(f"Zainicjalizowano GeminiKeyPool z {len(self.slots)} kluczem/kluczami dla modelu {model_name}.")

    def _discover_keys_from_env(self) -> List[str]:
        try:
            from dotenv import load_dotenv
            env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
            if os.path.exists(env_file):
                load_dotenv(env_file)
            load_dotenv()
        except ImportError:
            pass

        keys = []
        # 1. Sprawdzenie listy po przecinku: GEMINI_API_KEYS
        raw_keys = os.environ.get("GEMINI_API_KEYS", "")
        if raw_keys:
            for k in raw_keys.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys:
                    keys.append(k_clean)

        # 2. Sprawdzenie kluczy numerowanych: GEMINI_API_KEY_1, GEMINI_API_KEY_2, etc.
        idx = 1
        while True:
            key_n = os.environ.get(f"GEMINI_API_KEY_{idx}")
            if key_n and key_n.strip():
                k_clean = key_n.strip()
                if k_clean not in keys:
                    keys.append(k_clean)
                idx += 1
            else:
                break

        # 3. Fallback do standardowego GEMINI_API_KEY
        single_key = os.environ.get("GEMINI_API_KEY")
        if single_key and single_key.strip():
            k_clean = single_key.strip()
            if k_clean not in keys:
                keys.append(k_clean)

        return keys

    def get_active_slot(self) -> Optional[KeySlot]:
        """Zwraca aktualny dostępny slot klucza lub przełącza na kolejny dostępny."""
        with self._lock:
            if not self.slots:
                return None
            total = len(self.slots)
            for i in range(total):
                idx = (self._current_index + i) % total
                if self.slots[idx].is_available:
                    self._current_index = idx
                    return self.slots[idx]
            return None

    def rotate_to_next_slot(self) -> Optional[KeySlot]:
        """Przesuwa indeks na następny slot i zwraca pierwszy dostępny."""
        with self._lock:
            if not self.slots:
                return None
            total = len(self.slots)
            start_idx = (self._current_index + 1) % total
            for i in range(total):
                idx = (start_idx + i) % total
                if self.slots[idx].is_available:
                    self._current_index = idx
                    return self.slots[idx]
            return None

    def mark_slot_exhausted(self, slot: KeySlot, cooldown_seconds: Optional[int] = None):
        """Oznacza podany slot jako wyczerpany i nakłada cooldown."""
        with self._lock:
            cd = cooldown_seconds if cooldown_seconds is not None else self.default_cooldown
            slot.mark_exhausted(cd)
            total = len(self.slots)
            if total > 0:
                self._current_index = (self._current_index + 1) % total

    def mark_slot_success(self, slot: KeySlot):
        """Oznacza sukces operacji na danym slocie."""
        with self._lock:
            slot.mark_success()

    def get_min_wait_time(self) -> int:
        """Zwraca liczbę sekund do zwolnienia najbliższego slotu."""
        with self._lock:
            if not self.slots:
                return 0
            now = time.time()
            cooldowns = [max(0, int(s.cooldown_until - now)) for s in self.slots]
            return min(cooldowns) if cooldowns else 0

    def get_status(self) -> List[Dict[str, Any]]:
        with self._lock:
            now = time.time()
            return [
                {
                    "name": slot.name,
                    "available": slot.is_available,
                    "cooldown_remaining_sec": max(0, int(slot.cooldown_until - now)),
                    "successes": slot.successes,
                    "failures": slot.failures
                }
                for slot in self.slots
            ]

    def generate_content(self, prompt: str, **kwargs) -> Any:
        """
        Zgodność z google.generativeai dla wywołań jednorazowych.
        """
        import google.generativeai as genai
        from google.api_core.exceptions import ResourceExhausted, GoogleAPICallError

        if not self.slots:
            raise AllKeysExhaustedError("Brak skonfigurowanych kluczy w GeminiKeyPool.")

        attempts = 0
        total_slots = len(self.slots)

        while attempts < total_slots:
            slot = self.get_active_slot()
            if not slot:
                break

            try:
                genai.configure(api_key=slot.key)
                model = genai.GenerativeModel(self.model_name)
                response = model.generate_content(prompt, **kwargs)
                self.mark_slot_success(slot)
                return response
            except ResourceExhausted:
                self.mark_slot_exhausted(slot, self.default_cooldown)
                attempts += 1
                logger.info("Automatyczny failover na kolejny klucz w puli...")
            except GoogleAPICallError as e:
                if "API_KEY_INVALID" in str(e) or "403" in str(e):
                    logger.error(f"Klucz {slot.name} jest nieprawidłowy! Wykluczam z puli na 24h.")
                    self.mark_slot_exhausted(slot, cooldown_seconds=86400)
                    attempts += 1
                else:
                    raise e

        wait_time = self.get_min_wait_time()
        raise AllKeysExhaustedError(
            f"Wszystkie {total_slots} klucze w puli wyczerpały swoje limity. "
            f"Najbliższy klucz będzie dostępny za ok. {wait_time}s."
        )
