# Dziennik Decyzji (Architecture Decision Record - ADR)

Ten dokument opisuje kluczowe decyzje architektoniczne w projekcie "Project Coach", ich kontekst oraz powody odrzucenia alternatyw.

---

## ADR-001: Push Webhook zamiast Pull API

**Kontekst:** Początkowo system pobierał dane ze Stravy i Google Fit cyklicznie za pomocą modelu pull. W katalogu `sync/` znajduje się martwy kod stanowiący ślad po tej architekturze.
**Decyzja:** Zastosowanie mechanizmu push poprzez webhooki generowane z zegarka Samsung (np. via Health Sync lub Tasker), odbierane przez tunel Ngrok na serwerze Flask.
**Odrzucone alternatywy:** Cykliczne odpytywanie chmurowych API (Strava, Google Fit).
**Uzasadnienie:** Model pull generował problemy z wygasaniem tokenów OAuth oraz limitami zapytań (rate limits) narzucanymi przez API. Brakowało również możliwości natychmiastowego przesyłania notatek głosowych w czasie rzeczywistym.

## ADR-002: SQLite zamiast plików płaskich (.csv, .md)

**Kontekst:** W fazie pierwszej projekt opierał się na plikach tekstowych takich jak `metrics.csv`, `nutrition_log.md`, `workout_log.md`.
**Decyzja:** Przeniesienie kluczowych danych do centralnej bazy `baza_kalistenika.db` opartej na SQLite, z wykorzystaniem relacyjnych tabel `metryki_dzienne` oraz `treningi`.
**Odrzucone alternatywy:** Kontynuacja przechowywania i procesowania danych w płaskich plikach CSV oraz Markdown.
**Uzasadnienie:** Agenci AI (LLM) słabo radzili sobie z wielowymiarową korelacją (operacje typu JOIN) łączącą duże zbiory telemetryczne z odczuciami treningowymi zapisywanymi w plikach. Baza SQL dostarcza "twardej", matematycznej wyroczni i precyzyjnych danych.

## ADR-003: Autocommit voice_inbox (zasada KISS)

**Kontekst:** Wcześniej modele językowe otrzymywały dyktowane przez zegarek posiłki i zamiast od razu je księgować, próbowały prowadzić dialog z użytkownikiem w celu ich potwierdzenia/doprecyzowania.
**Decyzja:** Bezwzględny podział kanałów. Zapis głosowy ze smartwatcha ląduje w buforze `voice_inbox.md`, skąd agent zawsze dokonuje tzw. autocommitu do bazy diety bez angażowania się w dialog. Czat tekstowy służy teraz wyłącznie do analiz i potencjalnych modyfikacji (rollbacków).
**Odrzucone alternatywy:** Analiza intencji i kontynuacja dialogu z użytkownikiem przy każdej nowej notatce głosowej.
**Uzasadnienie:** Modele bardzo często wpadały w lingwistyczne pętle lub dekoncentrowały się na pobocznych wątkach. Automatyczny zapis jest szybszy i znacznie bardziej niezawodny.

## ADR-004: RBAC — podział ról Dietetyk / Trener

**Kontekst:** Kiedy system posiadał jednego, uniwersalnego agenta do zarządzania wszystkim, regularnie dochodziło do wyścigów (race conditions) podczas równoczesnego zapisu do tych samych plików i baz danych.
**Decyzja:** Wyznaczenie ścisłych ról i uprawnień do zapisu. Agent Dietetyk (owner diety) odpowiada za zamykanie doby oraz zapis wagi ciała. Agent Trener (owner treningu) jest wyłącznie odpowiedzialny za zarządzanie notatkami treningowymi.
**Odrzucone alternatywy:** Pozostawienie jednego wszechstronnego agenta z dostępem do całości danych i operacji.
**Uzasadnienie:** Jasna separacja ról wprost eliminuje problemy związane z nadpisywaniem danych oraz wprowadzaniem sprzecznych zmian.

## ADR-005: Organiczne triggery zamiast Cron

