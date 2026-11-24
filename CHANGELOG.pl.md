# 📋 Rejestr Zmian (CHANGELOG)

Wszystkie istotne zmiany i etapy ewolucji architektonicznej projektu **Project Coach** są dokumentowane w tym pliku.

Format oparty jest o [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/), a wersjonowanie stosuje zasady [Semantic Versioning](https://semver.org/).

---

## [2.5.0] - 2026-11-23
### Dodano
- **Brama Ingress Cloudflare Tunnels i utwardzenie perymetru:** Wdrożenie kontenerowego konektora `cloudflared` (`coach-tunnel`) nawiązującego wychodzący tunel QUIC do krawędzi Cloudflare z zerową liczbą otwartych portów przychodzących oraz całkowitą eliminacją ekspozycji publicznego IP.
- **Weryfikacja tokenu autoryzacyjnego Webhooka Telegrama:** Egzekwowanie nagłówka kryptograficznego `X-Telegram-Bot-Api-Secret-Token` dla przychodzących pakietów Telegrama, odrzucające nieautoryzowane wywołania POST (HTTP 403).
- **Wielousługowy stos Docker Compose i kolejka Redis:** Rozszerzenie stosu o usługę `coach-redis` (`redis:7-alpine`) do asynchronicznego odciążania zadań obok `project-coach-cpu` i `coach-tunnel`.
- **Biała lista kontekstu Docker (Enterprise Inverted Whitelist):** Wdrożenie ścisłej białej listy w modelu Zero-Trust (Default Deny) w `.dockerignore`, redukującej transfer kontekstu do 301 bajtów oraz całkowicie odcinającej kontener od plików Windows, pakietów testowych i sekretów hosta.
- **Ochrona dokumentacji w środowisku produkcyjnym:** Wygaszenie publicznego dostępu do Swagger UI (`/docs`), ReDoc (`/redoc`) oraz schematów `openapi.json` na produkcji.
- **Schematy architektury Retina 2x:** Aktualizacja schematów graficznych wysokiej rozdzielczości (`architecture.png`, `architecture.pl.png`) w polskiej i angielskiej wersji językowej, prezentujących stos Cloudflare Tunnels, kolejkę Redis oraz izolację usług.

### Zmieniono
- **Izolacja pętli zwrotnej portów:** Przypięcie portów usług ściśle do interfejsu pętli zwrotnej (loopback), eliminujące ryzyko ominięcia perymetru w sieci lokalnej.

### Usunięto
- **Wycofanie stosu procesów hosta:** Zakończenie działania procesów hosta (`ngrok.exe` i procesów `pythonw.exe`), gwarantujące wyłączność kontenera na zapis w bazie SQLite WAL.
- **Archiwizacja starszego serwera:** Przeniesienie implementacji Flask do `docs/_archiwum/` i zastąpienie `server/server.py` lekkim mostkiem zachowującym 100% kompatybilności testów jednostkowych (35/35).

---

## [2.4.0] - 2026-09-16
### Dodano
- **Konteneryzacja Docker w architekturze dwuprofilowej:** Wdrożono wielostopniowy `Dockerfile` (`python:3.13-slim-bookworm`) oraz profile w `docker-compose.yml`:
  - `cpu`: Lekki kontener (~350 MB) pod standardowe webhooki i zapytania do chmurowych modeli Gemini.
  - `gpu`: Akcelerowany kontener (~1.9 GB) z passthrough NVIDIA Container Toolkit dla lokalnego modelu Faster-Whisper (`large-v3`, CUDA float16).
- **Bezpieczne montowanie wolumenów dla SQLite WAL:** Host Bind Mount całego katalogu (`../kalistenika:/kalistenika`) zapewniający atomowość operacji VFS (`.db-wal`, `.db-shm`) i ochronę surowego Data Lake (`workouts.json.tmp` -> `os.replace`) przy regule Single-Writer.
- **Parametryzacja środowiskowa:** Obsługa zmiennych `KALISTENIKA_DIR` oraz `WHISPER_DEVICE` ze 100% kompatybilnością wsteczną dla natywnego środowiska Windows.

---

## [2.3.0] - 2026-09-16
### Dodano
- **Asynchroniczny silnik FastAPI & Uvicorn:** Migracja backendu produkcyjnego ze starszego Flaska do asynchronicznego FastAPI + Pydantic v2 na porcie 8000. Wdrożono ścisłą walidację modeli, interaktywny Swagger UI pod `/docs` oraz samonaprawiającego się watchdoga SRE z natychmiastowym rollbackiem (<5s).
- **Sanityzacja formatowania Telegram i mapowanie alertów GitHub:** Wzbogacenie formatera wiadomości o automatyczną translację alertów Markdown (`> [!NOTE]`, `> [!TIP]`, `> [!WARNING]`) na natywne oznaczenia mobilne oraz usuwanie znaczników cytowania.
- **Rozbudowany pakiet testów jednostkowych:** Rozszerzenie zestawu testów do 23 testów (`test_server_fastapi.py` i `test_server.py`) wykonujących się w 0.17s z pełną izolacją mockową.

### Naprawiono
- **Zgodność typowania uruchamiania procesów:** Usunięto błąd generycznego typowania `Popen[bytes]` na Pythonie 3.13 poprzez zastąpienie funkcyjnego monkeypatcha dedykowaną klasą `PatchedPopen` dla cichego uruchamiania procesów w tle.

---

## [2.2.0] - 2026-09-16
### Dodano
- **Wątek samonaprawczy SRE Watchdog:** Monitorujący wątek w tle sprawdzający aktywność tunelu co 60s (automatyczny auto-heal przy zerwaniu połączenia sieciowego) oraz audytujący stan webhooka Telegrama (`getWebhookInfo`) co 5 minut w celu uwalniania zatorów kolejki.
- **Wskaźnik UX "Project Coach pisze..." (`sendChatAction: typing`):** Wdrożenie klasy `TelegramTypingAction` gwarantującej natychmiastowy i ciągły feedback wizualny w aplikacji Telegram podczas transkrypcji mowy Whisper na GPU oraz wnioskowania agenta.
- **Inżynierski schemat architektury w PNG (Retina 2x):** Wygenerowanie i wdrożenie dwutorowych schematów architektury systemu w języku polskim i angielskim (`architecture.png`, `architecture.pl.png`), zastępujących zawodny silnik Mermaid na GitHubie.

### Naprawiono
- **Hermetyzacja cyklu życia i izolacja procesów:** Przeniesienie procedur czyszczenia wyłącznie do `__main__` i leniwa inicjalizacja Whispera (`init_whisper()`), dzięki czemu testy jednostkowe wykonują się w 0.04s bez obciążania GPU i bez zakłócania usług produkcyjnych.
- **Sanityzacja danych w mediach showcase:** Podmiana zrzutu ekranu w punkcie 7 na w 100% czysty plik (`showcase/telegram_bot.jpg`) eliminujący widoczne w tle ścieżki Windowsa.

---

## [2.1.0] - 2026-09-15
### Dodano
- **Dedykowany formater wiadomości mobilnych (Mobile UX Redesign):** Opracowano mechanizm prezentacji odpowiedzi zoptymalizowany pod wąskie ekrany smartfonów i zegarków w aplikacji Telegram.
- **Kompaktowe karty bilansu dobowego:** Wprowadzono czytelne punktory dla kluczowych parametrów (Zjedzone, Podaż białka, Stan dnia), eliminujące konieczność przewijania.
- **Kontekstowa pętla decyzyjna:** Agent w analizie na żywo uwzględnia bieżący plan jednostki treningowej (TRAINING DAY — PULL), pamięć posiłków z poprzednich dni oraz natychmiastowe bilansowanie makroskładników z notatki głosowej.

### Zmieniono
- **Eliminacja surowego formatu Markdown (GFM):** Zastąpiono tabele z separatorami | (które w Telegramie renderowały się jako nieczytelny blok tekstu) przejrzystym układem pionowym.
- **Oczyszczenie interfejsu konwersacyjnego:** Usunięto surowe znaczniki nagłówków ###, separatory --- oraz wycieki lokalnych ścieżek URI (ile:///).

---

## [2.0.0] - 2026-09-15
### Dodano
- **Dwukierunkowy interfejs mobilny Telegram Bot API:** Wdrożono endpoint /telegram-webhook do asynchronicznej wymiany wiadomości tekstowych i audio bezpośrednio ze smartwatcha i telefonu.
- **Lokalna transkrypcja mowy na GPU (Faster-Whisper):** Zintegrowano model large-v3 w trybie CUDA float16, eliminując zależność od chmurowych, płatnych API mowy.
- **Silnik idempotencji i Auto-Purge (TelegramDeduplicator):** Zabezpieczenie przed podwójnym wysyłaniem pakietów audio przez klienta Wear OS. Identyfikacja duplikatów po unikalnym ile_unique_id oraz samoczynne usuwanie nadmiarowych dymków przez API deleteMessage.
- **Wielokluczowy Failover Router (GeminiKeyPool):** Dynamiczna rotacja 3 niezależnych kluczy Google AI Studio z natychmiastowym przełączaniem (0ms) przy kodzie HTTP 429 i automatycznym cooldownem.
- **Serializacja zapytań do agenta (chat_lock):** Blokada współbieżności eliminująca wyścigi transakcyjne w plikach sesji i zabezpieczająca limity RPM.
- **Odporność środowiska hosta (Host Power SRE):** Konfiguracja profilu zasilania pod kątem Modern Standby S0 (brak uśpienia na AC, ochrona ogniw zasilania awaryjnego ~80%, autologowanie ARSO).

---

## [1.3.0] - 2026-09-12
### Dodano
- **Dynamiczna kompensacja BMR:** Rozwiązanie problemu obcinania wydatku podstawowego przez Samsung Health do Google Health Connect.
- **Serwerowy algorytm Mifflina-St Jeora:** Dynamiczne doliczanie BMR na bazie bieżącej wagi z bazy SQLite przy odczycie poniżej 1500 kcal, zapewniające idealną zgodność z estymacjami zegarka.

---

## [1.2.0] - 2026-09-08
### Dodano
- **Mechanizm Store-and-Forward w MacroDroid:** Wdrożenie lokalnej kolejki buforującej notatki w telefonie na wypadek braku łączności z serwerem brzegowym.
- **Buforowanie ze separatorem |:** Zapisywanie pakietów telemetrycznych i automatyczne opróżnianie kolejki po wznowieniu połączenia.

---

## [1.0.0] - 2026-09-01
### Dodano
- **Demon systemowy Windows:** Skrypt VBS (start_serwera.vbs) uruchamiający serwer Flask w tle bez widocznego okna konsoli (pythonw) przy starcie systemu.
- **Relacyjna baza SQLite i potok ETL (etl_parser.py):** Bezpieczna transformacja surowego JSON-a do tabel SQL metryki_dzienne i 	reningi.
- **Mechanizm Sanity Check:** Walidacja wprowadzanych danych i blokada skrajnych anomalii (np. literówki w wadze) chroniąca spójność średnich kroczących.

---

## [0.5.0] - 2026-08-20
### Dodano
- **Architektura zdarzeniowa (Push zamiast Pull):** Zastąpienie okresowego pobierania danych pasywnym odbieraniem webhooków w czasie rzeczywistym.
- **Szyfrowana brama HTTPS:** Bezpieczne wystawienie lokalnego serwera na żądania telemetryczne bez konieczności publicznego IP i przekierowywania portów.
- **Surowy Data Lake:** Trwały zapis każdego przychodzącego payloadu JSON na dysku przed wykonaniem operacji ETL.

---

## [0.1-alpha] - 2026-08-01
### Dodano
- **Weryfikacja koncepcji (PoC):** Ręczne skrypty Pythona odpytujące API Google Fit i Strava.
- **Płaskie pliki CSV:** Podstawowa agregacja objętości treningowej w arkuszach kalkulacyjnych.
- **Identyfikacja tarcia manualnego:** Decyzja o konieczności budowy bezobsługowego potoku danych.
