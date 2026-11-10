# Instalacja i obsługa Deye EMS 1.0.5

Wymagany Home Assistant **2026.11.0 lub nowszy**. Integracja działa lokalnie i nie wymaga EMHASS ani zewnętrznego solvera. Użytkownik wybiera źródła danych i parametry właściwe dla swojej instalacji.

## Marketplace

[![Zainstaluj Deye EMS przez Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=gaszu&repository=ha-deye-ems&category=integration)

1. Kliknij przycisk i wskaż instancję HA.
2. Jeżeli repozytorium nie jest jeszcze dodane, zaakceptuj dodanie go jako **Integracja**.
3. Zainstaluj **v1.0.5**. Wykonaj restart, jeżeli HA go wymaga.
4. [Dodaj Deye EMS](https://my.home-assistant.io/redirect/config_flow_start/?domain=deye_ems) przez **Ustawienia → Urządzenia i usługi → Dodaj integrację**.

Alternatywnie w Marketplace użyj **Dodaj z linku** i adresu `https://github.com/gaszu/ha-deye-ems`. Jeżeli integracja ma już wpis, [otwórz istniejącą konfigurację](https://my.home-assistant.io/redirect/integration/?domain=deye_ems); nie dodawaj drugiego wpisu. Po instalacji odśwież przeglądarkę. Panel administratora pojawia się w menu bocznym.

## Instalacja z ZIP

1. Pobierz [deye-ems-1.0.5.zip](https://github.com/gaszu/ha-deye-ems/releases/download/v1.0.5/deye-ems-1.0.5.zip).
2. Rozpakuj i skopiuj cały katalog `custom_components/deye_ems` do `/config/custom_components/deye_ems` swojej instancji.
3. Uruchom HA ponownie i dodaj integrację.

## Pierwsza konfiguracja

1. Wpisz minimalny bezpieczny SoC, pojemność baterii, moc PV, moc falownika łącznie i na fazę oraz osobne limity importu. Domyślne wartości produktu to m.in. 40%, 66 kWh, 12 kW łącznie i 5 kW na fazę; wymagają dopasowania do urządzeń.
2. Pozostań w **shadow / obserwacja**. W tym trybie integracja pokazuje obliczenia bez sterowania wyjściami.
3. W **Konfiguruj → Encje pomiarowe i sterujące** sprawdź lub zastąp przykładowe przypisania. Każde wyjście musi wskazywać właściwą, istniejącą encję, a wyjścia muszą mieć unikalne przypisania.
4. Skonfiguruj źródło prognozy PV i ewentualne dodatkowe profile zużycia.
5. Sprawdź pomiary, ich jednostki, daty prognozy, wybrany cel i warunki konfiguracji. Dopiero potem osobno wybierz sterowanie. Zasady przejścia i powrotu opisuje [MIGRATION.md](MIGRATION.md).

Wymagane pomiary obejmują SoC i napięcie tego samego BMS, dopuszczony prąd i blokadę BMS, GRID/LOAD łącznie i na trzech fazach, moc baterii oraz odczyt nastawy prądu ładowania. Sterowanie wymaga zgodnych ustawień trybów falownika i mapowań TOU. Szczegółowe warunki opisuje [SPECIFICATION.md](SPECIFICATION.md). Integracja nie ustawia automatycznie wszystkich trybów sprzętowych.

Recorder HA dostarcza historię LOAD i liczników energii. Do stabilnego profilu potrzebne są porównywalne obserwacje poszczególnych godzin; brak wystarczającej historii uruchamia jawny fallback. Zweryfikuj, że główny LOAD obejmuje odbiorniki używane w modelu.

## Solcast — konfiguracja w panelu

1. W [Solcast Toolkit](https://toolkit.solcast.com.au/) skonfiguruj konto i instalacje. Moc AC/DC, azymut, nachylenie i sprawność należą do konfiguracji usługi Solcast.
2. W panelu wybierz **Połącz i skonfiguruj Solcast → Połącz / zmień ustawienia**. Dostępna jest również droga **Integracje → Deye EMS → Konfiguruj → Solcast — połączenie i ustawienia**. Jeżeli działa sterowanie, najpierw jawnie wybierz **Przejdź do obserwacji**.
3. Wpisz klucz API i identyfikatory `rooftop_resource_id` oddzielone przecinkami. Puste identyfikatory pozwalają spróbować wykrywania; jeśli API go nie obsługuje, wpisz je ręcznie.
4. Dobierz odstęp pobierania i limit konta. Każda instalacja wymaga osobnego zapytania, a wykrywanie oraz nieudane próby mogą również zużyć limit. Dwie instalacje odpytywane co 6 h oznaczają zwykle 8 zapytań na dobę, bez dodatkowych prób. Domyślny limit wynosi 10 na dobę UTC; dopasuj go do planu konta zgodnie z [dokumentacją Solcast](https://docs.solcast.com.au/docs/section/rooftop-sites-hobbyist).
5. Podaj znane wykorzystanie bieżącej doby. Jeśli jest nieznane, pozostaw pełny limit i poczekaj na następną dobę UTC. Wartość ta nie obniża istniejącego rejestru, lecz może go podnieść.
6. Dla prognozy całej instalacji pozostaw skalowanie 1:1. Moc kWp nie mnoży ponownie prognozy obliczonej dla instalacji w portalu. Mnożnik stały i 24 korekty godzinowe zmieniaj świadomie; osobny tryb profilu referencyjnego wymaga właściwej mocy odniesienia.
7. Wybierz **Zapisz i włącz pobieranie API**. Zapis włącza klienta i kolejne pobrania mogą zużyć limit. Zaczekaj na nowy plan, sprawdź go i osobno włącz sterowanie.

Otwarcie lub anulowanie kreatora, a także aktualizacja wersji, nie przełączają źródła. **Anuluj kreator** odrzuca niezapisany szkic. **Zamknij kreator** po zapisie nie cofa konfiguracji. Wyłączenie pobierania w panelu wymaga osobnego potwierdzenia i zachowuje klucz oraz kalibrację.

Zapisany klucz pozostaje ukryty; puste pole zachowuje dotychczasowy. Klucz wpisany w formularzu jest przechowywany nietrwale i czyszczony po zakończeniu lub zamknięciu. Panel statusu, plan, cache i diagnostyka nie udostępniają klucza.

### Import istniejącej konfiguracji

Wybierz **Importuj ustawienia z HA** i wskaż wpis `solcast_solar`. Import kopiuje dostępny klucz, limit konta, wykluczenia oraz bieżące 24/48 współczynników. Kalibracja jest odczytywana z encji przypisanej do wybranej integracji przez rejestr HA, bez zależności od jej wyświetlanej nazwy.

Jest to snapshot, bez historii i dalszego samouczenia poprzedniego klienta. Kreator pokazuje zakres importu, a wymagający przeglądu import wymaga dodatkowego potwierdzenia. Brak kompletnych korekt zatrzymuje import. Dane pozostają szkicem aż do zapisu formularza. Korekty są stosowane wyłącznie do surowego API EMS; prognozy odczytywane z encji HA nie są korygowane ponownie.

Import nie zatrzymuje innej integracji. Przy zmianie klienta użytkownik osobno zarządza jej odpytywaniem, aby nie współdzielić nieświadomie limitu konta. EMS utrwala wykorzystanie przed HTTP; restart, import i zapis konfiguracji nie zerują licznika bieżącej doby.

## Dodatkowe zużycia

W panelu użyj **Dodaj odbiornik**, podaj nazwę, licznik energii Wh/kWh i opcjonalną moc W/kW. **Edytuj** zmienia konfigurację, **Usuń** usuwa kanał, a ON/OFF zachowuje jego dane i identyfikator. Zmiany wymagają obserwacji i nie wznawiają sterowania automatycznie.

Kanały służą wyłącznie modelowaniu SoC. Nie sterują urządzeniami i nie są ponownie dodawane do bieżącego LOAD ani ograniczania importu. Przy niedostatecznej historii kanału model korzysta z całkowitego LOAD.

## Motyw panelu

Rozwiń **Ustawienia zaawansowane i szczegóły**, a w polu **Motyw panelu** wybierz motyw i zapisz. Lista zawiera motywy już dostępne w HA. Możesz wskazać ten sam motyw co w innym widoku Lovelace; motyw przypisany do pojedynczego widoku nie jest automatycznie motywem całego profilu.

**Bieżący motyw HA** usuwa lokalne nadpisanie i przywraca dziedziczenie profilu. Wybór zapisuje integracja; nie zmienia to motywu pozostałych ekranów, parametrów sterowania ani źródła prognozy. Gdy zapisany motyw zostanie usunięty z HA, panel zgłasza jego brak i korzysta z motywu profilu.

## Aktualizacja i zakończenie pracy

Zaktualizuj przez Marketplace albo podmień katalog integracji z ZIP i wykonaj wymagany restart HA. Zachowaj wpis konfiguracji i magazyn runtime, aby zachować ustawienia, cache oraz rejestr prób. Sama aktualizacja nie wybiera nowego źródła Solcast.

Przed usunięciem integracji jawnie wybierz obserwację i sprawdź odczyty urządzenia. Gdy EMS nadal ma wyłączną kontrolę, przejście z active do shadow próbuje wyłączyć Grid Charge i ustawić 0 A. Samo wyładowanie kodu nie wysyła poleceń sprzętowych; ostatnie ustawienia mogą pozostać w urządzeniu.

[README](README.md) · [Specyfikacja](SPECIFICATION.md) · [Przejście i powrót](MIGRATION.md) · [Testy](VALIDATION.md)
