# Instalacja i obsługa Deye EMS

Menu boczne EMS zawiera odnośniki do sekcji. Na telefonie jest dostępne pod przyciskiem „Sekcje”.

Kafelki układu pod podsumowaniem pokazują moc i kierunek przepływu portu GRID, a w trybie CT także przyłącza. Odczyty faz są na tych samych kafelkach. Zielony oznacza poprawny stan, czerwony błąd, żółty informację, a niebieski grupuje odczyty odbiorów.

EMS używa wewnętrznego CT Deye (suma i wymagane fazy) do pomiaru portu GRID w obu trybach. Zewnętrzne CT jest wymagane tylko w Zero Export To CT, gdzie mierzy przyłącze. Zapisane niestandardowe przypisania pozostają w użyciu. EMS blokuje sterowanie bez wymaganych świeżych pomiarów. Alternatywne nazwy encji miernika portu przypisz ręcznie.

Instrukcja dla wydania [Deye EMS 2.7.1](https://github.com/gaszu/deye-ems/releases/tag/v2.7.1).

Do instalacji użyj [najnowszego stabilnego wydania](https://github.com/gaszu/deye-ems/releases/latest). Przed konfiguracją sprawdź połączenie falownika przez mostek Modbus RS-485, przypisanie encji Home Assistant i zgodność profilu taryfy z umową.

## Wymagania

- **Home Assistant 2026.11.0 lub nowszy** i konto administratora.
- Obsługiwany hybrydowy falownik Deye i magazyn energii. Wybierz dokładny model jedno- lub trójfazowy albo skonfiguruj model własny. [Katalog modeli](custom_components/deye_ems/inverter_models.py)
- Fizyczny mostek **Modbus RS-485** podłączony do falownika, połączony z HA przez Wi-Fi lub przewodowy LAN. Sprawdź dostępność aktualnych odczytów i zapisywalnych encji ładowania oraz TOU.
- Dane baterii z Deye, YamBMS lub ręcznie przypisanych encji. Przed włączeniem automatyki sprawdź SoC, napięcie i sygnały ograniczeń BMS wymagane dla profilu.
- Zastosowanie docelowe to polski system opustów. Nowa konfiguracja taryfy obsługuje TAURON Dystrybucja G11, G12, G12w i G13.

## Marketplace

[![Zainstaluj Deye EMS przez Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=gaszu&repository=deye-ems&category=integration)

1. Kliknij przycisk i wskaż instancję HA.
2. Jeżeli repozytorium nie jest jeszcze dodane, zaakceptuj dodanie go jako **Integracja**.
3. Zainstaluj [najnowsze stabilne wydanie](https://github.com/gaszu/deye-ems/releases/latest). Wykonaj restart, jeżeli HA go wymaga.
4. [Dodaj Deye EMS](https://my.home-assistant.io/redirect/config_flow_start/?domain=deye_ems) przez **Ustawienia → Urządzenia i usługi → Dodaj integrację**.

Alternatywnie w Marketplace użyj **Dodaj z linku** i adresu `https://github.com/gaszu/deye-ems`. Jeżeli integracja ma już wpis, [otwórz istniejącą konfigurację](https://my.home-assistant.io/redirect/integration/?domain=deye_ems); nie dodawaj drugiego wpisu. Po instalacji odśwież przeglądarkę. Panel administratora pojawia się w menu bocznym.

## Instalacja z ZIP

1. Pobierz [paczkę ZIP z najnowszego wydania](https://github.com/gaszu/deye-ems/releases/latest).
2. Rozpakuj i skopiuj cały katalog `custom_components/deye_ems` do `/config/custom_components/deye_ems` swojej instancji.
3. Uruchom HA ponownie i dodaj integrację.

## Gdzie znaleźć panel po instalacji

**Po dodaniu integracji panel Deye EMS znajdziesz na pasku bocznym Home Assistanta.** Wymagane jest konto administratora. Jeśli wpis jest ukryty, sprawdź opcję „Panel boczny” integracji oraz edycję własnego paska HA. Panel można też otworzyć pod adresem `/deye-ems` swojej instancji.

## Regulacja prądu i zakończenie ładowania

W potwierdzonej taryfie, w dozwolonych oknach od 21:00 do 07:00, EMS priorytetowo ładuje do porannego celu SoC z dostępną mocą. Między dodatnimi poleceniami zachowuje co najmniej 120 s. Po osiągnięciu celu ustawia 0 A, a histereza wznowienia wynosi 5 p.p. Poza tym trybem zwykła korekta nastawy wynosi najwyżej 10 A co 600 s, z uwzględnieniem kroku urządzenia. Po osiągnięciu celu prąd maleje stopniowo. Maksymalny SoC, niedozwolone okno, stan BMS, utrata prawidłowych pomiarów lub nagły wzrost poboru mogą spowodować natychmiastową redukcję.

W dozwolonych slotach kalendarza EMS uzbraja Grid Charge, gdy spełnione są warunki bezpieczeństwa. Gdy wystarczy przerwać doładowanie po osiągnięciu celu, prąd 0 A pozwala zachować uzbrojenie slotu. Przy ocenie efektu rozróżniaj wysłane polecenie, odczyt nastawy i rzeczywistą moc baterii.

## TOP BALANCE

W aktywnym EMS ustaw docelowy SoC jako liczbę całkowitą od 1 do 100% w zakresie akceptowanym przez falownik. Przycisk znajduje się po lewej pod podsumowaniem akumulatora. Tryb włącza Grid Charge w bieżącym slocie także przy drogiej taryfie i wykorzystuje dostępną moc w granicach aktualnych pomiarów i limitów instalacji.

Po osiągnięciu celu lub ręcznym zakończeniu EMS przywraca próg SoC i Grid Charge slotu, a następnie przelicza prąd według zwykłego planu. Przy zmianie slotu najpierw odtwarza nastawy poprzedniego. Po restarcie kończy przerwaną sesję i odtwarza zapisane nastawy.

## Pierwsza konfiguracja

1. Wpisz minimalny bezpieczny SoC, pojemność baterii, moc PV, moc falownika łącznie i na fazę oraz osobne limity importu. Domyślne wartości produktu to m.in. 40%, 66 kWh, 12 kW łącznie i 5 kW na fazę; wymagają dopasowania do urządzeń.
2. Uzupełniaj konfigurację w **shadow / obserwacja**. W tym trybie integracja pokazuje obliczenia bez zwykłego sterowania ładowaniem.
3. W **Konfiguruj → Encje pomiarowe i sterujące** sprawdź lub zastąp przykładowe przypisania. Każde wyjście musi wskazywać właściwą, istniejącą encję, a wyjścia muszą mieć unikalne przypisania.
4. Skonfiguruj źródło prognozy PV i ewentualne dodatkowe profile zużycia.
5. Wybierz operatora, taryfę oraz zegar zgodne z umową i licznikiem. Sprawdź podgląd, a następnie zatwierdź końcowy zapis. Silnik sam sprawdzi świeże pomiary, plan i zabezpieczenia przed włączeniem sterowania. Jeśli nie może go włączyć, pozostanie w obserwacji z podaną przyczyną. Zasady przejścia i powrotu: [MIGRATION.md](MIGRATION.md).

Ustaw limit importu całej instalacji oraz limit fazowy przyłącza w sekcji **Przyłącze sieciowe**. W topologii CT bilans uwzględnia też odbiory pomiędzy portem GRID a licznikiem CT. Dobierz limity do przyłącza i osobno wpisz właściwe parametry falownika.

Wymagane pomiary obejmują SoC i napięcie baterii, GRID/LOAD zgodnie z wybraną liczbą faz, moc baterii oraz odczyt nastawy prądu ładowania. Profile YamBMS i ręczny zachowują wymagania limitu i blokady BMS. Sterowanie wymaga zgodnych ustawień trybów falownika i mapowań TOU. Szczegółowe warunki opisuje [SPECIFICATION.md](SPECIFICATION.md). Integracja nie ustawia automatycznie wszystkich trybów sprzętowych.

Dla wybranego falownika jednofazowego i profilu baterii „Deye” formularz źródeł może zaproponować istniejące w HA encje `sensor.<prefiks>_battery`, `switch.<prefiks>_time_of_use_<n>_charge_enable` oraz `sensor.<prefiks>_device_alarm` i `sensor.<prefiks>_device_fault`. Są to nazwy używane przez [Lewa-Reka dla baterii 1P](https://github.com/Lewa-Reka/esphome-deye-inverter/blob/v0.13.0/pv_inverter/packages/deye_hybrid_1p/battery.yaml), [ładowania w slotach 1P](https://github.com/Lewa-Reka/esphome-deye-inverter/blob/v0.13.0/pv_inverter/packages/deye_hybrid_1p/tou.yaml) i [alarmów falownika 1P](https://github.com/Lewa-Reka/esphome-deye-inverter/blob/v0.13.0/pv_inverter/packages/deye_hybrid_1p/device.yaml). Propozycja dotyczy tylko brakującego domyślnego przypisania; własne encje i puste wyłączenia pozostają zachowane. Samo otwarcie formularza lub aktualizacja nie zmienia zapisanych źródeł.

Źródłowy sterownik 1P może nie publikować bieżącego limitu ładowania BMS (CCL). Gdy encja CCL nie istnieje albo jej przypisanie jest świadomie wyłączone, profil „Deye” korzysta z 95% maksymalnego prądu ładowania odczytanego z ustawień Deye. Jeśli CCL jest dostępny, jego niższa wartość dodatkowo ogranicza ładowanie. Błędny lub niedostępny odczyt istniejącej encji nie uruchamia przejścia na sam limit Deye, a CCL równy 0 A blokuje ładowanie. Profile YamBMS i ręczny nie korzystają z tego zastępstwa. Alarm i błąd baterii nadal wymagają poprawnych źródeł; prawidłowy model i sam odczyt SoC nie wystarczą do aktywacji.

W jednofazowym profilu Deye sensory `device_alarm` i `device_fault` opisują stan całego falownika. Tylko prawidłowy stan `OK` potwierdza brak problemu. Opis błędu, `Error`, `N/A`, brak lub niedostępność odczytu blokują sterowanie; wymagane pozostają także żywe pomiary i pozostałe zabezpieczenia EMS.

Recorder HA dostarcza do 42 dni statystyk godzinowych LOAD i liczników energii. Planer porównuje ostatni tydzień z wcześniejszą historią dla tych samych godzin i ogranicza wpływ korekty trendu. Przy braku wystarczających danych stosuje profil łączny lub plan zachowawczy, zależnie od jakości dostępnych danych. W CT Recorder musi też dostarczyć spójną historię pomiaru CT i portu GRID.

## Solcast — konfiguracja w panelu

P10 służy do ostrożnego wyznaczania zapasu i oceny ryzyka niedoboru. P50 służy do wyświetlania prognozy SoC i oceny pokrycia zużycia przez PV przy wyznaczaniu zimowego celu pogodowego. [Znaczenie P10 i P50](README.md#co-oznaczają-p10-i-p50)

1. W [Solcast Toolkit](https://toolkit.solcast.com.au/) skonfiguruj konto i instalacje. Moc AC/DC, azymut, nachylenie i sprawność należą do konfiguracji usługi Solcast.
2. W panelu wybierz **Połącz i skonfiguruj Solcast → Połącz / zmień ustawienia**. Dostępna jest również droga **Integracje → Deye EMS → Konfiguruj → Solcast — połączenie i ustawienia**. Jeżeli działa sterowanie, najpierw jawnie wybierz **Przejdź do obserwacji**.
3. Wpisz klucz API i identyfikatory `rooftop_resource_id` oddzielone przecinkami. Puste identyfikatory pozwalają spróbować wykrywania; jeśli API go nie obsługuje, wpisz je ręcznie.
4. Dobierz odstęp pobierania i limit konta. Każda instalacja wymaga osobnego zapytania, a wykrywanie oraz nieudane próby mogą również zużyć limit. Dwie instalacje odpytywane co 6 h oznaczają zwykle 8 zapytań na dobę, bez dodatkowych prób. Domyślny limit wynosi 10 na dobę UTC; dopasuj go do planu konta zgodnie z [dokumentacją Solcast](https://docs.solcast.com.au/docs/section/rooftop-sites-hobbyist).
5. Podaj znane wykorzystanie bieżącej doby. Jeśli jest nieznane, pozostaw pełny limit i poczekaj na następną dobę UTC. Wartość ta nie obniża istniejącego rejestru, lecz może go podnieść.
6. Dla prognozy całej instalacji pozostaw skalowanie 1:1. Moc kWp nie mnoży ponownie prognozy obliczonej dla instalacji w portalu. Mnożnik stały i 24 korekty godzinowe zmieniaj świadomie; osobny tryb profilu referencyjnego wymaga właściwej mocy odniesienia.
7. Wybierz **Zapisz i włącz pobieranie API**. Zapis włącza klienta i kolejne pobrania mogą zużyć limit. Kreator zamknie się, a silnik sprawdzi warunki automatycznego wznowienia. Obserwuj wynik przy trybie pracy u góry panelu.

Otwarcie lub anulowanie kreatora, a także aktualizacja wersji, nie przełączają źródła. **Anuluj kreator** odrzuca niezapisany szkic. Po zapisie kreator zamyka się automatycznie; wynik sprawdzania pozostaje widoczny w panelu. Wyłączenie pobierania w panelu wymaga osobnego potwierdzenia i zachowuje klucz oraz kalibrację.

Zapisany klucz pozostaje ukryty; puste pole zachowuje dotychczasowy. Klucz wpisany w formularzu jest przechowywany nietrwale i czyszczony po zakończeniu lub zamknięciu. Panel statusu, plan, cache i diagnostyka nie udostępniają klucza.

### Import istniejącej konfiguracji

Wybierz **Importuj ustawienia z HA** i wskaż wpis `solcast_solar`. Import kopiuje dostępny klucz, limit konta, wykluczenia oraz bieżące 24/48 współczynników. Kalibracja jest odczytywana z encji przypisanej do wybranej integracji przez rejestr HA, bez zależności od jej wyświetlanej nazwy.

Jest to snapshot, bez historii i dalszego samouczenia poprzedniego klienta. Kreator pokazuje zakres importu, a wymagający przeglądu import wymaga dodatkowego potwierdzenia. Brak kompletnych korekt zatrzymuje import. Dane pozostają szkicem aż do zapisu formularza. Korekty są stosowane wyłącznie do surowego API EMS; prognozy odczytywane z encji HA nie są korygowane ponownie.

Import nie zatrzymuje innej integracji. Przy zmianie klienta użytkownik osobno zarządza jej odpytywaniem, aby nie współdzielić nieświadomie limitu konta. EMS utrwala wykorzystanie przed HTTP; restart, import i zapis konfiguracji nie zerują licznika bieżącej doby.

## Dodatkowe zużycia

W panelu użyj **Dodaj odbiornik**, podaj nazwę, licznik energii Wh/kWh i opcjonalną moc W/kW. **Edytuj** zmienia konfigurację, **Usuń** usuwa kanał, a ON/OFF zachowuje jego dane i identyfikator. Zmiany wymagają obserwacji. Zapis zmienionych opcji uruchamia sprawdzenie warunków wznowienia; wynik jest widoczny u góry panelu.

W LOAD dodawaj odbiorniki ujęte w pomiarze wyjścia LOAD. W CT możesz dodać również odbiorniki między portem GRID a licznikiem CT, jeśli ich moc jest już ujęta w bilansie. EMS aktualizuje prognozę wraz z historią i oddziela prognozę odbiornika od prognozy reszty domu, aby nie doliczać jego energii podwójnie. Przełącznik kanału zmienia modelowanie. Chwilowy limit importu nadal wynika z bieżących pomiarów.

## Motyw panelu

Rozwiń **Ustawienia zaawansowane i szczegóły**, a w polu **Motyw panelu** wybierz motyw i zapisz. Lista zawiera motywy już dostępne w HA. Możesz wskazać ten sam motyw co w innym widoku Lovelace; motyw przypisany do pojedynczego widoku nie jest automatycznie motywem całego profilu.

**Bieżący motyw HA** usuwa lokalne nadpisanie i przywraca dziedziczenie profilu. Wybór zapisuje integracja; nie zmienia to motywu pozostałych ekranów, parametrów sterowania ani źródła prognozy. Gdy zapisany motyw zostanie usunięty z HA, panel zgłasza jego brak i korzysta z motywu profilu.

## Aktualizacja i zakończenie pracy

Zaktualizuj przez Marketplace albo podmień katalog integracji z ZIP i wykonaj wymagany restart HA. Zachowaj wpis konfiguracji i magazyn runtime, aby zachować ustawienia, cache oraz rejestr prób. Sama aktualizacja nie wybiera nowego źródła Solcast.

Przed usunięciem integracji jawnie wybierz obserwację i sprawdź odczyty urządzenia. Gdy EMS nadal ma wyłączną kontrolę, przejście z active do shadow próbuje wyłączyć Grid Charge i ustawić 0 A. Samo wyładowanie kodu nie wysyła poleceń sprzętowych; ostatnie ustawienia mogą pozostać w urządzeniu.

[README](README.md) · [Specyfikacja](SPECIFICATION.md) · [Przejście i powrót](MIGRATION.md) · [Testy](VALIDATION.md)

## Panel boczny

W ustawieniach integracji wybierz **Deye EMS → Konfiguruj → Panel boczny → Pokaż Deye EMS w panelu bocznym** i zapisz. Zmiana jest dostępna także przy aktywnym sterowaniu; nie przeładowuje sterownika ani nie zmienia jego trybu. Jest zapisana oddzielnie od ustawień energetycznych.

Panel jest dostępny tylko administratorom. Bezpośredni adres to `/deye-ems` na Twojej instancji, także przy wyłączonej widoczności wpisu. Jeżeli osobisty profil HA ukrywa tę pozycję, przywróć ją również w edycji menu bocznego. Samo pobranie plików z HACS wymaga restartu HA i dodania integracji w Urządzenia i usługi.

## Blokada włączenia sterowania: tryby falownika

Przed aktywacją EMS sprawdza odczyty encji wybranych w **Konfiguruj → Źródła**:

| Źródło | Wymagany stan HA |
|---|---|
| Solar Sell | `on` |
| Time of Use | `on` |
| Energy Management Priority | `Load First` |
| System Work Mode | `Zero Export To Load` lub `Zero Export To CT`, zgodnie z wybraną topologią |

Nazwy encji na innej instancji mogą być inne — przypisz jej właściwe encje. Brak encji, stan `unavailable` albo `restored` również blokują aktywację. EMS nie przełącza sam tych trybów. Dopasowanie trybów musi odpowiadać topologii i planowanemu sposobowi pracy instalacji.

Panel wskazuje brakujące lub niezgodne odczyty potrzebne do aktywacji.

## Prefiks encji Deye

Prefiks można wpisać przy dodawaniu integracji lub w **Deye EMS → Konfiguruj → Prefiks encji Deye**. Wpisz część nazwy bez domeny, np. `deye_dom_`. Daje to m.in. `sensor.deye_dom_load_power`, `select.deye_dom_system_work_mode` oraz `number.deye_dom_maximum_battery_grid_charge_current`. Końcowe podkreślenie jest uzupełniane automatycznie.

Zmiana przypisań wymaga obserwacji. Kreator w istniejącej integracji pokazuje znalezione i brakujące encje, a następnie pełny formularz przypisań do sprawdzenia i ręcznej korekty. Dopiero zapis formularza zapisuje przypisania i prefiks. Anulowanie nie zmienia konfiguracji. Prefiks dotyczy wyłącznie encji falownika Deye: nie przepisuje nazw BMS, Solcast ani odbiorników. Prefiks pomaga dobrać nazwy; nie zmienia trybu fizycznego falownika ani nie dodaje obsługi Zero Export To CT. Po końcowym zapisie kreatora silnik sprawdza warunki automatycznego wznowienia; samo otwarcie, podgląd lub anulowanie nie uruchamiają sterowania.

## Dom pod LOAD, CWU między GRID a CT

W obserwacji wybierz **Konfiguruj → Topologia i moc falownika → Dom pod LOAD i odbiory między GRID a CT**. Wpisz moc znamionową urządzenia (np.10kW) i wspólny limit modelu (np.10kW); limit obejmuje cały falownik, a nie osobno LOAD i port GRID. To parametry obliczeń, nie zapis ograniczenia mocy do urządzenia. Ograniczenia fizyczne zapewnia konfiguracja i znamionowa moc falownika.

W **Źródłach** przypisz niezależne pomiary CT przy przyłączu i portu GRID falownika: suma orazL1/L2/L3. Dodatni znak CT oznacza import z sieci, dodatni znak GRID — dopływ do falownika. Dla standardowych nazw CT są to `external_ct_power` i `external_ct_l1_power`/`external_ct_l2_power`/`external_ct_l3_power` z prefiksem Deye. LOAD musi mierzyć samo wyjście LOAD/UPS, bez odbiorów między GRID a CT.

Moc odbiorów między CT a GRID = CT − GRID. Przykład: CT0W i GRID−2000W oznaczają2kW zasilania odbiorów przed falownikiem przy zerowej wymianie z siecią. Do LOAD dodajemy tę moc dokładnie raz. Osobny licznik CWU nie jest wymagany do bieżącego bilansu; historia prognozy wymaga wspólnych godzinowych średnich LOAD, CT i portu GRID. Niekompletna historia nie jest zastępowana profilem samego LOAD.

Do bilansu EMS potrzebuje świeżych, spójnych pomiarów CT i portu GRID, z poprawnymi jednostkami, znakami i wartościami poszczególnych faz. Wspólny budżet mocy falownika obejmuje sumę faz oraz odbiorniki uwzględnione w bilansie. Regulator sprawdza zapas przyłącza i odczyty GRID przed zwiększeniem prądu. Wymagany tryb falownika to **Zero Export To CT**. EMS go nie przełącza.

Zmiana topologii lub przypisań unieważnia stary plan i cache celu. Zapis kreatora lub zmienionych opcji, także selektora LOAD/CT w panelu, może wznowić sterowanie dopiero po ponownym sprawdzeniu warunków. Panel pokazuje osobno sieć mierzoną na CT, LOAD, odbiory przed falownikiem i port GRID. Sekcja **Układ LOAD** lub **Układ LOAD i CT** w **Ustawieniach zaawansowanych i szczegółach** opisuje znaczenie pomiarów w zapisanym układzie. W układzie LOAD odbiory między GRID a CT są nieobliczane. Nieaktualny lub niezgodny odczyt jest oznaczony jako brak danych. Testy offline nie potwierdzają kierunków rzeczywistych czujników ani reakcji sprzętu.

## Taryfa TAURON i automatyczny start po zapisie

1. Otwórz **Wybierz taryfę TAURON**. Podczas sterowania najpierw jawnie przejdź do obserwacji.
2. Operator jest stały: **TAURON Dystrybucja**. Wybierz zgodną z umową taryfę **G11, G13, G12w albo G12**. Nowego profilu innego operatora obecnie nie można wybrać; istniejąca obca lub własna konfiguracja nie jest automatycznie zastępowana.
3. Potwierdź zegar licznika. **Czas lokalny** uwzględnia zmianę lato/zima; **stały CET** pozostaje czasem zimowym. Nie dobieraj tego ustawienia na podstawie pory roku. Ustal je dla swojego układu pomiarowego. Zegary HA i falownika muszą być prawidłowe.
4. Sprawdź podgląd dni roboczych, wolnych, sezonu i godzin. Zaznacz potwierdzenie zgodności z umową i wybierz **Zapisz potwierdzoną taryfę**. Anulowanie odrzuca szkic, a zmiana konfiguracji w tle unieważnia stary podgląd.
5. Kreator zamknie się sam. Silnik HA oczekuje na nową konfigurację, pomiary i obliczenia, a następnie używa zwykłych zabezpieczeń aktywacji. Poprawny plan zachowawczy może być użyty jawnie bez udawania pełnej prognozy. Oczekiwanie i przyczyny blokady pozostają widoczne; przeglądarka nie musi być otwarta.
6. Przycisk **Zatrzymaj i obserwuj** u góry panelu anuluje oczekujący start, również gdy bieżący tryb nadal jest obserwacją. Zapis źródeł, modelu i Solcast podlega tej samej zasadzie; samo zamknięcie albo anulowanie bez zapisu nie aktywuje EMS.

Sprawdzanie po zapisie obejmuje wszystkie zmienione opcje wpisu integracji, także odbiorniki i parametry panelu. Motyw i widoczność menu bocznego są osobne: ich zapis, odczyty katalogu, podgląd, anulowanie oraz ręczny STOP nie inicjują automatycznej aktywacji.

Przy przeładowaniu aktywnej konfiguracji silnik najpierw żąda wyłączenia Grid Charge i 0 A oraz wymaga poprawnych odczytów potwierdzających. Brak potwierdzenia blokuje przeładowanie i jest pokazywany jako błąd. Potwierdzenie nastaw nie jest pomiarem fizycznej reakcji urządzenia.

Tabela taryfy rozdziela zgodę strefy, cel doładowania, stałą rezerwę i projekcję SoC. Projekcja bieżącego przedziału zaczyna się od podanej chwili. Wartości minione lub nieznane nie otrzymują sztucznego 0%. Sześć wpisów TOU ma stałe godziny sezonowego szablonu. W G13 EMS zachowuje jednakowe godziny sterowania każdego dnia danego sezonu. W G12w weekend lub święto może oznaczać tanią strefę przez całą dobę. Panel pokazuje to dla dziś i jutra, gdy kalendarz jest potwierdzony. Podział nie tworzy nowych stref OSD ani sześciu nowych terminów celu. Dla cyklicznego szablonu lub stałego CET lokalna doba może pokazywać fragmenty jednego wpisu po obu stronach północy. Godziny i fragmenty pochodzą z backendu. Po instalacji osobno sprawdź przyjęcie programu i rzeczywiste odczyty godzin oraz flag; sam podgląd ich nie potwierdza. [Źródła i warunki taryf](TARIFFS.md).

## Sprawdzanie aktualizacji

EMS sprawdza najnowsze stabilne wydanie po uruchomieniu HA (około 30 s później), następnie co godzinę. Własna encja **Deye EMS — Nowe wydanie** przekazuje wynik do natywnej listy aktualizacji Home Assistanta bez funkcji instalowania. Sprawdzenie działa także po zamknięciu panelu i nie zależy od pracy regulatora. **Sprawdź aktualizacje** pozwala wywołać je wcześniej, z co najmniej 60 s przerwy i obsługą limitów GitHub.

Marketplace ma odrębną listę wersji: repozytoria dodane z linku zwykle co 48 h, katalog co 6 h. Gdy administrator otworzy panel EMS i jest potwierdzone nowe wydanie, panel może sam odświeżyć metadane wyłącznie naszego repozytorium przez oficjalny protokół sklepu. Żądania są deduplikowane, mają ograniczone ponowienia i nie instalują plików. Brak uprawnień lub niedostępność sklepu nie blokuje sterowania. Przy zamkniętym panelu ten etap czeka na jego otwarcie; własna encja update nadal powiadamia o wydaniu. Starsza wersja EMS wymaga jednorazowego zainstalowania 2.1.0, aby uzyskać ten mechanizm.

**Otwórz Marketplace** prowadzi do sklepu bieżącej instancji. Instalacja pozostaje jawną czynnością użytkownika. Przed nią zachowaj kopię ustawień bez danych dostępu i poprzednie wydanie. Zachowaj istniejący tryb przy zwykłej aktualizacji; jeśli przechodzisz do obserwacji w celu zmiany konfiguracji, potwierdź odczyty wyłączenia doładowania. Po instalacji sprawdź konfigurację, wykonaj wymagany restart i zweryfikuj pomiary, ustawienia i plan przed wznowieniem dotychczasowego trybu.

Przycisk **Odśwież interfejs** pobiera nowszą wersję otwartej karty; przy niezapisanych formularzach jest zablokowany. Nie zastępuje restartu backendu. Samo sprawdzanie wersji nie zmienia trybu EMS i nie uruchamia restartu ani instalacji.

## Automatyczna moc ładowania

Nie wpisuje się już „Modelowego limitu ładowania”. Prognoza korzysta z ogólnego limitu prądu Deye, BMS, napięcia baterii i mocy falownika, ze wspólnym budżetem dla PV i sieci. Dla sieci dodatkowo obowiązują Deye−5%, zakres nastawy i dostępna moc. Przypisania niezależnego limitu Deye i sterowanej nastawy GRID pozostają rozdzielone. Dawna encja modelowego limitu jest wyłączana z zachowaniem historii; ustawienie modelowego rozładowania pozostaje osobne.

## Priorytet PV w bieżącym sterowaniu

Istniejące przypisania **battery_power** i natywnego **grid_power** oraz faz GRID służą do oszacowania nadwyżki lokalnej pomniejszającej potrzebę ładowania z sieci. Bateria ma znak minus podczas ładowania; port GRID ma znak plus przy dopływie do falownika. Nie przypisuj CT zamiast portu GRID ani jednej encji do obu pomiarów. Wymagane są niezależne, poprawne odczyty W do 30 s, rozbieżne czasowo najwyżej o 20 s. Brak poprawnych danych blokuje ładowanie sieciowe zamiast przyjmować PV równe zero.

Panel pokazuje zachowawczy szacunek nadwyżki i potrzebę doładowania po stronie baterii. Nie są to odczyty dokładnej produkcji PV ani AC importu. Pokrycie potrzeby przez PV może zatrzymać doładowanie bez osiągnięcia celu SoC; wznowienie respektuje odstęp właściwy dla bieżącego trybu oraz stabilizację pomiarów. Fizyczne ładowanie z PV pozostaje sterowane przez falownik.

## Redukcje ochronne i diagnostyka poleceń

Redukcja ochronna nie zwiększa wcześniejszego niższego żądania w reakcji na opóźnione echo HA. Dodatnie redukcje są zaokrąglane w dół do 5 A, z zachowaniem dopuszczalnej całkowitej nastawy 1–4 A, zaokrąglonej w dół przy limicie poniżej 5 A. Przyjęte powtórzenie tej samej redukcji nie rozpoczyna od nowa maksymalnego 30 s oczekiwania na odczyt. Jeżeli potrzebne jest surowsze zero, nie czeka ono na ten termin. Nie wymaga to zmiany firmware ani przypisań.

Rozwiń **Ustawienia zaawansowane i szczegóły → Zapisy do falownika**. Sekcja tylko do odczytu pokazuje czas od uruchomienia, liczniki oraz pięć najnowszych prób; nie dodaje przycisków sterujących ani osobnych żądań przy renderowaniu.

Pobrana diagnostyka udostępnia `data.command_diagnostics`: ostatnie 20 prób zmiany limitu prądu ładowania z sieci, liczniki wyników oraz oddzielne pominięcia i ostatni odczyt. Ten prywatny ślad jest przechowywany w RAM od bieżącego uruchomienia; po restarcie zaczyna się od nowa. Nie jest pełną ani odtworzoną wstecz historią instalacji. `accepted` oznacza przyjęcie wywołania usługi HA, a nie potwierdzenie nastawy przez urządzenie lub fizyczne ładowanie. Odczyt nastawy i pomiary mocy należy sprawdzać oddzielnie. Sam wykres encji HA może przedstawiać echo integracji źródłowej i nie dowodzi wykonania tylu zapisów Modbus. Nie publikuj eksportu diagnostyki zawierającego dane swojej instalacji.

## Rezerwa SoC — dolna granica z Battery low SOC

Minimalną rezerwę EMS można ustawić od aktualnej nastawy `number.deye_inverter_battery_low_soc` powiększonej o5punktów procentowych do90%. To bieżąca wartość progu falownika, a nie atrybut `min` encji. Przykład: Battery low SOC10% → rezerwa EMS od15%. Ułamkowy próg jest zaokrąglany w górę do pełnego procenta. Domyślna rezerwa EMS pozostaje40%, ale nie jest już dolnym limitem formularza.

Encja jest wybierana wŹródłach i obsługiwana przez prefiksDeye. Limit obowiązuje w panelu, konfiguracji HA, encji liczbowej, walidacji backendu, planowaniu i nastawach TOU. Zwiększenie progu falownika automatycznie podnosi skuteczną rezerwę ponad niższe zapisane życzenie użytkownika. Nowy cel musi także mieścić rezerwę i bufor do maksymalnego celu ładowania.

Brak, restored, niepoprawna jednostka lub wartość encji blokują zmianę rezerwy i aktywację. Przy utracie odczytu w czasie pracy EMS zeruje ładowanie z sieci i wyłączaGC, nie obniżaTOU i zachowuje konserwatywną poprzednią granicę. Nie zmienia samej nastawy Battery low SOC. Wspierany odczyt0–85% zapewnia miejsce na5p.p. zapasu przy maksymalnej rezerwie90%.

Wybór LOAD/CT jest dostępny bezpośrednio w panelu w sekcji **Pomiar i sterowanie**. Selektor konfiguruje model EMS, a odczyt fizycznego trybu falownika jest pokazany oddzielnie. Zapis wymaga obserwacji i nie zmienia sam nastawy fizycznego trybu falownika. Zmienione opcje uruchamiają sprawdzanie warunków wznowienia; niezgodny tryb sprzętowy blokuje aktywację.

## Ryzyko i diagnostyka planu

Panel pokazuje SoC w P10/P50 przed terminem oraz ewentualny niedobór energii w chronionym oknie. Silnik ocenia osiągalność każdego celu osobno, a panel rozróżnia cel planu i cel używany przez regulator. Podniesienie celu ochronnego na podstawie nieosiągalnego planu wymaga ryzyka wyczerpania rezerwy. Diagnostyka odbiornika podaje dostępne i wykorzystane godziny Recorder oraz zakres osobnego profilu. Problemy telemetrii podczas startu i w czasie pracy są rozróżniane.

Przy doborze osobnych profili zużycia każdy licznik jest sprawdzany osobno. Kanał z brakami pozostaje w zużyciu łącznym. Profile mogą korzystać tylko ze wspólnych godzin, w których ich łączne zużycie mieści się w pomiarze domu.

Widok Lovelace korzysta z natywnego paska i menu Home Assistant. W panelu EMS jego boczne menu prowadzi do sekcji. Pasek przycisków sterowania pozostaje widoczny przy przewijaniu.

Pasek HA pozostaje przy górnej krawędzi podczas przewijania. Przycisk menu steruje natywnym panelem bocznym Home Assistant.

## Deye EMS w natywnym pulpicie Home Assistant

1. W **Ustawienia → Pulpity → Zasoby** dodaj moduł JavaScript o adresie
   `/deye_ems_static/deye-ems-panel.js`. Adres jest stały przy aktualizacjach EMS.
2. Utwórz osobny pulpit administratora i wybierz układ widoku **Panel**.
3. Dodaj jedną kartę ręcznie, z konfiguracją `type: custom:deye-ems-dashboard-card`.

Lewy pasek, tytuł widoku i nawigację pulpitu renderuje Home Assistant. Wewnątrz
karty pozostają menu EMS i tło motywu wybranego w panelu. Dostęp do sterowania wymaga
uprawnień administratora, tak jak w widoku samodzielnym.

Aby wyświetlić natywne zakładki u góry, w edytorze konfiguracji surowej pulpitu użyj wielu widoków:

```yaml
title: Deye EMS
views:
  - title: Przegląd
    path: przeglad
    type: panel
    cards:
      - type: custom:deye-ems-dashboard-card
  - title: Pomiary
    path: pomiary
    type: panel
    cards:
      - type: custom:deye-ems-dashboard-card
        section: meters
  - title: Prognoza
    path: prognoza
    type: panel
    cards:
      - type: custom:deye-ems-dashboard-card
        section: forecast
  - title: Ustawienia
    path: ustawienia
    type: panel
    cards:
      - type: custom:deye-ems-dashboard-card
        section: settings
```

### Otwieranie pulpitu z lewego menu

Aby pozycja „Deye EMS” w lewym menu otwierała kartę z natywnymi zakładkami
pulpitu „Przegląd”, dodaj do tego pulpitu jeden widok:

```yaml
title: Deye EMS
path: deye-ems
type: panel
visible: false
cards:
  - type: custom:deye-ems-dashboard-card
```

Widok jest ukryty w zakładkach podczas przeglądania pozostałych widoków.
Home Assistant może wyświetlić go jako bieżącą zakładkę po otwarciu EMS.
Adres `/deye-ems?standalone=1` otwiera samodzielny panel bez przekierowania.

Stan sterowania i przycisk „Zatrzymaj i obserwuj” pozostają widoczne na półprzezroczystym pasku pod natywnym nagłówkiem HA.

Przejście z bocznego menu przewija do górnej krawędzi sekcji, z odstępem pod paskiem sterowania.
