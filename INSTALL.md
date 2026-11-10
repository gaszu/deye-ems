# Instalacja Deye EMS

Wymagany Home Assistant **2026.11.0 lub nowszy**. W tej wersji używane są aktualne interfejsy config flow, panelu i walidacji HA. Silnik nie pobiera pakietów spoza HA.

## Marketplace — zalecana instalacja

1. W HA otwórz **Ustawienia → Marketplace → Dodaj z linku**.
2. Wpisz `https://github.com/gaszu/ha-deye-ems` i wybierz typ **Integracja**.
3. Dodaj repozytorium, otwórz Deye EMS i wybierz **Instaluj**.
4. Jeśli HA poprosi o restart, wykonaj go. Następnie dodaj Deye EMS w **Ustawienia → Urządzenia i usługi → Dodaj integrację**.

Jest to instalacja z własnego repozytorium Marketplace. Projekt nie jest jeszcze pozycją domyślnego katalogu. Publiczne repozytorium zawiera kod, dokumentację i dane syntetyczne, bez danych dostępu i historii domu.

## Instalacja ręczna z ZIP

1. Pobierz ZIP z katalogu `dist` repozytorium.
2. Rozpakuj go. Skopiuj cały katalog `custom_components/deye_ems` do katalogu konfiguracji HA, zwykle `/config/custom_components/deye_ems`.
3. Uruchom ponownie Home Assistant, aby wykrył nową integrację.
4. Otwórz **Ustawienia → Urządzenia i usługi → Dodaj integrację → Deye EMS**.
5. Ustaw minimalny bezpieczny SoC, pojemność magazynu, moc PV w kWp, moc falownika łącznie i na fazę oraz osobne limity poboru. Wartości początkowe to 40%, 66 kWh oraz 12 kW łącznie i 5 kW na fazę; dopasuj je do własnej instalacji.
6. Integracja zaczyna w trybie **shadow / obserwacja**. Panel Deye EMS pojawi się w menu bocznym administratora.
7. W **Konfiguruj → Encje pomiarowe i sterujące** sprawdź przypisania. Domyślne identyfikatory to przykład dla ESPHome Deye/YamBMS i można je zastąpić własnymi.
8. W **Dodatkowe zużycia** dodaj odpowiednie liczniki pompy ciepła, CWU, klimatyzacji itd.
9. Porównaj pomiary i cele z działającym EMS. Przejście produkcyjne opisano w [MIGRATION.md](MIGRATION.md).

## Połączenie z Solcast

1. W [Solcast Toolkit](https://toolkit.solcast.com.au/) załóż konto i skonfiguruj instalacje: moc AC/DC, azymut, nachylenie i sprawność. Skopiuj klucz API i identyfikatory `rooftop_resource_id` z ich szczegółów.
2. W HA otwórz **Deye EMS → Konfiguruj → Solcast — połączenie i ustawienia → Połącz / zmień ustawienia**. Moduł jest już częścią EMS; nie wymaga osobnej instalacji Solcast.
3. Wpisz klucz i identyfikatory oddzielone przecinkami. Puste identyfikatory uruchamiają próbę wykrywania konta; jeżeli API jej nie obsługuje, wpisz identyfikatory ręcznie.
4. Dopasuj częstotliwość i limit konta. Dwie instalacje i pobieranie co 6 h zużywają zwykle 8 zapytań na dobę; wykrywanie lub nieudane próby też mogą zużyć zapytanie. Standardowy plan Hobbyist pozwala na 10 na dobę UTC. Nie ustawiaj wyższego limitu bez odpowiedniego planu Solcast.
5. Wpisz rzeczywistą liczbę zapytań już wykorzystanych tego dnia na tym koncie. Gdy jej nie znasz, pozostaw 10 i poczekaj na nową dobę. Wpisane zużycie nie zmniejsza istniejącego rejestru; po zmianie konfiguracji może go podnieść.
6. Zostaw mnożnik 1 i puste korekty godzinowe, jeśli nie wymagają zmiany. Prognoza Solcast jest już obliczona dla mocy zapisanej w portalu; w EMS pozostaw tryb **prognoza całej instalacji, bez skalowania**.
7. Alternatywnie wybierz **Importuj dostępne ustawienia z HA**. Klucz, limit konta, wykluczenia i bieżące 24/48 współczynników zostaną skopiowane lokalnie. Sensor korekt jest wyszukiwany w rejestrze wybranej integracji, bez zależności od jego polskiej nazwy. Import zachowuje stan korekt, bez całej historii i algorytmu dalszego samouczenia; kreator poda zakres i poprosi o potwierdzenie. Brak kompletnych korekt zatrzymuje import zamiast zgadywać wartości.
8. Podczas przełączania źródła zatrzymaj odpytywanie poprzedniego klienta Solcast. Sprawdź datę prognozy i stan API w panelu EMS. Zmiany źródła wykonuje się w obserwacji; produkcyjne przejęcie wymaga kompletnej konfiguracji.

## Wymagane pomiary

SoC i napięcie tego samego BMS; prąd dopuszczony i blokada BMS; suma i trzy fazy Grid/LOAD; rzeczywista moc baterii; odczyt limitu prądu ładowania. Dynamiczne pomiary mocy muszą być świeże i mieć poprawne jednostki.

Integracja używa standardowego Recorder HA do profilu historycznego LOAD i liczników energii. LOAD zawiera cały dom, w tym pompę ciepła. Zalecana jest co najmniej tygodniowa historia, z minimum trzema porównywalnymi obserwacjami każdej godziny. Brak historii daje jawny fallback.

Prognozy PV są opcjonalnymi danymi planowania; obsługiwany jest format `detailedForecast` z `period_start`, `pv_estimate10`, `pv_estimate`. Cache jest przypisany do konkretnych dat i przedziałów. Brak kompletnych danych nie jest zastępowany fikcyjną produkcją zero.

## HACS / Marketplace

Repozytorium zawiera strukturę `custom_components` i `hacs.json`. Marketplace i HACS wymagają publicznego repozytorium dla instalacji i aktualizacji tą drogą. Prywatny projekt można nadal instalować ręcznie z ZIP. Integracja EMS nie potrzebuje tokenu GitHub do działania.

## Aktualizacje i usunięcie

Aktualizacja: podmień wyłącznie katalog integracji i uruchom HA ponownie. Nie usuwaj jej konfiguracji ani magazynu runtime, jeżeli chcesz zachować ustawienia i cache.

Przed usunięciem wybierz obserwację. Gdy integracja nadal ma wyłączną kontrolę, świadome przejście z active do shadow próbuje wyłączyć Grid Charge i ustawić prąd sieciowy 0 A; trzeba sprawdzić odczyty urządzenia. Wyładowanie samego kodu nie wysyła poleceń sprzętowych. Ostatnie ustawienia falownika mogą pozostać zapisane, więc jego stan należy zweryfikować.

