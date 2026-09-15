> **Typ dokumentu:** Materiał referencyjny (koncepcyjny)
> **Rola:** Matryca interpretacji danych fizjologicznych dla agentów analitycznych. Definiuje korelacje 1D–4D między danymi ze sprzętu a odczuciami użytkownika.
> **Uwaga:** To nie jest dokument operacyjny. Stan systemu → `PROJECT_STATE.md`. Architektura → `docs/architektura.md`.

---

# SYSTEMOWA MACIERZ DANYCH (DATA MATRIX)

Podejście bottom-up: zaczynamy od dostępnych surowych danych, a następnie je krzyżujemy, aby uzyskać bezcenną wiedzę o Twoim organizmie.

---

## 1. NASZE "ATOMY" DANYCH (Surowe wejścia)

### A. Automatyczne z zegarka (Hardware)
1. `Kroki` (NEAT / Aktywność pozatreningowa)
2. `Kalorie_Calkowite` (TDEE - całkowity wydatek energetyczny)
3. `Czas_w_Strefach_1_3` (Baza tlenowa, regeneracja aktywna)
4. `Czas_w_Strefach_4_5` (Wysiłek beztlenowy, obciążenie CNS)
5. `HRV (RMSSD)` (Zmienność rytmu zatokowego - status układu współczulnego)
6. `Tętno_Spoczynkowe` (Zmierzone rano lub w nocy - marker przemęczenia)

### B. Wprowadzane z czatu (Software / Human)
7. `Waga_Poranna` (Masa ciała)
8. `Spozyte_Makro` (Kalorie zjedzone, Białko, Węgle, Tłuszcze)
9. `Rodzaj_Pokarmu` (Konkretne zjedzone produkty - jakość, gęstość odżywcza)
10. `Objetosc_Treningowa` (Wykonane serie × powtórzenia per ćwiczenie/partia)
11. `Trening_RPE` (Subiektywne obciążenie 1-10)
12. `Odczucia_Jakosciowe` (Ból, jakość snu, pompa mięśniowa - słowa kluczowe)

---

## 2. KORELACJE 2D (Zderzenie dwóch zmiennych)

| Oś X (Zmienna 1) | Oś Y (Zmienna 2) | Co nam to mówi? (Wniosek systemowy) |
| :--- | :--- | :--- |
| `Kroki` | `Trening_RPE (Nogi)` | **Wskaźnik zmęczenia lokalnego:** Czy wysoki NEAT (dużo chodzenia po górach) z wczoraj drastycznie utrudnia dzisiejsze siady? |
| `Spozyte_Wegle` | `Czas_Strefy_4_5` | **Wydajność glikolityczna:** Czy w dni "high-carb" jesteś w stanie spędzić więcej czasu na wysokich obrotach tętna bez spadku mocy? |
| `Objetosc_Treningowa` | `Trening_RPE` | **Wskaźnik adaptacji siłowej:** Robisz 4x8 dipów z RPE 8. Tydzień później robisz 4x8 dipów z RPE 7. Siła układu nerwowego wzrosła. |
| `HRV` | `Tętno_Spoczynkowe` | **Weryfikacja przetrenowania:** Spadek HRV + Wzrost Tętna Spoczynkowego = Twój układ nerwowy prosi o litość. Konieczny deload. |
| `Kalorie_Calkowite` | `Spozyte_Makro` | **Rzeczywisty Bilans Dnia:** Różnica to Twój prawdziwy, matematyczny deficyt lub nadwyżka kaloryczna. |

---

## 3. KORELACJE 3D (Zaawansowane wnioskowanie)

Kiedy zderzamy trzy atomy, otrzymujemy odpowiedzi na skomplikowane pytania.

### A. ROZWIĄZANIE TWOJEGO PROBLEMU: Weryfikacja Rekompozycji (Przyrost Mięśni)
* **Zmienne:** `Waga` + `Rzeczywisty Bilans` + `(Objetosc_Treningowa vs RPE)`
* **System analizuje:** Waga stoi w miejscu od 2 tygodni. Ale kalkulator pokazuje, że jesteś w łącznym deficycie -2000 kcal za ten czas. Z kolei na treningu zwiększyłeś powtórzenia w podciąganiu przy zachowaniu tego samego RPE.
* **Wniosek Agenta:** *"Robert, waga stoi, bo jednocześnie utleniłeś tłuszcz (deficyt) i nadbudowałeś tkankę mięśniową (progresja siłowa/objętościowa). Rekompozycja przebiega modelowo, nie tniemy kalorii."*

### B. Weryfikacja "Złego Dnia" (Jakość Paliwa vs CNS)
* **Zmienne:** `Spozyte_Makro (Węgle)` + `HRV` + `Trening_RPE`
* **System analizuje:** RPE wywaliło w kosmos, zgłaszasz na czacie brak siły.
* **Wniosek Agenta:** *"Sprawdziłem dane. Twoje węgle od 3 dni są w normie, ale HRV zanurkowało, a strefy 4_5 z całego tygodnia są bardzo wysokie. Twój spadek siły to nie kwestia diety i braku glikogenu, to klasyczne przeciążenie centralnego układu nerwowego (CNS). Jutro śpisz godzinę dłużej i robisz pełen rest."*

---

## 4. KORELACJE 4D (Holistyczny Model Sportowca)

* **Zmienne:** `Kroki_Tygodniowe` + `Czas_Strefy_1_3` + `Czas_Strefy_4_5` + `Waga`
* **Jak system to interpretuje (Tzw. Oszczędzanie Energii):** 
Będąc długo w deficycie, organizm podświadomie zwalnia. System widzi: deficyt jest utrzymany, waga zaczyna zwalniać z redukcją. Agent patrzy na Strefy 1_3 i kroki, by zauważyć: *"Robert, celowo nie docinasz diety głębiej, bo widzę z zegarka, że Twój czas w Strefach 1-3 z treningów i dzienne kroki spadły o 20% względem zeszłego miesiąca. Twój NEAT i aktywność spontaniczna siadły (organizm oszczędza energię). Zamiast ucinać jedzenie, świadomie dołóż 2000 kroków dziennie, by podbić wydatkowanie."*

---

### PODSUMOWANIE PODEJŚCIA SYSTEMOWEGO
Zamiast "wymyślać dashboardy", każemy agentom liczyć korelacje z tej macierzy. Twarde dane z zegarka zawsze weryfikują Twoje subiektywne odczucia z czatu (i na odwrót). Czasem czujesz się fatalnie (wysokie RPE), a HRV jest super – to znak, by ignorować odczucia i cisnąć. Czasem czujesz się świetnie, ale zegarek krzyczy (niskie HRV) – to znak, by uważać na kontuzję, bo pracujesz na adrenalinie.