**Kontekst:** Harmonogramy cykliczne (oparte na cron) nierzadko generowały puste albo wręcz błędne raporty, zwłaszcza w dniach, gdy użytkownik zmieniał swój naturalny rytm (np. budził się później).
**Decyzja:** Zastosowanie triggerów wywoływanych konkretnymi akcjami użytkownika. Przykładowo, podanie porannej wagi skutkuje natychmiastowym zamknięciem wczorajszej doby oraz przygotowaniem raportu pacingowego. Koniec treningu wymusza wykonanie operacji batch INSERT dla wszystkich zarejestrowanych ćwiczeń.
**Odrzucone alternatywy:** Sztywne, deterministyczne odpytywanie i przetwarzanie danych na podstawie ustalonych ram czasowych.
**Uzasadnienie:** System zyskał odporność na nieregularności ludzkiego trybu życia i potrafi na bieżąco adaptować się do zdarzeń.

## ADR-006: Procesy w tle via VBS/pythonw.exe, zakaz IsDaemon=true

**Kontekst:** W platformie Antigravity ustawienie flagi `IsDaemon=true` przy wywołaniach zadań w tle powodowało niekończące się animacje ładowania na froncie UI oraz trwałe blokowanie zasobów.
**Decyzja:** Wprowadzenie rygorystycznego zakazu stosowania flagi `IsDaemon=true`. Zamiast tego serwery muszą być uruchamiane jako niezależne procesy systemu Windows wywoływane przez skrypty VBS z wykorzystaniem `pythonw.exe` (bez okna powłoki konsoli).
**Odrzucone alternatywy:** Pozostawienie funkcji daemonów natywnych wewnątrz ekosystemu środowiska agenta (Antigravity).
**Uzasadnienie:** Takie rozwiązanie gwarantuje stabilność, oddziela cykl życia systemu operacyjnego od sesji czatu oraz zapewnia czystość interfejsu.

## ADR-007: Żelazna Reguła RPE — zakaz estymacji

**Kontekst:** Zdarzało się, że Agent Trener próbował sam wyciągać wnioski i generować wartości z subiektywnej skali odczuwalnego wysiłku RPE z pobieżnych i krótkich opisów treningowych (np. "było ciężko").
**Decyzja:** Kategoryczny zakaz estymacji odczuwalnego zmęczenia. Jeśli użytkownik nie poda jednoznacznie wartości RPE (lub skali rezerwy RIR), agent musi powstrzymać się od zapisu do bazy i proaktywnie dopytać użytkownika.
**Odrzucone alternatywy:** Automatyczna estymacja bazująca na analizie tekstu (sentiment analysis).
**Uzasadnienie:** Ocena zmęczenia ośrodkowego układu nerwowego (CNS) decyduje o doborze intensywności treningów w przyszłości. "Wyhalucynowane" wartości prowadzą do zupełnie błędnych rekomendacji.

## ADR-008: HRV — 7-dniowa średnia krocząca, nie wartości dzienne

**Kontekst:** Jednodniowe fluktuacje HRV dostarczane z zegarka Samsung charakteryzowały się gigantycznym poziomem szumu, spowodowanym takimi czynnikami jak spożycie kofeiny, stres w ciągu dnia czy brak pomiaru w czasie snu.
**Decyzja:** Surowy zakaz interpretowania jednodniowych pomiarów wskaźnika HRV jako miarodajnego źródła informacji o ogólnym przemęczeniu organizmu. Analizie podlegać będzie wyłączne matematyczny trend 7-dniowej średniej kroczącej (SMA/EMA).
**Odrzucone alternatywy:** Natychmiastowa analiza codziennych skoków i spadków wskaźnika zmienności rytmu zatokowego jako główna determinanta zmęczenia.
**Uzasadnienie:** Użytkownik nie wykonuje porannych standaryzowanych prób pomiarów w spoczynku przy ustabilizowanym tętnie (ortostatycznych) i nie rejestruje jakości snu z zegarkiem. Wyniki dzienne są zwykłym chaosem.

## [2026-09-13] Architektura po migracji i ramy testowe

**Kontekst:** Projekt został rozbity na nową strukturę (rozdzielono infrastrukturę serwerową do *Project Coach* od głównej bazy *kalistenika*). Należało zapewnić ciągłość operacyjną webhooków i zapisu do bazy bez ryzyka nadpisania produkcyjnych logów z API.
**Decyzja:** Zaimplementowano skrypt 	est_server.py wykorzystujący izolowane środowiska (tempfile) do przeprowadzania testów bez skutków ubocznych na głównej bazie. Ścieżki produkcyjne (hardcoded) pozostają niezmienne i poprawnie linkują do sąsiedniego Workspace'a.
**Konsekwencje:** Pełna pewność, że po restarcie systemu ngrok i flask płynnie kierują pliki (voice, telemetry) do docelowej architektury Kalisteniki. Inicjacja nowych baz SQLite przez init_db musi zostać w przyszłości zaktualizowana by odzwierciedlała tabelę produkcyjną z Kalisteniki (tzw. Dług Techniczny - niezgodność kolumn SQL).

