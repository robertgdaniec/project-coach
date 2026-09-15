# Architektura Systemu - Project Coach

## 1. Diagram Przepływu Danych (Data Flow Diagram)

```mermaid
graph TD
    SW["Samsung Watch / Smartfon"] -->|Telemetria HTTP POST| Ngrok["Ngrok HTTPS Tunnel"]
    SW -->|Audio / Czat Telegram| TG["Telegram Bot API"]
    TG -->|Webhook HTTP POST| Ngrok
    
    Ngrok -->|Przekierowanie| Flask["Flask Server (port 5000)"]
    
    Flask -->|endpoint /voice| VI["voice_inbox.md"]
    Flask -->|endpoint /* (catch-all)| WJ["workouts.json (Data Lake)"]
    Flask -->|endpoint /telegram-webhook| DEDUP["TelegramDeduplicator (Auto-Purge)"]
    DEDUP -->|Unikalne audio| WSP["Lokalny Whisper (GPU large-v3)"]
    DEDUP -.->|Duplikat z Wear OS| DEL["Telegram API deleteMessage"]
    
    WSP -->|Transkrybowany tekst| GKP["GeminiKeyPool (3 klucze API)"]
    GKP -->|Failover Router| OMNI["Omni-Agent (project_coach.md)"]
    
    WJ -->|Trigger| ETL["etl_parser.py"]
    ETL -->|Zapis danych ustrukturyzowanych| DB[("baza_kalistenika.db (SQLite)")]
    
    subgraph "Projekt Kalistenika"
        VI
        DB
        OMNI
        NL["nutrition_log.md"]
    end
    
    OMNI -->|Zapis/Odczyt| NL
    OMNI -->|Zapis/Odczyt| DB
    OMNI -->|Odpowiedź czatu| TG
```

## 2. Schemat Bazy Danych

Aktualne tabele zarządzane przez `etl_parser.py`:

*   **`metryki_dzienne`**
    *   `data TEXT PRIMARY KEY`
    *   `kroki INTEGER`
    *   `spalone_kalorie REAL`
    *   `waga REAL`
    *   `hrv_rmssd REAL`
    *   `vo2_max REAL`
    *   `hr_rest INTEGER`
*   **`treningi`**
    *   `id TEXT PRIMARY KEY`
    *   `data TEXT`
    *   `typ TEXT`
    *   `czas_trwania_min REAL`
    *   `hr_avg INTEGER`
    *   `hr_max INTEGER`
    *   `strefa_1_min REAL`
    *   `strefa_2_min REAL`
    *   `strefa_3_min REAL`
    *   `strefa_4_min REAL`
    *   `strefa_5_min REAL`
    *   `notatki_treningowe` (relacyjnie obsługiwana przez ETL)

## 3. Tabela Endpointów API

| Metoda HTTP | Endpoint | Opis |
|---|---|---|
| `POST` | `/telegram-webhook` | Odbiera wiadomości i notatki głosowe z Telegrama. Transkrybuje audio przez Whisper GPU, wywołuje Omni-Agenta via `GeminiKeyPool` i odsyła odpowiedź. |
| `POST` | `/voice` | Odbiera surowe notatki głosowe z zegarka (`{"text": "..."}`). Zapisuje do `voice_inbox.md`. |
| `POST` | `/*` (catch-all) | Odbiera webhooki z payloadem JSON (Samsung Health). Dopisywane do `workouts.json` i wywołuje trigger dla `etl_parser.process_data()`. |
| `GET` | `/*` (catch-all) | Healthcheck. Zwraca `{"status": "ok"}`. |

## 4. Konfiguracja Stref Tętna (Heart Rate Zones)

*   **MAX_HR** = 185
*   **Strefa 1:** < 60% (< 111 bpm)
*   **Strefa 2:** 60-70% (111-130 bpm)
*   **Strefa 3:** 70-80% (130-148 bpm)
*   **Strefa 4:** 80-90% (148-167 bpm)
*   **Strefa 5:** 90-100% (167-185 bpm)

> **Heurystyka:** Wartości są wyliczane poprzez pomnożenie liczby próbek (sample counts) przez 5, przy założeniu 5-minutowych interwałów próbkowania z zegarka.

## 5. Zależności Międzyprojektowe

