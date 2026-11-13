# Instalacja i obsługa Deye EMS 2.0.1

**Po instalacji panel Deye EMS znajdziesz w lewym menu Home Assistant.** Profil baterii „Deye” korzysta z danych falownika; „YamBMS” jest opcjonalny. W panelu, w sekcji „Źródła danych”, wybierz prefiks i profil, sprawdź encje, a następnie osobno zapisz przypisania w obserwacji.

W sekcji „Przyłącze sieciowe” wpisz dozwolony import całej instalacji oraz jednej fazy. Są to parametry przyłącza, niezależne od mocy falownika. Zakres wynosi 1–30 kW łącznie i 0,5–15 kW na fazę. Obowiązują w LOAD i CT; w CT pomiar obejmuje również odbiory przed portem GRID. Regulator zachowuje zapas 0,5 kW łącznie i 0,25 kW na fazę. Aktualizacja zachowuje dotychczasowe wartości.

Wymagany Home Assistant **2026.11.0 lub nowszy**. Integracja działa lokalnie i nie wymaga EMHASS ani zewnętrznego solvera. Użytkownik wybiera źródła danych i parametry właściwe dla swojej instalacji.

## Marketplace

[![Zainstaluj Deye EMS przez Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=gaszu&repository=deye-ems&category=integration)

1. Kliknij przycisk i wskaż instancję HA.
2. Jeżeli repozytorium nie jest jeszcze dodane, zaakceptuj dodanie go jako **Integracja**.
3. Zainstaluj **v2.0.1**. Wykonaj restart, jeżeli HA go wymaga.
4. [Dodaj Deye EMS](https://my.home-assistant.io/redirect/config_flow_start/?domain=deye_ems) przez **Ustawienia → Urządzenia i usługi → Dodaj integrację**.

Alternatywnie w Marketplace użyj **Dodaj z linku** i adresu `https://github.com/gaszu/deye-ems`. Jeżeli integracja ma już wpis, [otwórz istniejącą konfigurację](https://my.home-assistant.io/redirect/integration/?domain=deye_ems); nie dodawaj drugiego wpisu. Po instalacji odśwież przeglądarkę. Panel administratora pojawia się w menu bocznym.

## Instalacja z ZIP

1. Pobierz [deye-ems-2.0.1.zip](https://github.com/gaszu/deye-ems/releases/download/v2.0.1/deye-ems-2.0.1.zip).
2. Rozpakuj i skopiuj cały katalog `custom_components/deye_ems` do `/config/custom_components/deye_ems` swojej instancji.
3. Uruchom HA ponownie i dodaj integrację.

## Gdzie znaleźć panel po instalacji

**Po dodaniu integracji panel Deye EMS znajdziesz na pasku bocznym Home Assistanta.** Wymagane jest konto administratora. Jeśli wpis jest ukryty, sprawdź opcję „Panel boczny” integracji oraz edycję własnego paska HA. Panel można też otworzyć pod adresem `/deye-ems` swojej instancji.

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

## Panel boczny — wersja 1.0.7

W ustawieniach integracji wybierz **Deye EMS → Konfiguruj → Panel boczny → Pokaż Deye EMS w panelu bocznym** i zapisz. Zmiana jest dostępna także przy aktywnym sterowaniu; nie przeładowuje sterownika ani nie zmienia jego trybu. Jest zapisana oddzielnie od ustawień energetycznych.

Panel jest dostępny tylko administratorom. Bezpośredni adres to `/deye-ems` na Twojej instancji, także przy wyłączonej widoczności wpisu. Jeżeli osobisty profil HA ukrywa tę pozycję, przywróć ją również w edycji menu bocznego. Samo pobranie plików z HACS wymaga restartu HA i dodania integracji w Urządzenia i usługi.

Opcja jest dostępna od1.0.7.

## Blokada włączenia sterowania: tryby falownika

Przed aktywacją EMS sprawdza odczyty encji wybranych w **Konfiguruj → Źródła**:

| Źródło | Wymagany stan HA |
|---|---|
| Solar Sell | `on` |
| Time of Use | `on` |
| Energy Management Priority | `Load First` |
| System Work Mode | `Zero Export To Load` lub `Zero Export To CT`, zgodnie z wybraną topologią |

Nazwy encji na innej instancji mogą być inne — przypisz jej właściwe encje. Brak encji, stan `unavailable` albo `restored` również blokują aktywację. EMS nie przełącza sam tych trybów. Dopasowanie trybów musi odpowiadać topologii i planowanemu sposobowi pracy instalacji.

W wersji1.0.6 komunikat brzmi `Inverter modes do not match the EMS model`. Wersja1.0.7 wymienia konkretne encje, odczyty i oczekiwane stany.

## Prefiks encji Deye — wersja1.0.7

Prefiks można wpisać przy dodawaniu integracji lub w **Deye EMS → Konfiguruj → Prefiks encji Deye**. Wpisz część nazwy bez domeny, np. `deye_dom_`. Daje to m.in. `sensor.deye_dom_load_power`, `select.deye_dom_system_work_mode` oraz `number.deye_dom_maximum_battery_grid_charge_current`. Końcowe podkreślenie jest uzupełniane automatycznie.

Zmiana przypisań wymaga obserwacji. Kreator w istniejącej integracji pokazuje znalezione i brakujące encje, a następnie pełny formularz przypisań do sprawdzenia i ręcznej korekty. Dopiero zapis formularza zapisuje przypisania i prefiks. Anulowanie nie zmienia konfiguracji. Prefiks dotyczy wyłącznie encji falownika Deye: nie przepisuje nazw BMS, Solcast ani odbiorników. Prefiks pomaga dobrać nazwy; nie zmienia trybu fizycznego falownika ani nie dodaje obsługi Zero Export To CT. Po zmianie przypisań wznowienie sterowania wymaga jawnego działania użytkownika.

## Dom pod LOAD, CWU między GRID a CT — wersja1.0.7

W obserwacji wybierz **Konfiguruj → Topologia i moc falownika → Dom pod LOAD i odbiory między GRID a CT**. Wpisz moc znamionową urządzenia (np.10kW) i wspólny limit modelu (np.10kW); limit obejmuje cały falownik, a nie osobno LOAD i port GRID. To parametry obliczeń, nie zapis ograniczenia mocy do urządzenia. Ograniczenia fizyczne zapewnia konfiguracja i znamionowa moc falownika.

W **Źródłach** przypisz niezależne pomiary CT przy przyłączu i portu GRID falownika: suma orazL1/L2/L3. Dodatni znak CT oznacza import z sieci, dodatni znak GRID — dopływ do falownika. Dla standardowych nazw CT są to `external_ct_power` i `external_ct_l1_power`/`external_ct_l2_power`/`external_ct_l3_power` z prefiksem Deye. LOAD musi mierzyć samo wyjście LOAD/UPS, bez odbiorów między GRID a CT.

Moc odbiorów między CT a GRID = CT − GRID. Przykład: CT0W i GRID−2000W oznaczają2kW zasilania odbiorów przed falownikiem przy zerowej wymianie z siecią. Do LOAD dodajemy tę moc dokładnie raz. Osobny licznik CWU nie jest wymagany do bieżącego bilansu; historia prognozy wymaga wspólnych godzinowych średnich LOAD, CT i portu GRID. Niekompletna historia nie jest zastępowana profilem samego LOAD.

Pomiary muszą być świeże (do30s), bez restored, wW; znaczniki CT i portu GRID muszą mieścić się w10s. Wymagana jest zgodność sum i faz (tolerancja większa z300W i10% sumy) oraz nieujemny bilans odbiorów między CT a GRID (do200W tolerancji). Sterowanie nie zakłada bilansowania faz CT na podstawie przełącznika dotyczącego LOAD: zwiększenia prądu stosują zachowawczy model fazowy. Tryb wymagany w tej topologii to **Zero Export To CT**; EMS nie przełącza go sam.

Zmiana topologii lub przypisań unieważnia stary plan i cache celu oraz wymaga ręcznego wznowienia. Panel pokazuje osobno sieć mierzoną na CT, LOAD, odbiory przed falownikiem i port GRID. Sekcja **Układ LOAD** lub **Układ LOAD i CT** pozostaje zawsze widoczna na głównym ekranie i opisuje znaczenie pomiarów w zapisanym układzie. W układzie LOAD odbiory między GRID a CT są nieobliczane. Nieaktualny lub niezgodny odczyt jest oznaczony jako brak danych. Testy offline nie potwierdzają kierunków rzeczywistych czujników ani reakcji sprzętu.

## Sprawdzanie aktualizacji — od 1.0.17

W głównym panelu wybierz **Sprawdź aktualizacje** w sekcji **Wersja i aktualizacje**. Informacja dotyczy najnowszego stabilnego wydania publicznego, a wersja HA wskazuje rzeczywiście załadowany kod. Sama instalacja nowych plików może jeszcze wymagać restartu HA. Sprawdzenie jest ręczne, z co najmniej 60 s przerwy między próbami, i nie zmienia trybu EMS.

**Otwórz Marketplace** prowadzi do sklepu bieżącej instancji. Jeśli sklep pokazuje tylko stare wydanie, otwórz menu repozytorium Deye EMS i wybierz odświeżenie informacji. Przed aktualizacją zachowaj kopię ustawień i paczkę poprzedniej wersji, przejdź do obserwacji i potwierdź zatrzymanie doładowania z sieci. Po instalacji sprawdź konfigurację, wykonaj wymagany restart i zweryfikuj pomiary, ustawienia i plan przed wznowieniem wcześniejszego trybu.

Przycisk **Odśwież interfejs** służy do pobrania nowszej wersji otwartej karty; jest blokowany przy niezapisanych formularzach. Nie zastępuje restartu backendu, jeśli HA nadal ma załadowaną starszą wersję. Karta otwarta jeszcze przed instalacją 1.0.17 wymaga jednorazowego pełnego odświeżenia, aby wyświetlić nową sekcję.

## Automatyczna moc ładowania — od 1.0.15

Nie wpisuje się już „Modelowego limitu ładowania”. Prognoza korzysta z ogólnego limitu prądu Deye, BMS, napięcia baterii i mocy falownika, ze wspólnym budżetem dla PV i sieci. Dla sieci dodatkowo obowiązują Deye−5%, zakres nastawy i dostępna moc. Przypisania niezależnego limitu Deye i sterowanej nastawy GRID pozostają rozdzielone. Dawna encja modelowego limitu jest wyłączana z zachowaniem historii; ustawienie modelowego rozładowania pozostaje osobne.

## Priorytet PV w bieżącym sterowaniu — od 1.0.16

Istniejące przypisania **battery_power** i natywnego **grid_power** oraz faz GRID służą do oszacowania nadwyżki lokalnej pomniejszającej potrzebę ładowania z sieci. Bateria ma znak minus podczas ładowania; port GRID ma znak plus przy dopływie do falownika. Nie przypisuj CT zamiast portu GRID ani jednej encji do obu pomiarów. Wymagane są niezależne, poprawne odczyty W do 30 s, rozbieżne czasowo najwyżej o 10 s. Brak poprawnych danych blokuje ładowanie sieciowe zamiast przyjmować PV równe zero.

Panel pokazuje zachowawczy szacunek nadwyżki i potrzebę doładowania po stronie baterii. Nie są to odczyty dokładnej produkcji PV ani AC importu. Pokrycie potrzeby przez PV może zatrzymać doładowanie bez osiągnięcia celu SoC; wznowienie nadal respektuje harmonogram zapisów i stabilizację pomiarów. Fizyczne ładowanie z PV pozostaje sterowane przez falownik.

## Rezerwa SoC — dolna granica z Battery low SOC

Minimalną rezerwę EMS można ustawić od aktualnej nastawy `number.deye_inverter_battery_low_soc` powiększonej o5punktów procentowych do90%. To bieżąca wartość progu falownika, a nie atrybut `min` encji. Przykład: Battery low SOC10% → rezerwa EMS od15%. Ułamkowy próg jest zaokrąglany w górę do pełnego procenta. Domyślna rezerwa EMS pozostaje40%, ale nie jest już dolnym limitem formularza.

Encja jest wybierana wŹródłach i obsługiwana przez prefiksDeye. Limit obowiązuje w panelu, konfiguracji HA, encji liczbowej, walidacji backendu, planowaniu i nastawach TOU. Zwiększenie progu falownika automatycznie podnosi skuteczną rezerwę ponad niższe zapisane życzenie użytkownika. Nowy cel musi także mieścić rezerwę i bufor do maksymalnego celu ładowania.

Brak, restored, niepoprawna jednostka lub wartość encji blokują zmianę rezerwy i aktywację. Przy utracie odczytu w czasie pracy EMS zeruje ładowanie z sieci i wyłączaGC, nie obniżaTOU i zachowuje konserwatywną poprzednią granicę. Nie zmienia samej nastawy Battery low SOC. Wspierany odczyt0–85% zapewnia miejsce na5p.p. zapasu przy maksymalnej rezerwie90%.

Wybór LOAD/CT jest dostępny bezpośrednio w panelu w sekcji **Pomiar i sterowanie**. Selektor konfiguruje model EMS, a odczyt fizycznego trybu falownika jest pokazany oddzielnie. Zapis wymaga obserwacji, nie zmienia sam nastawy trybu falownika i nie wznawia sterowania.