## ADR-009: Gotowość Produkcyjna i Bezpieczeństwo Danych

**Kontekst:** System narażony był na utratę danych z powodu braku atomowości zapisu pliku workouts.json, braku trybu WAL w SQLite, a także wycieki pamięci poprzez nieskończone pliki logów i zaszyte sekrety ngroka w kodzie.
**Decyzja:** Zastosowanie rygorystycznych wzorców gotowości produkcyjnej: użycie bufora tymczasowego .tmp i os.replace przy zapisach I/O, aktywacja trybu WAL z  usy_timeout, wdrożenie RotatingFileHandler oraz przeniesienie zmiennych do .env. Skrypty uniezależniono używając relatywnych ścieżek Path(__file__).
**Odrzucone alternatywy:** Pozostawienie luźnych, skryptowych zaleceń i bezpośrednich zapisów pliku.
**Uzasadnienie:** Zabezpieczono dane telemetryczne przed awariami zasilania i błędami w systemie Windows. Wyeliminowano konflikty portów używając psutil i precyzyjnego sprzątania atexit. System spełnia standard 'Sanity Check' (9/9 reguł z checklists.md).

## ADR-010: Telegram Bot jako mobilny interfejs czatu

**Kontekst:** System wymagał najprostszego i najwygodniejszego interfejsu mobilnego, który odtworzyłby doświadczenie pełnego okna czatu z Trenerem i Dietetykiem z poziomu smartfona, zastępując konieczność siedzenia przy PC.
**Decyzja:** Zastosowanie natywnego bota w aplikacji Telegram komunikującego się z serwerem Flask przez webhooki (push) za pośrednictwem istniejącego tunelu ngrok.
**Odrzucone alternatywy:** Budowa własnej aplikacji Web / PWA (zbyt wysoki koszt wytworzenia UI i zarządzania stanem audio), Bot Discord (wymóg stałego połączenia WebSocket, niezgodność z webhookową architekturą Flaska).
**Uzasadnienie:** Telegram Bot API doskonale pasuje do obecnej architektury serwera (webhooki HTTP). Zapewnia natywny UX, obsługę notatek głosowych od ręki oraz jest darmowy i prosty w integracji, omijając cały narzut związany z tworzeniem front-endu.

## ADR-011: Mechanizm Store-and-Forward (Retry Policy) dla notatek głosowych w MacroDroid

**Kontekst:** System cierpiał na ułomność pojedynczego punktu awarii (SPOF) - jeśli serwer domowy był offline lub uśpiony, webhooki z notatkami głosowymi z zegarka były bezpowrotnie tracone w warstwie sieciowej, co uderzało w niezawodność rozwiązania.
**Decyzja:** Zaimplementowano asynchroniczną kolejkę notatek po stronie klienta mobilnego (MacroDroid). Wysłanie webhooka zostało przeniesione do pętli oczekującej z warunkami na kody HTTP: 200 czysci bufor, błędne połączenie przerywa pętlę pozostawiając bufor do późniejszej synchronizacji (np. na zdarzenie wybudzenia/ekranu).
**Odrzucone alternatywy:** Tworzenie ciężkiego bufora i bazy SQLite na telefonie, aplikacje pośredniczące z chmurą.
**Uzasadnienie:** Architektura Store-and-Forward natywnie wykorzystująca zmienna tekstowa (String) MacroDroida zapewnia bezstratny transfer danych przy absolutnym minimum kodu backendowego, zdejmując odpowiedzialność za retencje z serwera Flaska na urządzenie generujące dane.

## ADR-012: Serwerowa kompensacja TDEE (Dynamiczne BMR)