```mermaid
graph LR
    subgraph "Project Coach (Źródło)"
        Srv["server.py"]
        ETL["etl_parser.py"]
    end
    
    subgraph "kalistenika (Cel)"
        VI["voice_inbox.md"]
        WJ["workouts.json"]
        DB[("baza_kalistenika.db")]
        Log["server_log.txt"]
        R_Diet["Reguła Dietetyk"]
        R_Tren["Reguła Trener"]
    end
    
    Srv -->|Zapis POST /voice| VI
    Srv -->|Zapis POST /*| WJ
    Srv -->|Logowanie HTTP| Log
    
    ETL -->|Odczyt| WJ
    ETL -->|Zapis (INSERT/UPDATE)| DB
    ETL -->|Logowanie statusów| Log
    
    VI -.->|Zależność| R_Diet
    DB -.->|Zależność| R_Tren
```

## 6. Procesy w tle i Autostart

*   **`start_serwera.vbs`** znajduje się w folderze Autostart systemu Windows.
*   Skrypt VBS tworzy `WScript.Shell` i uruchamia `python server.py` z ukrytym oknem (parametr `0, False`).
*   **Hacking konsoli:** `server.py` wewnętrznie wykorzystuje *monkeypatching* na `subprocess.Popen`, wstrzykując flagę `STARTF_USESHOWWINDOW`. Zapobiega to pojawieniu się okna konsoli podczas uruchamiania procesu `ngrok.exe`.
*   **Ngrok:** Uruchamiany programowo poprzez bibliotekę pyngrok: `pyngrok.ngrok.connect(5000, domain=...)`.

## 7. Środowisko Hosta i Zarządzanie Energią (Power Management SRE)

Dla zapewnienia nieprzerwanej dostępności usług w architekturze Modern Standby (S0 Low Power Idle) na dedykowanym hoście z GPU NVIDIA:
*   **Zasilanie sieciowe (AC):**
    *   Wyłączenie ekranu (`VIDEOIDLE`): 5–15 min (bezpieczne odcięcie zasilania matrycy bez dławienia procesów).
    *   Uśpienie (`STANDBYIDLE`): **Nigdy (0)** – uśpienie S0 zamraża procesy Win32, usypia GPU (CUDA) i zrywa tunel ngrok.
    *   Hibernacja (`HIBERNATEIDLE`): **Nigdy (0)**.
    *   Akcja zamknięcia pokrywy (`LIDACTION`): **Nic nie rób (0)**.
*   **Ochrona baterii (Conservation Mode):**
    *   Włączony **Tryb konserwacji** blokujący ładowanie do ~75–80%, eliminujący degradację ogniw Li-Ion i ryzyko spuchnięcia baterii przy pracy 24/7 pod ładowarką.
*   **Odporność na restarty (Windows Update):**
    *   Włączenie w *Konta → Opcje logowania* opcji automatycznego dokończenia konfiguracji po aktualizacji (ARSO - Automatic Restart Sign-On), co gwarantuje podniesienie sesji i skryptu `start_serwera.vbs`.

## 8. Silnik Idempotencji i Deduplikacji (TelegramDeduplicator & Auto-Purge)

W celu eliminacji błędu wielokrotnego wysyłania tych samych notatek głosowych ze smartwatchy (Samsung Galaxy Watch z Wear OS) w potoku sieciowym wdrożono:
*   **Pamięciowy Rejestr Unikalności (`TelegramDeduplicator`):** Śledzi globalne identyfikatory `file_unique_id` (audio, TTL 300s), skróty treści tekstowej (TTL 5s) oraz `update_id` webhooków (TTL 300s), synchronizowany przez `threading.Lock`.
*   **Auto-Purge w UI Telegrama:** Po wykryciu duplikatu serwer natychmiast przerywa przetwarzanie i asynchronicznie wywołuje `deleteMessage` na identyfikatorze drugiej wiadomości. Eliminuje to nadmiarowy dymek na ekranie zegarka/telefonu użytkownika.
*   **Serializacja Sesji Agenta (`get_chat_lock`):** Zabezpiecza przed współbieżnym odpytywaniem tego samego `conversation_id` przy szybkim nadejściu kilku różnych wiadomości, chroniąc bazę sesji i limit 5 RPM w darmowym tierze Gemini API.


