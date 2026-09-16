# 📋 Rejestr Zmian (CHANGELOG)

Wszystkie istotne zmiany i etapy ewolucji architektonicznej projektu **Project Coach** są dokumentowane w tym pliku.

Format oparty jest o [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/), a wersjonowanie stosuje zasady [Semantic Versioning](https://semver.org/).

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
- **Silnik idempotencji i Auto-Purge (TelegramDeduplicator — ADR-014):** Zabezpieczenie przed podwójnym wysyłaniem pakietów audio przez klienta Wear OS. Identyfikacja duplikatów po unikalnym ile_unique_id oraz samoczynne usuwanie nadmiarowych dymków przez API deleteMessage.
- **Wielokluczowy Failover Router (GeminiKeyPool — ADR-013):** Dynamiczna rotacja 3 niezależnych kluczy Google AI Studio z natychmiastowym przełączaniem (0ms) przy kodzie HTTP 429 i automatycznym cooldownem.
- **Serializacja zapytań do agenta (chat_lock):** Blokada współbieżności eliminująca wyścigi transakcyjne w plikach sesji i zabezpieczająca limity RPM.
- **Odporność środowiska hosta (Host Power SRE — ADR-015):** Konfiguracja profilu zasilania laptopa pod kątem Modern Standby S0 (brak uśpienia na AC, ochrona baterii Lenovo Conservation Mode ~80%, autologowanie ARSO).

---

## [1.3.0] - 2026-09-12
### Dodano
- **Dynamiczna kompensacja BMR (ADR-012):** Rozwiązanie problemu obcinania wydatku podstawowego przez Samsung Health do Google Health Connect.
- **Serwerowy algorytm Mifflina-St Jeora:** Dynamiczne doliczanie BMR na bazie bieżącej wagi z bazy SQLite przy odczycie poniżej 1500 kcal, zapewniające idealną zgodność z estymacjami zegarka.

---

## [1.2.0] - 2026-09-08
### Dodano
- **Mechanizm Store-and-Forward w MacroDroid:** Wdrożenie lokalnej kolejki buforującej notatki w telefonie na wypadek braku łączności z domowym serwerem.
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
- **Szyfrowany tunel HTTPS (Ngrok):** Bezpieczne wystawienie lokalnego serwera na żądania ze smartwatcha bez konieczności publicznego IP.
- **Surowy Data Lake:** Trwały zapis każdego przychodzącego payloadu JSON na dysku przed wykonaniem operacji ETL.

---

## [0.1-alpha] - 2026-08-01
### Dodano
- **Weryfikacja koncepcji (PoC):** Ręczne skrypty Pythona odpytujące API Google Fit i Strava.
- **Płaskie pliki CSV:** Podstawowa agregacja objętości treningowej w arkuszach kalkulacyjnych.
- **Identyfikacja tarcia manualnego:** Decyzja o konieczności budowy bezobsługowego potoku danych.