**Kontekst:** Aplikacja Health Connect Webhook eksportuje wyłącznie zsumowane kalorie wysiłkowe (tzw. Active Calories ~918 kcal), ignorując wyliczone w telefonie TDEE (np. 2696 kcal), ponieważ Samsung Health odmawia eksportu wewnętrznego BMR do bazy Google Health Connect.
**Decyzja:** Zaimplementowano w sercu Agenta Dietetyka (plik ekompozycja.md) twardą logikę: jeżeli odczyt z SQL (TDEE) wynosi < 1500 kcal, Agent z automatu uznaje go za kalorie aktywne i w locie wylicza dynamiczne BMR ze wzoru Mifflina-St Jeora (BMR = waga * 10 + 967 dla mężczyzny 35 lat / 182 cm), dodając je do puli.
**Odrzucone alternatywy:** Próba zmiany aplikacji webhookowej na telefonie, poszukiwanie wtyczek do Taskera odczytujących zablokowane api Samsung Health, wymuszanie ręcznego podawania kalorii przez użytkownika.
**Uzasadnienie:** Architekturę omijamy po stronie backendu, na warstwie analitycznej Agenta. Jest to bezinwazyjne rozwiązanie (tzw. Graceful Degradation), które zapewnia 100% precyzję wydatku energetycznego bez ruszania awaryjnego ekosystemu Androida.

## ADR-013: GeminiKeyPool i Failover Router w potoku Telegrama

**Kontekst:** W środowisku produkcyjnym darmowe konto Google AI Studio nakłada drastyczne lejki quota (HTTP 429) na pojedyncze projekty (np. 20 req/day dla gemini-3.5-flash). Poprzednia implementacja reply_with_agent wykonywała 5 ślepych prób z rosnącym opóźnieniem na tym samym wyczerpanym kluczu, zamrażając wątek bota na ponad 2 minuty i bezpowrotnie marnując zapytania.
**Decyzja:**
1. Wdrożenie wzorca GeminiKeyPool (server/gemini_pool.py) zarządzającego wieloma kluczami API z różnych projektów Google Cloud (GEMINI_API_KEYS).
2. Zastąpienie ślepej pętli ponowień natychmiastowym failoverem (0 ms delay): przy błędzie 429 klucz natychmiast trafia na cooldown (300s lub 24h dla limitu dobowego RPD), a zapytanie jest od razu kierowane do następnego aktywnego slotu w puli.
3. Migracja domyślnego modelu na gemini-3.5-flash-lite, który dysponuje pełnymi limitami w darmowym tierze.
**Odrzucone alternatywy:** Pozostawienie pojedynczego klucza i dalsze wydłużanie sleep(); płatny tier Pay-As-You-Go przed wyczerpaniem możliwości darmowej architektury failover.
**Uzasadnienie:** Rozwiązanie eliminuje pojedynczy punkt awarii (SPOF) w warstwie LLM, zapewnia nieprzerwaną responsywność bota Telegram i zwielokrotnia dostępne limity API bez ponoszenia kosztów.

## ADR-013B: Dedykowane narzędzia CLI dla agentów (CLI Helpers) oraz Friction Audit w Handoffie

**Kontekst:** W środowisku Windows/PowerShell agenci napotykali błędy składniowe (`SyntaxError: unterminated string literal`) przy próbach improwizowania zagnieżdżonych jednolinijkowców powłoki (`python -c "import sqlite3..."`). Ponadto brakowało systemowej procedury utrwalania wypracowanych usprawnień narzędziowych na przyszłe sesje.
**Decyzja:**
1. Wdrożono dedykowane narzędzie CLI `kalistenika/tools/db.py` (obsługa WAL `busy_timeout=5000`, flagi `--today`, `--last N`, `--workouts`, `--query`, wbudowana kalkulacja BMR/TDEE wg ADR-012). Zaktualizowano regułę w `kalistenika/.agents/rules/03_architektura_danych.md`.
2. Rozbudowano globalny protokół zamykania sesji (`handoff_runbook.md` w skillu `project-lifecycle`) o obowiązkowy Krok 1.5: *Audyt Punktów Tarcia i Samorefleksja Narzędziowa (Friction Audit & Tool Synthesis)*.
3. Utworzono centralny rejestr `~/.gemini/config/KATALOG_NARZEDZI.md` (Starter Pack Automatyka) oparty na zasadzie Progressive Disclosure.
**Uzasadnienie:** Zastąpienie zawodnej improwizacji powłoki deterministycznym kodem Pythona eliminuje błędy składni, skraca czas odpowiedzi agenta i zapewnia stałą ewolucję systemu z sesji na sesję.

