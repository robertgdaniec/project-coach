> **Typ dokumentu:** Materiał referencyjny (koncepcyjny)
> **Rola:** Zbiór propozycji wskaźników KPI (treningowych, kardiologicznych, regeneracyjnych, rekompozycyjnych) do rozważenia przy budowie dashboardów i raportów agentów.
> **Uwaga:** To nie jest dokument operacyjny. Stan systemu → `PROJECT_STATE.md`. Architektura → `docs/architektura.md`.

---

# Menu Wskaźników i Trendów (Do selekcji)

Poniżej znajduje się "burza mózgów" – wszystkie możliwe korelacje i wskaźniki (KPI), które możemy wyciągnąć z bazy SQLite i plików tekstowych. 

**Zadanie dla Ciebie:** Przejrzyj i wyrzuć (lub powiedz mi, żebym wyrzucił) wszystko, co wydaje Ci się "przerostem formy nad treścią". Zostawimy tylko to, co faktycznie pomoże Ci w treningu i rekompozycji.

---

## 1. Wskaźniki Treningowe (Wydajność i Progres)

1. **RPE vs. Objętość (Per Ćwiczenie)**
   * *Formuła:* Średnie RPE dla konkretnego ćwiczenia w korelacji z liczbą serii (np. czy przy 4x8 na dipach RPE maleje z tygodnia na tydzień?). Pokazuje adaptację układu nerwowego.
2. **Całkowita Objętość Tygodniowa (TRIMP / Total Sets)**
   * *Formuła:* Suma serii wykonanych na daną partię (NOGI, PUSH, PULL) w ciągu 7 dni. Zabezpiecza przed przetrenowaniem (śledzimy, by nie przekraczać np. 15-20 serii na partię w tygodniu).
3. **Trend Zakresu Ruchu / Techniki (Jakościowy)**
   * *Formuła:* Agent śledzi słowa kluczowe w notatkach (np. "głębiej", "lepsza kontrola", "ból") dla konkretnych ćwiczeń i robi z tego miesięczny status (np. "W tym miesiącu 4 razy narzekałeś na ból lewego barku przy dipach").
4. **Stosunek Czasu Treningu do Liczby Serii**
   * *Formuła:* Czas z zegarka (min) / Suma serii. Pokazuje gęstość treningu i to, jak długie robisz przerwy (np. czy trening NOGI staje się krótszy przy tej samej objętości).

## 2. Wskaźniki Kardiologiczne (Tętno z Zegarka)

5. **Wskaźnik Czasu w Strefach 4 i 5 (High Intensity Time)**
   * *Formuła:* Suma minut w Strefie 4 (80-90%) i 5 (90-100%) w skali tygodnia. 
   * *Cel:* Jeśli jest tego za dużo, "przepalasz" układ nerwowy. Trener pilnuje, by ten czas mieścił się w limitach.
6. **Korelacja RPE z Tętnem Maksymalnym (HR Max)**
   * *Formuła:* Czy jak zgłaszasz na czacie RPE 9 (bardzo ciężko), to zegarek faktycznie pokazuje HR Max > 165 BPM? Jeśli RPE jest wysokie, a tętno niskie = zmęczenie mięśniowe/CNS. Jeśli RPE wysokie i tętno w kosmosie = zmęczenie kardio.
7. **Baza Tlenowa (Strefy 1 i 2)**
   * *Formuła:* % czasu treningu spędzony w strefach 1-2. Wskaźnik, czy dobrze się rozgrzewasz i czy odpoczywasz między seriami.

## 3. Zmęczenie, Regeneracja i NEAT (Spacery)

8. **Wpływ Kroków (NEAT) na Trening Siłowy**
   * *Formuła:* Liczba kroków z wczoraj + dzisiaj przed treningiem -> zestawiona z dzisiejszym RPE. 
   * *Cel:* Agent ostrzega: "Zrobiłeś wczoraj 15k kroków, ubiegłe 3 razy w takiej sytuacji RPE na przysiadach wywaliło w kosmos, zrób lżejsze siady".
9. **Kompensacja Ruchu (Efekt lenia po treningu)**
   * *Formuła:* Kiedy jest mocny trening (dużo czasu w Strefie 3+4), sprawdzamy czy w ten sam dzień liczba kroków drastycznie *spada* (np. po siadach siedzisz resztę dnia na kanapie).
10. **Globalny Indeks Zmęczenia (GIZ)**
    * *Formuła:* [Średnie RPE z ostatnich 3 dni] * [Suma stref 4+5 z 3 dni] / [Ilość snu/regeneracji]. Gdy wskaźnik przekracza czerwoną linię, Trener zarządza Deload.

## 4. Rekompozycja i Dieta (Połączenie 3 światów)

11. **Rzeczywisty Deficyt Kaloryczny (Zegarek vs Miska)**
    * *Formuła:* Zjedzone kalorie (z `nutrition_log.md`) MINUS Kalorie spalone całkowite (z `metryki_dzienne.kalorie`). Daje nam **prawdziwy** deficyt dnia, a nie teoretyczny z kalkulatora.
12. **Wpływ Węglowodanów na Wydolność**
    * *Formuła:* Dni, w których zjadłeś dużo węgli vs. Średnie Tętno (HR Avg) i Czas w Strefie 4 na treningu. Czy węgle faktycznie obniżają Ci tętno w trakcie ciężkich dipów/siadów?
13. **Zastój Wagi vs. Fluktuacje Objętości**
    * *Formuła:* Jeśli waga stoi przez 7 dni (brak reakcji), Dietetyk odpytuje SQL o Twoje kroki i treningi z ostatnich 7 dni, by sprawdzić, czy czasem nie obciąłeś objętości treningowej nieświadomie (tzw. adaptacja metaboliczna).

---

## JAK Z TYM PRACUJEMY? (Co robią agenci?)
Kiedy wybierzesz np. 3 metryki z tej listy, w programujemy je na sztywno:
1. Agenci dostają gotowe skrypty SQL do ich obliczania.
2. Ty na czacie wpisujesz komendę np. `/raport`, a Trener w 5 sekund generuje tabelkę z odpowiedziami i mówi: *"Patrz Robert, wskaźnik nr 8 leży, za dużo spacerujesz przed siadami"*.
