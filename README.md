# Deye EMS

Samodzielna, instalowalna integracja dla Home Assistant z własnym lokalnym silnikiem planowania i prostym panelem. **Bez EMHASS, pomocniczych helperów i automatyzacji EMS.**

Pierwsza wersja zachowuje mechanizmy obecnego EMS: harmonogram G13, sezonowe cele SoC, prognozy PV P10/P50 z datowanym cache, profil domu z dodatkowymi odbiornikami, kontrolę Deye/YamBMS i pomiary energii w slotach. Nie wymaga usługi AI, kontenera ani zewnętrznego solvera.

## Instalacja

[![Zainstaluj Deye EMS przez Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=gaszu&repository=ha-deye-ems&category=integration)

1. Kliknij przycisk **Marketplace**, wskaż swoją instancję HA i zaakceptuj dodanie repozytorium, jeśli pojawi się taka propozycja.
2. Wybierz **Instaluj** i wersję **v1.0.3**. Jeśli HA poprosi o restart, wykonaj go.
3. [Dodaj integrację Deye EMS](https://my.home-assistant.io/redirect/config_flow_start/?domain=deye_ems). Jeżeli jest już skonfigurowana, [otwórz istniejącą integrację](https://my.home-assistant.io/redirect/integration/?domain=deye_ems).

W HA znajdziesz ją pod **Ustawienia → Urządzenia i usługi → Integracje → Deye EMS**. Jej panel pojawia się w menu bocznym administratora; po instalacji lub restarcie odśwież stronę. Pierwszy start to obserwacja.

Wymagany HA **2026.11+**. Przycisk otwiera normalną instalację Marketplace i obsługuje także dodanie tego projektu jako własnego repozytorium. Projekt nie jest jeszcze w katalogu domyślnym. [Zasady przycisku i katalogu](https://contributors.home-assistant.io/marketplace/guides/catalog/#the-link-to-your-repository).

[Specyfikacja 1.0.0](SPECIFICATION.md) · [Instrukcja instalacji](INSTALL.md) · [Przejście z obecnego EMS i powrót](MIGRATION.md)

Alternatywna instalacja ręczna: [deye-ems-1.0.3.zip](https://github.com/gaszu/ha-deye-ems/releases/download/v1.0.3/deye-ems-1.0.3.zip).

Wersja **1.0.3** udostępnia listę, dodawanie, edycję, usuwanie i checkboxy ON/OFF odbiorników bezpośrednio w panelu. [Opis zmian](release-notes/1.0.3.md). Specyfikacja silnika pozostaje 1.0.0.

## Najważniejsze ustawienia

| Ustawienie | Wartość początkowa |
|---|---:|
| **Minimalny bezpieczny SoC** — stałe dolne ograniczenie | **40%**, regulowane 40–90% |
| Pojemność baterii | 66 kWh |
| Zainstalowana moc paneli PV | Do wpisania, w kWp |
| Moc falownika łącznie / dopuszczalna na fazę | 12 kW / 5 kW, osobne parametry |
| Limit łącznego importu domu i ładowania | 12 kW |
| Limit importu na fazę | 5 kW |
| Maksymalny prąd sieciowy baterii | 108 A, dodatkowo BMS i Deye |
| Bufor prognozy ponad rezerwą | 5 p.p. |
| Zimowy cel przy słabym PV | 75%, obniżany przy lepszej prognozie |
| Maksymalny cel doładowania z sieci | 95% |

Stała rezerwa jest osobnym ustawieniem. Cel ładowania zależny od prognozy nigdy nie zastępuje tej rezerwy. Ustawienia zapisuje HA w konfiguracji integracji, a jej własny cache i rejestr prób — zarządzany magazyn HA. Nie należy edytować tych plików ręcznie.

## Solcast wewnątrz EMS

**Konfiguruj → Solcast — połączenie i ustawienia** uruchamia wbudowany klient API. Nie trzeba instalować osobnej integracji Solcast. W kreatorze podaje się klucz, identyfikatory instalacji, odstęp pobierania, limit zapytań oraz stały mnożnik i opcjonalne 24 mnożniki godzinowe. Klucz pozostaje w konfiguracji HA; panel, plan, cache i diagnostyka nie ujawniają go.

Konto i instalacje zakłada się w [Solcast Toolkit](https://toolkit.solcast.com.au/). Dla planu Hobbyist moc AC/DC, kierunek i nachylenie paneli oraz sprawność konfiguruje się w tym portalu. Wbudowany moduł pobiera prognozę dla zapisanych tam instalacji; nie zmienia geometrii przez komercyjne API. Zasady opisuje [oficjalna dokumentacja Solcast](https://docs.solcast.com.au/docs/section/rooftop-sites-hobbyist).

Prognoza całej instalacji jest domyślnie używana **1:1**. Pole mocy kWp wiąże prognozę i jej cache z konfiguracją instalacji; nie mnoży ponownie już skalibrowanej prognozy. Osobny tryb profilu referencyjnego oblicza `prognoza / moc referencyjna × moc zainstalowana`. Wybiera się go świadomie dla profilu innej mocy. Brak wpisanej mocy PV blokuje przejęcie sterowania i jest widoczny jako brak konfiguracji.

Import z `solcast_solar` kopiuje lokalnie dostępny klucz, limit konta, wykluczenia i bieżące współczynniki z sensora korekt przypisanego do tej integracji. Obsługuje 24/48 punktów i tabele instalacji; tabela globalna ma pierwszeństwo. Importowane korekty stosuje tylko do surowych odpowiedzi własnego API. Prognozy odczytywane z encji HA są już skorygowane i nie otrzymują ich ponownie. Przeniesiony jest stan współczynników, bez pełnej historii i mechanizmu dalszego samouczenia poprzedniej integracji. Kreator opisuje ten zakres i prosi o jego potwierdzenie. Nie wyłącza poprzedniego źródła samoczynnie.

Standardowy limit Hobbyist to 10 zapytań na dobę UTC dla całego konta. Każda instalacja zużywa oddzielne zapytanie. Rejestr jest zapisywany przed próbą HTTP, obejmuje błędy i pozostaje po restarcie lub zmianie konfiguracji. Wpisane początkowe zużycie nie zmniejsza istniejącego rejestru, a po zmianie konfiguracji może go podnieść; przy nieznanym zużyciu domyślne 10 wstrzymuje zapytania do kolejnej doby UTC. Nie należy równolegle odpytywać tego samego konta przez dwa klienty. Brak jednej instalacji lub części horyzontu nie jest zastępowany zerem. Cache ma datę pobrania i identyfikację źródła.

## Działanie

Zimą (X–III) tanie okna to **21–07 i 13–16**, chronione **07–13 i 16–21**. Silnik wylicza zapas na najbliższe chronione okno na podstawie P10 i zapotrzebowania domu, z pogodowym celem nominalnie 75→45%. Priorytetem są zasilanie domu, autokonsumpcja i ograniczanie importu.

Latem (IV–IX) normalna kolejność to **PV → dom → bateria wysoko → eksport nadwyżki**. Tanie okna **22–07 i 13–19** pozwalają na Grid tylko awaryjnie przy przewidywanym deficycie lub braku wiarygodnego planu i cache. Chronione okna to **07–13 i 19–22**. Normalny dolny próg TOU jest rezerwą; nie ogranicza ładowania z PV do niskiego SoC.

Regulator uwzględnia moc domu i faz, napięcie baterii oraz ograniczenia BMS. Zwiększa nastawę stopniowo o maks. 2 A co 30 s; zwykłe zmniejszanie do 5 A co 30 s. Redukcja wymagana przez bezpieczeństwo lub osiągnięcie celu ma pierwszeństwo. Rejestr próby zapisuje się przed poleceniem; opóźniony odczyt nie uruchamia serii zwiększeń. Utrzymywanie aktywnego ładowania podczas bezpiecznej rampy nie powoduje cyklicznego przełączania GC.

Model ograniczania importu zostawia 500 W łącznie i 250 W na fazie. Przy braku potwierdzonego rozkładu fazowego zachowawczo mieści całą dodatkową moc ładowania w zapasie każdej fazy. To ogranicza dostępną moc bardziej niż założenie podziału po ⅓ i będzie jednym z parametrów do późniejszej kalibracji.

Moc falownika i dopuszczalna moc na fazę są osobnymi polami konfiguracji. Regulator stosuje niższe ograniczenie: mocy falownika albo limitu importu, odpowiednio dla sumy i każdej fazy. Model ładowania i rozładowania również nie przekracza wpisanej łącznej mocy falownika. Zmiana mocy w konfiguracji nie zmienia parametrów sprzętowych urządzenia.

## Dodatkowe zużycia

W panelu **Dodatkowe zużycia** są lista, przyciski **Dodaj odbiornik / Edytuj / Usuń** i checkbox ON/OFF przy każdej pozycji. Podaje się nazwę, licznik energii Wh/kWh oraz opcjonalny pomiar mocy W/kW. Odbiornik wyłączony pozostaje zapisany na liście. Zmiany wykonuje się w obserwacji; po zakończeniu użyj widocznego przycisku powrotu do sterowania.

**Główny LOAD obejmuje wszystkie odbiorniki domu.** Lista służy wyłącznie modelowaniu prognozy SoC. Silnik rozdziela bazę domu i aktywne profile, a następnie składa prognozę raz; nie dolicza ponownie ich mocy do bieżącego LOAD ani regulatora importu. Brak wiarygodnej historii kanału pozostawia całkowity LOAD. Checkbox nie steruje zasilaniem fizycznego urządzenia.

Zakres LOAD zależy od topologii: w **Zero Export To Load** instrukcja opisuje odbiory portu LOAD, a w **Zero Export To CT** ekran LOAD obejmuje backup i home. Samo włączenie CT nie uzasadnia ponownego dodawania odbiorników już ujętych w tym pomiarze. [Instrukcja Deye, s. 33 i 38](https://www.deyeinverter.com/deyeinverter/2026/03/19/BManualSUN-5-12K-SG04LP3-EU20260319en.pdf).

Potwierdzone **Asymmetric phase feeding ON** w obsługiwanym trybie on-grid pozwala uwzględnić wyrównywanie poboru GRID pomimo niesymetrycznego LOAD. Limity importu są kontrolowane osobno od znamionowej mocy wyjściowej falownika. EMS nie zmienia automatycznie trybu LOAD/CT ani ustawienia bilansowania. [Opis producenta, s. 43](https://www.deyeinverter.com/deyeinverter/2026/03/19/BManualSUN-5-12K-SG04LP3-EU20260319en.pdf).

## Panel i diagnostyka

Główny widok pokazuje stan baterii, rezerwę, przepływy, wybrany cel i tryb pracy. Ustawienia techniczne są zwinięte. Plan, żądany limit, odczyt nastawy i pomiar mocy mają oddzielne znaczenie.

Integracja tworzy własne encje sensor, binary_sensor, number, select i button. Są częścią integracji; nie są pomocniczymi helperami. Pełne wiersze prognozy są dostępne dla uwierzytelnionego panelu, bez umieszczania dużego planu w atrybutach sensora.

## Zakres pierwszej wersji

To własny deterministyczny planer z bilansem energii i projekcją 48 h, nie deklaracja globalnego optimum. Niepełne dane uruchamiają jawny zachowawczy fallback, z zachowaniem prawidłowego cache właściwego terminu. Prognoza nie jest pomiarem, a zgodny odczyt nastawy nie potwierdza fizycznego wykonania.

Silnik nie zmienia firmware, Shutdown, osobnego limitu PV ani trybów Solar Sell / Load First / Zero Export To Load. Oczekuje właściwej konfiguracji tych trybów. Jego ograniczanie importu reaguje na dostępne pomiary i nie zastępuje zabezpieczeń elektrycznych falownika i BMS.

Wersja 1.0.0 ma testy offline planera, regulatora, runtime, pomiarów slotów i panelu. Testy runtime zastępują wyłącznie granicę API HA atrapami. Załadowanie w rzeczywistym HA i reakcja falownika wymagają osobnego etapu uruchomienia; samo repozytorium nie oznacza przejęcia produkcji.

## Rozwój

```shell
python -m unittest discover -s tests -q
node tests/test_frontend.cjs
python build_release.py
```

Kod nie zawiera danych dostępu ani bieżącej telemetrii domu. Wszystkie scenariusze testowe są syntetyczne.