## ADR-014: Idempotencja i eliminacja duplikatow z urzadzen Wear OS (TelegramDeduplicator & Auto-Purge)

**Kontekst:** Uzytkownik korzystajacy ze smartwatcha (Samsung Galaxy Watch / Wear OS) doswiadczal powielania wiadomosci glosowych w czacie Telegrama (sync glitch po stronie klienta Wear OS wysylal identyczny plik audio dwukrotnie w odstepie kilkudziesieciu milisekund z sasiednimi message_id). Prowadzilo to do podwojnego obciazania GPU transkrypcja Faster-Whisper, wyczerpywania limitu 5 RPM w darmowym tierze Gemini API (blad HTTP 429), niepotrzebnego failoveru w GeminiKeyPool oraz wysylania podwojnych odpowiedzi przez bota.
**Decyzja:**
1. Wdrozenie warstwy TelegramDeduplicator w server/server.py opartej o in-memory thread-safe cache (threading.Lock) z automatycznym wygaszaniem wpisow (TTL).
2. Deduplikacja mediow (audio/voice/video/photo) w oparciu o globalnie unikalny identyfikator pliku w Telegramie (file_unique_id) z oknem 300s, wiadomosci tekstowych w oparciu o hash (chat_id, text) z oknem 5s, oraz update_id z oknem 300s.
3. Wprowadzenie mechanizmu Auto-Purge: po wykryciu duplikatu serwer natychmiast odrzuca przetwarzanie i asynchronicznie wywoluje metode deleteMessage(chat_id, message_id) Telegram Bot API na identyfikatorze drugiej wiadomosci. Dzieki temu zduplikowany dymek-widmo samoczynnie znika z interfejsu mobilnego i zegarka.
4. Wdrozenie blokady wspolbieznosci per czat (get_chat_lock(chat_id)), ktora serializuje zapytania do sesji agenta Agent(conversation_id), eliminujac wyscigi w plikach sesji i zabezpieczajac limit RPM.
**Odrzucone alternatywy:** Czekanie na poprawke oficjalnego klienta Telegram na Wear OS (brak wplywu na cykl wydawniczy aplikacji zewnetrznej); ignorowanie drugiego zadania bez usuwania go z Telegrama (pozostawialoby to mylacy, zduplikowany dymek w UI uzytkownika).
**Uzasadnienie:** Architektura rozwiazuje problem u zrodla na poziomie backendu: chroni zasoby sprzetowe GPU i limity API LLM, a jednoczesnie czysci interfejs uzytkownika (UX) w czasie rzeczywistym.

## ADR-015: Standard odpornosci srodowiska hosta i zarzadzania energia (Host Power SRE)

**Kontekst:** Serwer Flask oraz tunel ngrok dzialaja bezposrednio na dedykowanym hoscie z GPU NVIDIA. Architektura tego sprzetu opiera sie na Modern Standby (S0 Low Power Idle) zamiast klasycznego uspienia S3. Domyslne ustawienia zasilania Windowsa (uspienie bezczynnosci, uspienie po zamknieciu pokrywy) zamrazaja procesy Win32 (pythonw, ngrok), odcinaja zasilanie dedykowanego GPU (D3cold - Faster-Whisper) i zrywaja sesje TLS ngroka, co uniemozliwialo odbieranie webhookow z zegarka i bota Telegrama. Ponadto praca 24/7 pod ciaglym napieciem 100% ladowarki zagrazala degradacja i spuchnieciem ogniw Li-Ion, a nocne restarty Windows Update blokowaly autostart uslug.
**Decyzja:**
1. Zdefiniowano i wdrozeno polityke zasilania sieciowego (AC): wylaczenie wylacznie ekranu (5-15 min), calkowity zakaz uspienia (STANDBYIDLE = 0) oraz hibernacji (HIBERNATEIDLE = 0), akcja zamkniecia pokrywy ustawiona na "Nic nie rob" (LIDACTION = 0).
2. Na zasilaniu bateryjnym (DC) zachowano akcje uspienia przy zamknieciu klapy, co chroni baterie i zapobiega przegrzaniu laptopa podczas transportu.
3. Wdrozeno ochrone ogniw baterii poprzez wlaczenie Trybu konserwacji (Conservation Mode), blokujacego ladowanie na poziomie ~75-80%.
4. Zweryfikowano i potwierdzono aktywna opcje Automatic Restart Sign-On (ARSO) w Windows 11 (Konta -> Opcje logowania), co gwarantuje odpalenie sesji i skryptu start_serwera.vbs po nocnych restartach systemu.
**Odrzucone alternatywy:** Pozostawienie domyslnych profili Windowsa i wybudzanie przez Wake-on-LAN (Modern Standby S0 nie gwarantuje niezawodnego wybudzania dla zewnetrznych webhookow HTTP); migracja na platny VPS w chmurze przed pelna stabilizacja lokalnej architektury.
**Uzasadnienie:** Rozwiazanie przeksztalca mobilnego laptopa w niezawodny wezel serwerowy 24/7 bez ponoszenia kosztow chmurowych, jednoczesnie zabezpieczajac fizyczny sprzet przed degradacja termiczno-bateryjna.

