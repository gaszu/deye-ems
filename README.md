# Deye EMS

Samodzielna integracja Home Assistant z lokalnym silnikiem planowania energii, regulatorem ładowania baterii i panelem administratora. Nie wymaga EMHASS, zewnętrznego solvera, kontenera, usługi AI ani pomocniczych automatyzacji EMS.

Produkt obsługuje sezonowe cele SoC, prognozy PV P10/P50, datowany cache, profile zużycia z Recorder HA, dodatkowe odbiorniki oraz pomiary energii w slotach. Parametry baterii, falownika, limitów importu i przypisania encji dobiera użytkownik do swojej instalacji.

## Instalacja wersji 1.0.8

[![Zainstaluj Deye EMS przez Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=gaszu&repository=ha-deye-ems&category=integration)

1. Otwórz przycisk Marketplace i wskaż swoją instancję HA. W razie potrzeby dodaj repozytorium jako integrację.
2. Zainstaluj **v1.0.8** i wykonaj restart, jeżeli HA go wymaga.
3. [Dodaj integrację Deye EMS](https://my.home-assistant.io/redirect/config_flow_start/?domain=deye_ems) albo [otwórz istniejący wpis](https://my.home-assistant.io/redirect/integration/?domain=deye_ems).

Wymagany Home Assistant **2026.11.0 lub nowszy**. Panel Deye EMS pojawia się w menu bocznym administratora. Nowa konfiguracja rozpoczyna pracę w **shadow / obserwacja**; włączenie sterowania wymaga osobnej czynności i poprawnej konfiguracji.

Alternatywnie pobierz [deye-ems-1.0.8.zip](https://github.com/gaszu/ha-deye-ems/releases/download/v1.0.8/deye-ems-1.0.8.zip). Szczegóły: [INSTALL.md](INSTALL.md), [specyfikacja silnika](SPECIFICATION.md), [zasady przejścia i powrotu](MIGRATION.md), [opis wydania](release-notes/1.0.8.md).

## Konfiguracja

| Ustawienie | Wartość początkowa produktu |
|---|---:|
| Minimalny bezpieczny SoC | 40%, od Battery low SOC +5p.p. do90% |
| Pojemność baterii | 66 kWh |
| Zainstalowana moc PV | Do wpisania, w kWp |
| Moc falownika łącznie / na fazę | 12 kW / 5 kW, osobne pola |
| Limit importu łącznie / na fazę | 12 kW / 5 kW, osobne pola |
| Maksymalny prąd ładowania z sieci | 108 A, dodatkowo ograniczenia BMS i Deye |
| Bufor prognozy ponad rezerwą | 5 p.p. |
| Zimowy cel przy słabym PV | 75% |
| Maksymalny cel doładowania z sieci | 95% |

Są to domyślne ustawienia oprogramowania, a nie odczyty urządzeń ani zalecenia dla każdej instalacji. Przed sterowaniem wpisz właściwe wartości i sprawdź przypisania w **Konfiguruj → Encje pomiarowe i sterujące**. Minimalny SoC pozostaje niezależną rezerwą; zmienny cel ładowania jej nie zastępuje. Konfigurację przechowuje HA, a cache i rejestr prób — zarządzany magazyn HA.

## Solcast w panelu

**Połącz i skonfiguruj Solcast** otwiera natywny kreator options flow HA wewnątrz panelu. Dostępna jest też droga **Integracje → Deye EMS → Konfiguruj → Solcast — połączenie i ustawienia**. Wbudowany klient nie wymaga osobnej integracji Solcast. Można również pozostać przy prognozach odczytywanych z wybranych encji HA.

Otwarcie, anulowanie kreatora i aktualizacja wersji nie przełączają źródła prognozy. Zmiany połączenia wykonuje się w obserwacji. **Zapisz i włącz pobieranie API** zapisuje konfigurację i włącza klienta; kolejne pobrania mogą zużyć limit konta. Po zapisie sprawdź nowy plan i osobno włącz sterowanie. Zamknięcie zakończonego kreatora nie cofa zapisu. Wyłączenie klienta wymaga jawnej akcji; panel pokazuje osobne potwierdzenie.

Konto, instalacje i ich geometrię konfiguruje się w [Solcast Toolkit](https://toolkit.solcast.com.au/). Kreator EMS przyjmuje klucz API, identyfikatory instalacji, odstęp pobierania, limit konta, wykorzystanie bieżącej doby oraz mnożniki korekty. Puste identyfikatory pozwalają spróbować wykrywania; jeśli API go nie obsługuje, wpisz je ręcznie. [Dokumentacja API Solcast](https://docs.solcast.com.au/docs/section/rooftop-sites-hobbyist) opisuje zasady usługi.

Zapisany klucz nie wraca do formularza, panelu statusu, planu, cache ani diagnostyki. Puste pole zachowuje istniejący klucz. Nowy klucz wpisany w formularzu pozostaje w jego nietrwałej pamięci i jest czyszczony po zakończeniu lub zamknięciu.

Import z `solcast_solar` kopiuje dostępne ustawienia i **bieżący snapshot kalibracji**, obejmujący 24/48 współczynników, tabele instalacji i wykluczenia. Nie przenosi historii ani dalszego samouczenia. Import trafia najpierw do prywatnego szkicu; zapis następuje dopiero po zatwierdzeniu formularza. Brak wymaganej kalibracji zatrzymuje import. Import nie wyłącza istniejącego klienta Solcast; użytkownik zarządza jego odpytywaniem osobno.

Korekty importowane do EMS dotyczą wyłącznie surowych odpowiedzi własnego API. Prognozy z encji HA nie są korygowane ponownie. Tryb **prognoza całej instalacji** używa wartości 1:1; moc kWp nie skaluje ich drugi raz. Osobny tryb profilu referencyjnego skaluje przez stosunek mocy zainstalowanej do referencyjnej.

Limit zapytań jest rozliczany dla całego konta według **doby UTC**. Każda instalacja wymaga oddzielnego zapytania; wykrywanie i nieudane próby również mogą zużyć limit. Rejestr próby jest utrwalany przed HTTP. Restart, zapis ustawień i zmiana źródła nie zerują wykorzystania. Początkowe zużycie może podnieść zapisany licznik, nigdy go obniżyć. Przy nieznanym zużyciu pozostaw pełny limit doby; domyślnie jest to 10. Unikaj równoległego odpytywania konta przez kilku klientów.

## Plan i regulacja

Silnik tworzy deterministyczną projekcję bilansu energii na 48 h. Zimą wyznacza cel zależny od PV i prognozowanego zużycia; latem preferuje autokonsumpcję PV i ładowanie z sieci stosuje awaryjnie. Okna sezonowe, warunki fallbacku i szczegóły modelu opisuje [SPECIFICATION.md](SPECIFICATION.md). Cache jest datowany i powiązany z konfiguracją oraz terminem; braki prognozy nie są zastępowane fikcyjną produkcją zero.

Regulator uwzględnia świeżość i jednostki pomiarów, GRID/LOAD łącznie i na fazach, napięcie baterii oraz ograniczenia BMS i falownika. Model rozkładu fazowego zależy od potwierdzonych ustawień urządzenia; brak potwierdzenia wybiera wariant zachowawczy. Limity importu i mocy konwersji są kontrolowane osobno. EMS nie przełącza automatycznie trybów falownika.

W kandydacie1.0.7 zwykłe nastawy prądu są wyliczane bez rampy20A i wysyłane o :00/:30, w pierwszej minucie bloku. Korekta wymaga10A, nastawa jest zaokrąglana do5A w granicach bezpieczeństwa. Bezpieczny start z zera może użyć1–4A. Po osiągnięciu celu ponowny start wymaga spadku SoC o2p.p., a po ograniczeniu wymagane są120s stabilnych obserwacji i dopuszczony termin zapisu. Zwiększenia muszą zmieścić się w aktualnym zapasie GRID oraz limitach LOAD, falownika i BMS. Ochrony i zakończenie ładowania mogą wymagać natychmiastowej redukcji. Restart ani opóźniony odczyt nie kasują przerwy między możliwymi wysłanymi poleceniami. Próba polecenia jest zapisywana przed usługą; przyjęcie usługi, odczyt rejestru i fizyczny przepływ energii są odrębnymi informacjami. Plan nie gwarantuje osiągnięcia SoC ani idealnego zera importu.

## Dodatkowe zużycia

W panelu dostępne są **Dodaj odbiornik / Edytuj / Usuń** oraz przełącznik ON/OFF. Kanał zawiera nazwę, licznik energii Wh/kWh i opcjonalny pomiar mocy W/kW. OFF zachowuje konfigurację i identyfikator. Edycja wymaga obserwacji; powrót do sterowania jest jawny.

Model zakłada, że główny LOAD obejmuje modelowane odbiorniki. Użytkownik musi sprawdzić zakres swojego pomiaru. Kanały służą wyłącznie prognozie SoC: silnik rozdziela profile i składa całkowite zużycie raz. Nie dolicza ponownie mocy kanałów do bieżącego LOAD ani regulatora importu. Brak odpowiedniej historii kanału zachowuje model całkowitego LOAD. ON/OFF nie steruje fizycznym zasilaniem odbiornika.

## Panel, aktualizacje i testy

Panel pokazuje tryb, cele, przepływy, plan i diagnostykę. W ustawieniach zaawansowanych pole **Motyw panelu** pozwala wybrać dowolny zainstalowany motyw HA albo dziedziczyć bieżący motyw profilu. Wygląd jest stosowany lokalnie w EMS, łącznie z tłem i kartami, bez zmiany innych dashboardów. Integracja tworzy własne encje sensor, binary_sensor, number, select i button.

Aktualizacja kodu zachowuje istniejącą konfigurację i źródło prognozy. Nie usuwaj wpisu integracji ani magazynu runtime podczas zwykłej aktualizacji. Włączenie sterowania pozostaje osobną, świadomą czynnością.

Testy są offline; podgląd przeglądarki używa danych syntetycznych. Aktualne wyniki, zakres i ograniczenia opisuje [VALIDATION.md](VALIDATION.md).

```shell
python -m unittest discover -s tests -q
node tests/test_frontend.cjs
python build_release.py
```

## Wersja1.0.7: układ z CT i odbiorami przed falownikiem

Opcjonalna topologia **LOAD + odbiory między GRID a CT** zachowujeZero Export To CT. Odróżnia wymianę z siecią mierzoną naCT od portuGRID falownika. Do zużycia i prognozy dodaje bilansCT−GRID do natywnegoLOAD, bez podwójnego liczenia CWU. Wspólna moc znamionowa dotyczy całego falownika. Konfiguracja wymaga oddzielnych sum i faz obu pomiarów, obserwacji i jawnego wznowienia; pełne wymagania są w[INSTALL.md](INSTALL.md). Brak wdrożenia i potwierdzenia pomiarów sprzętowych.
