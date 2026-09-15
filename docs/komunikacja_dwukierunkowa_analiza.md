# Analiza Architektoniczna: Dwukierunkowa Komunikacja

## 1. Kontekst i Cel
Celem jest zaprojektowanie mechanizmu pozwalającego agentom (Dietetykowi i Trenerowi z projektu Kalistenika) na proaktywne wysyłanie powiadomień, pytań i podsumowań do użytkownika, który przebywa z dala od PC i operuje wyłącznie z poziomu smartfona/smartwatcha. 

Obecnie przepływ danych jest jednokierunkowy (Zegarek/Tasker -> Ngrok -> Flask -> Pliki lokalne). Nowa architektura musi minimalizować opór interfejsu (frictionless UX), umożliwiać łatwy odczyt i odpowiedź w ruchu, wykorzystując fakt, że domowy serwer działa nieprzerwanie 24/7.

## 2. Przegląd Najlepszych Opcji Technologicznych

Po przeanalizowaniu dostępnych rozwiązań na rynku, wyselekcjonowałem trzy kanały najlepiej pasujące do paradygmatu automatyzacji mobilnej:

### Opcja A: Dedykowany Telegram Bot
**Zasada działania:**
Agenci wykorzystują proste żądania HTTP do API Telegrama, by wysyłać wiadomości bezpośrednio na dedykowany czat. Gdy użytkownik odpowiada lub wysyła notatkę głosową, serwery Telegrama przesyłają żądanie typu Webhook bezpośrednio do naszego serwera Flask (poprzez aktywny tunel Ngrok).
* **Zalety:** Natywny, czatowy interfejs idealny na smartfony i zegarki, trwała historia wiadomości, wbudowana obsługa notatek głosowych, bezpłatny, bardzo szybka integracja.
* **Wady:** Wymaga założenia konta bota (BotFather) i zarządzania tokenem dostępowym.

### Opcja B: Powiadomienia Push przez Join / Tasker (AutoRemote)
**Zasada działania:**
Skoro ekosystem Taskera jest już w użyciu (obsługa notatek z zegarka), agenci mogą uderzać w API usługi Join (joaoapps). Tasker na telefonie odbiera sygnał i renderuje natywne powiadomienie na Androidzie, w tym opcjonalne przyciski szybkiej reakcji.
* **Zalety:** Ogromne możliwości konfiguracji po stronie telefonu (dźwięki, wibracje, integracje sprzętowe), wykorzystanie istniejących już narzędzi (Tasker).
* **Wady:** Komunikacja jest asymetryczna. Powiadomienia to nie konwersacja - znikają po odrzuceniu (brak stałej historii), a odpowiadanie przez pola tekstowe zagnieżdżone w powiadomieniu jest niewygodne (wysokie tarcie UX).

### Opcja C: Kanał Subskrypcyjny ntfy.sh (Serverless Push)
**Zasada działania:**
Wykorzystanie darmowej usługi `ntfy.sh`. Serwer wysyła zwykłe żądanie `POST /temat` z treścią, a aplikacja ntfy na smartfonie budzi się i wyrzuca powiadomienie Push.
* **Zalety:** Skrajnie prosta implementacja (wystarczy `curl`), brak wymogu uwierzytelniania na etapie testów, bardzo lekkie obciążenie.
* **Wady:** Ponownie - to system notyfikacji, nie komunikacji. Ograniczone możliwości wygodnego odpowiadania w ruchu. Wymaga instalacji dodatkowej aplikacji.

## 3. Matryca Porównawcza

| Kryterium | Opcja A: Telegram Bot | Opcja B: Join / Tasker | Opcja C: ntfy.sh |
|:---|:---|:---|:---|
| **Kierunkowość** | Prawdziwie Dwukierunkowa | Jednokierunkowa (z opcją symulacji) | Jednokierunkowa (z opcją symulacji) |
| **UX w Ruchu (Frictionless)** | Wybitny (intuicyjny UI czatu, dyktowanie) | Średni (odpisywanie w Androidowych dymkach) | Dobry (lekkie dymki, ciężko odpowiadać) |
| **Retencja Kontekstu** | Stała (przewijalna historia rozmowy) | Ulotna (znika po odrzuceniu powiadomienia) | Ulotna |
| **Próg Wejścia / Wdrożenie** | Niski (REST API + nowy endpoint Flask) | Średni (wymaga budowy profili Tasker) | Niski (HTTP POST, gotowa apka) |
| **Synergia Architektoniczna** | Bardzo Wysoka (tunel HTTPS Ngrok już gotowy pod Webhooki) | Wysoka (Tasker już jest w obiegu) | Średnia (nowy, niezależny byt) |

## 4. Rekomendacja Głównego Architekta

Biorąc pod uwagę wymogi (frictionless UX, telefon jako główne narzędzie, praca w ruchu) oraz zasady żelaznej inżynierii opierającej się na solidnych fundamentach, **jednoznacznie rekomenduję Opcję A: Telegram Bot**.

**Uzasadnienie z perspektywy Root Cause Analysis:**
Problemem w dwukierunkowej komunikacji na linii Agent-Człowiek nie jest sam przesył danych, lecz **zarządzanie kontekstem kognitywnym użytkownika będącego w ruchu**. 
Systemy typu Push (Tasker, ntfy) traktują komunikaty jak zdarzenia jednorazowe. Jeśli Dietetyk wyśle Ci rozpiskę posiłków na dany dzień, powiadomienie Push zostanie przez przypadek "zdmuchnięte" i utracone z ekranu telefonu. 

Telegram Bot gwarantuje stałą retencję (historia czatu służy jako bieżący raport). Co więcej, w pełni wykorzystuje naszą obecną architekturę:
1. Posiadamy już pracujący serwer Flask z wystawionym tunelem Ngrok. Dodanie Webhooka Telegrama to kwestia dopisania jednej trasy (route'a) w `server.py`, która w przyszłości będzie w stanie przyjmować zarówno tekst, jak i zrzuty notatek głosowych z dyktowania.
2. Bot zastępuje konieczność mozolnego budowania front-endu, oferując natywne doświadczenie na smartfonie bez narzutu deweloperskiego.

Oczekuję na weryfikację i ewentualną zgodę na przygotowanie *Implementation Plan* w oparciu o wybraną opcję.