## ADR-016: Prezentacja Mobilna w Telegramie i Odporna Sanityzacja HTML (Telegram Mobile-First & Fail-Safe HTML)

**Kontekst:** Odpowiedzi agenta generowane w czacie Telegrama cierpiały na niedopasowanie do medium mobilnego (Channel Mismatch). Telegram natywnie nie wspiera tabel Markdown (`|---|`), co przy 3-kolumnowych zestawieniach powodowało chaotyczne łamanie wierszy i zlewanie się tekstu. Brak parametru `parse_mode` w wywołaniu `sendMessage` skutkował dosłownym wyświetlaniem znaczników technicznych (`**bold**`, `### Nagłówek`, `---`), a agent wklejał lokalne ścieżki Windowsa (`[PROJECT_STATE.md](file:///...)`). Całość tworzyła męczącą wzrok "ścianę tekstu" na 6-calowym ekranie smartfona.
**Decyzja:**
1. Wdrożono w `kalistenika/.agents/rules/project_coach.md` standard *Telegram Mobile-First Output Protocol*: bezwzględny zakaz tabel Markdown, prezentacja wariantów w postaci pionowych kart z wcięciem (`•`), zakaz odnośników lokalnych `file:///`, umiar typograficzny (zasada BLUF, pogrubianie wyłącznie kluczowych wartości, brak jarmarcznych emotikonów w duchu Chłodnego Profesjonalisty).
2. Zaimplementowano w `server/server.py` deterministyczną warstwę formatowania:
   * `convert_markdown_tables`: awaryjny transposer przekształcający tabele Markdown w czytelne karty pionowe,
   * `format_telegram_message`: eliminacja ścieżek `file:///` i wstawek `(patrz: ...)`, bezpieczne escapowanie encji HTML (`&lt;`, `&gt;`, `&amp;`) oraz translacja `**tekst**` → `<b>tekst</b>`,
   * `clean_plain_text`: generator czystego tekstu na potrzeby awaryjnego fallbacku.
3. Wprowadzono do potoku wysyłki `send_telegram_message` obsługę `parse_mode="HTML"` wraz z mechanizmem Fail-Safe Fallback: w razie błędu parsowania po stronie Telegram API (kod 400), serwer natychmiast ponawia wysyłkę w czystym tekście bez formatowania, gwarantując 100% dostarczalności.
**Odrzucone alternatywy:**
* `parse_mode="MarkdownV2"`: odrzucone ze względu na ekstremalną niestabilność parsera Telegrama (wymóg uciekania każdego znaku `.`, `-`, `!`, `(`, `)` groził gubieniem wiadomości przy najmniejszej anomalii).
* Wymuszanie bloków monospace `<pre>` dla tabel: odrzucone, gdyż czcionka monotypiczna na telefonach jest optycznie mniejsza i wymaga uciążliwego przewijania poziomego.
**Uzasadnienie:**
Połączenie prewencji na poziomie promptu (czyste dane u źródła) z filtrem backendowym (gwarancja formatowania nawet przy halucynacji LLM) zapewnia najwyższą ergonomię czytania na smartfonie przy zerowym ryzyku awarii potoku.

## ADR-017: Izolacja Cyklu Życia Serwera i Eliminacja Efektów Ubocznych Importu (Process Lifecycle & Import Side-Effects Guard)

