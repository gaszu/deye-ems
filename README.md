# Deye EMS

Samodzielna, instalowalna integracja dla Home Assistant z własnym lokalnym silnikiem planowania i prostym panelem. **Bez EMHASS, pomocniczych helperów i automatyzacji EMS.**

Pierwsza wersja zachowuje mechanizmy obecnego EMS: harmonogram G13, sezonowe cele SoC, prognozy PV P10/P50 z datowanym cache, profil domu z dodatkowymi odbiornikami, kontrolę Deye/YamBMS i pomiary energii w slotach. Nie wymaga usługi AI, kontenera ani zewnętrznego solvera.

## Instalacja

[Instrukcja instalacji](INSTALL.md) · [Przejście z obecnego EMS i powrót](MIGRATION.md)

Pakiet: [deye-ems-0.1.0.zip](dist/deye-ems-0.1.0.zip). Po skopiowaniu katalogu integracji i restarcie HA: **Ustawienia → Urządzenia i usługi → Dodaj integrację → Deye EMS**. Panel **Deye EMS** pojawia się w menu bocznym. Pierwsze dodanie uruchamia obserwację, bez poleceń do falownika.

## Najważniejsze ustawienia

| Ustawienie | Wartość początkowa |
|---|---:|
| **Minimalny bezpieczny SoC** — stałe dolne ograniczenie | **40%**, regulowane 40–90% |
| Pojemność baterii | 66 kWh |
| Limit łącznego importu domu i ładowania | 12 kW |
| Limit importu na fazę | 5 kW |
| Maksymalny prąd sieciowy baterii | 108 A, dodatkowo BMS i Deye |
| Bufor prognozy ponad rezerwą | 5 p.p. |
| Zimowy cel przy słabym PV | 75%, obniżany przy lepszej prognozie |
| Maksymalny cel doładowania z sieci | 95% |

Stała rezerwa jest osobnym ustawieniem. Cel ładowania zależny od prognozy nigdy nie zastępuje tej rezerwy. Ustawienia zapisuje HA w konfiguracji integracji, a jej własny cache i rejestr prób — zarządzany magazyn HA. Nie należy edytować tych plików ręcznie.

## Działanie

Zimą (X–III) tanie okna to **21–07 i 13–16**, chronione **07–13 i 16–21**. Silnik wylicza zapas na najbliższe chronione okno na podstawie P10 i zapotrzebowania domu, z pogodowym celem nominalnie 75→45%. Priorytetem są zasilanie domu, autokonsumpcja i ograniczanie importu.

Latem (IV–IX) normalna kolejność to **PV → dom → bateria wysoko → eksport nadwyżki**. Tanie okna **22–07 i 13–19** pozwalają na Grid tylko awaryjnie przy przewidywanym deficycie lub braku wiarygodnego planu i cache. Chronione okna to **07–13 i 19–22**. Normalny dolny próg TOU jest rezerwą; nie ogranicza ładowania z PV do niskiego SoC.

Regulator uwzględnia moc domu i faz, napięcie baterii oraz ograniczenia BMS. Zwiększa nastawę stopniowo o maks. 2 A co 30 s; zwykłe zmniejszanie do 5 A co 30 s. Redukcja wymagana przez bezpieczeństwo lub osiągnięcie celu ma pierwszeństwo. Rejestr próby zapisuje się przed poleceniem; opóźniony odczyt nie uruchamia serii zwiększeń. Utrzymywanie aktywnego ładowania podczas bezpiecznej rampy nie powoduje cyklicznego przełączania GC.

Model ograniczania importu zostawia 500 W łącznie i 250 W na fazie. Przy braku potwierdzonego rozkładu fazowego zachowawczo mieści całą dodatkową moc ładowania w zapasie każdej fazy. To ogranicza dostępną moc bardziej niż założenie podziału po ⅓ i będzie jednym z parametrów do późniejszej kalibracji.

## Dodatkowe zużycia

**Konfiguruj → Dodaj dodatkowe zużycie**: nazwa, encja energii (Wh/kWh), opcjonalna encja mocy (W/kW), pole „Zużycie jest już ujęte w LOAD”. Można dodać pompę ciepła, CWU, klimatyzację i następne odbiorniki.

Dla odbiorników już w LOAD silnik rozdziela bazę domu i kanały, a następnie składa prognozę raz. Brak wiarygodnej historii takiego kanału pozostawia całkowity LOAD. Odbiorniki poza LOAD są dodawane osobno; wymagają świeżego pomiaru mocy do bezpiecznego zwiększania ładowania. Brak danych nie jest zerowym zużyciem.

## Panel i diagnostyka

Główny widok pokazuje stan baterii, rezerwę, przepływy, wybrany cel i tryb pracy. Ustawienia techniczne są zwinięte. Plan, żądany limit, odczyt nastawy i pomiar mocy mają oddzielne znaczenie.

Integracja tworzy własne encje sensor, binary_sensor, number, select i button. Są częścią integracji; nie są pomocniczymi helperami. Pełne wiersze prognozy są dostępne dla uwierzytelnionego panelu, bez umieszczania dużego planu w atrybutach sensora.

## Zakres pierwszej wersji

To własny deterministyczny planer z bilansem energii i projekcją 48 h, nie deklaracja globalnego optimum. Niepełne dane uruchamiają jawny zachowawczy fallback, z zachowaniem prawidłowego cache właściwego terminu. Prognoza nie jest pomiarem, a zgodny odczyt nastawy nie potwierdza fizycznego wykonania.

Silnik nie zmienia firmware, Shutdown, osobnego limitu PV ani trybów Solar Sell / Load First / Zero Export To Load. Oczekuje właściwej konfiguracji tych trybów. Jego ograniczanie importu reaguje na dostępne pomiary i nie zastępuje zabezpieczeń elektrycznych falownika i BMS.

Wersja 0.1.0 ma testy offline planera, regulatora, runtime, pomiarów slotów i panelu. Testy runtime zastępują wyłącznie granicę API HA atrapami. Załadowanie w rzeczywistym HA i reakcja falownika wymagają osobnego etapu uruchomienia; samo repozytorium nie oznacza przejęcia produkcji.

## Rozwój

```shell
python -m unittest discover -s tests -q
node tests/test_frontend.cjs
python build_release.py
```

Kod nie zawiera danych dostępu ani bieżącej telemetrii domu. Wszystkie scenariusze testowe są syntetyczne.