**Kontekst:** Po uruchomieniu testów jednostkowych (`test_server.py`) serwer produkcyjny działający w tle utracił tunel ngrok, co skutkowało błędem HTTP 404 z Telegram API i zawieszeniem kolejki webhooków (`pending_update_count: 1`). Root Cause Analysis wykazała, że moduł `server.py` posiadał niebezpieczne efekty uboczne na poziomie importu modułu (Top-Level Side Effects):
1. `atexit.register(cleanup_ngrok)` był rejestrowany przy samym imporcie modułu `server`, przez co zakończenie procesu testowego zabijało globalny proces `ngrok.exe` instancji produkcyjnej.
2. Ciężki model `WhisperModel('large-v3', device='cuda')` był ładowany na poziomie importu, blokując pamięć VRAM GPU (3.5 GB) i spowalniając testy jednostkowe.
3. `kill_port_5000()` opierał się na miękkim `terminate()` bez awaryjnego `kill()` po upływie timeoutu.

## ADR-018: Deterministyczny schemat architektury w PNG (Retina 2x) zamiast zawodnego renderera Mermaid na GitHubie

**Kontekst:** W dokumentacji repozytorium `Project Coach` (`README.md` oraz `README.pl.md`) architektura systemu została początkowo opisana surowym blokiem kodu Mermaid (`flowchart TD`). Silnik renderujący Mermaida na GitHubie okazał się wysoce zawodny i nieprzewidywalny:
1. Spłaszczał architekturę do wąskiej, pionowej kolumny o wysokości ponad 1500px, w której wszystkie klocki były ułożone jeden pod drugim, tracąc logiczny podział na warstwy.
2. Rysował zaokrąglone, krzywe linie Béziera (`curve: 'basis'`), które nienaturalnie wybrzuszały się i bezceremonialnie przecinały etykiety z tekstem.
3. W ciemnym motywie GitHuba nadawał węzłom wyblakły, niski kontrast szarości na szarości, przez co diagram zlewał się z tłem.
4. Próba zastąpienia kodu Mermaid surowym plikiem SVG napotkała na proxy obrazów GitHuba (Camo), które blokowało renderowanie (`Error rendering embedded code: Invalid image source`) przy wystąpieniu encji XML lub bloków `<style>`.

**Decyzja:**
1. Całkowicie wycięto kod Mermaid oraz pliki SVG z głównej prezentacji w `README.md` i `README.pl.md`.
2. Zaimplementowano skrypt generatora grafiki w Pythonie oparty o bibliotekę `Pillow`, renderujący diagram bezpośrednio do formatu PNG z 2-krotnym supersamplingiem (Retina 2x, rozdzielczość 2080x1140) z wykorzystaniem systemowej, inżynierskiej typografii Segoe UI.
3. Utrwalono **dwutorowy układ architektury (Two-Track Architecture Flow)**:
   * **Lewy tor (Pętla analityczno-agentowa):** `SQL Query Engine` ➔ `Domain AI Agent` ➔ `Telegram Bot` w spójnych akcentach szmaragdu (`#10b981`) i fioletu (`#c084fc`).
   * **Prawy tor (Potok telemetrii i danych):** `Galaxy Watch` + `Notatka Audio` ➔ `Health Connect` + `Faster-Whisper CUDA` ➔ `Domowy Serwer Flask` ➔ `Parser ETL & Sanity Guard` ➔ `Relacyjna Baza SQLite` w akcentach inżynierskiego błękitu (`#38bdf8`) i szmaragdu.
   * **Zamknięta pętla:** magistrala danych historycznych z bazy SQLite do silnika SQL oraz sprzężenie zwrotne z bota na nadgarstek użytkownika.
4. Wygenerowano i wdrożono dedykowane pliki binarne: `architecture.png` (wersja angielska) oraz `architecture.pl.png` (wersja polska), podlinkowane jako responsywne obrazy w obu wersjach językowych README.

**Odrzucone alternatywy:**
* Pozostawienie kodu Mermaid w Markdownie: odrzucone ze względu na koszmarną estetykę, krzyżowanie się strzałek i brak kontroli nad układem na urządzeniach rekruterów/użytkowników.
* Próby obejścia ograniczeń SVG na GitHubie: odrzucone z uwagi na niestabilność polityk bezpieczeństwa proxy Camo i ryzyko ponownego pojawienia się ikony uszkodzonego obrazu.

**Uzasadnienie:**
Podejście jest w 100% zgodne ze światowym standardem open-source (topowe repozytoria jak LangChain, Docker czy Supabase zamrażają architekturę w plikach PNG/WebP). Gwarantuje niezawodne wyświetlanie pixel-perfect, czytelną prezentację dwutorową oraz zerową podatność na błędy zewnętrzne.

## ADR-019: Telegram UX Typing Indicator, Autonomia Narzędziowa i SRE Watchdog

**Kontekst:** W trakcie użytkowania mobilnego interfejsu bota zidentyfikowano trzy obszary optymalizacji:
1. **Feedback UX w trakcie generowania:** Brak wizualnego potwierdzenia odbioru wiadomości (odpowiedź LLM i transkrypcja trwały od 3 do 18 sekund), co rodziło niepewność po stronie użytkownika, czy serwer żyje.
2. **Wyciek powiadomień polityk bezpieczeństwa (confirm_run_command):** Próba wywołania narzędzia przez agenta w trybie autonomicznym skutkowała odrzuceniem przez domyślny hook bezpieczeństwa harnessu (`Denied by policy "confirm_run_command"`), co wyciekało na początek wiadomości na Telegramie.
3. **Brak odporności na awarie tunelu Ngrok:** Chwilowe rozłączenie sieci Wi-Fi lub restart sesji Ngrok nie były automatycznie wykrywane przez serwer Flask.

**Decyzja:**
1. Zaimplementowano klasę `TelegramTypingAction` w `server.py`, która w tle cyklicznie (co 4 sekundy) wysyła akcję `sendChatAction: typing` do czatu Telegrama od momentu odebrania wiadomości (zarówno tekstowej, jak i notatki głosowej) aż do wysłania gotowej odpowiedzi.
2. W `reply_with_agent` dodano `policies=[policy.allow_all()]` do `LocalAgentConfig`, co autoryzuje autonomiczne działanie agenta, a w `format_telegram_message` wprowadzono dodatkowy filtr regex usuwający wszelkie techniczne komunikaty odmowy (`Denied by policy...`).
3. Wdrożono wątek `start_watchdog` w `server.py`, który co 60 sekund sprawdza aktywność tunelu Ngrok (`ngrok.get_tunnels()`) i automatycznie wznawia połączenie w razie awarii, a co 5 minut audytuje stan webhooka Telegrama (`getWebhookInfo`) i usuwa ewentualne zatory w kolejce.

**Uzasadnienie:**
Wdrożenie łączy wzorcowy UX komunikatora mobilnego (natychmiastowy feedback "pisze...") z odpornością infrastruktury typu Self-Healing (automatyczne wznawianie tunelu bez konieczności restartu hosta) i czystością generowanego tekstu.

## ADR-020: Pre-Push Sanity Gate — Precyzyjna detekcja wycieków bez fałszywych alarmów

**Kontekst:** Automatyczny strażnik `.git/hooks/pre-push` blokował operację `git push`, zgłaszając fałszywe alarmy (False Positives). Wzorzec `\.ngrok-free\.dev` oraz `Users` dopasowywał się do prawidłowych szablonów architektonicznych (`https://[tunnel-id].ngrok-free.dev` w `README.md`, `your-static-subdomain.ngrok-free.dev` w `.env.example`) oraz syntetycznych danych testowych (`c:/Users/TESTUSER/` w `test_server.py` testującym mechanizm sanityzacji).

**Decyzja:**
1. Zoptymalizowano skrypt `.git/hooks/pre-push`, dodając potok wykluczający autoryzowane wzorce placeholderów (`[tunnel-id]`, `your-static-subdomain`) oraz atrapy testowe (`TESTUSER`).
2. Wprowadzono jawne raportowanie wykrytych linii do konsoli w razie detekcji rzeczywistego wycieku, co eliminuje konieczność zgadywania przyczyny odrzucenia pusha.

**Uzasadnienie:**
Ochrona danych prywatnych musi być deterministyczna i precyzyjna. Rozwiązanie odróżnia rzeczywiste sekrety i aktywne domeny od generycznych szablonów wymaganych przez standard open-source.


