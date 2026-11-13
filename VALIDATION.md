# Wersja 2.0.2 — katalog SG05LP3-EU-SM2

599 testów Python i 149 testów panelu przeszło lokalnie. Nowe modele nie zmieniają istniejącej konfiguracji ani warunków bezpieczeństwa.

- Dwanaście modeli trójfazowych 3–20 kW zweryfikowanych względem oficjalnych kart producenta; katalog obejmuje 28 modeli LV. Testy kontrolują moce, prądy, przepustowość i warianty wejść baterii.
- Profil SUN-10K-SG05LP3-EU-SM2 dopasowuje górne granice do modelu i zachowuje niższe ograniczenia użytkownika. Migracja nie przełącza automatycznie istniejącej instalacji na nowy model.
- Wersja panelu i informacje instalacyjne są zgodne z wydaniem 2.0.2. Nie zmieniano limitów świeżości ani oprogramowania urządzeń ESPHome. Testy są syntetyczne; nie potwierdzają fizycznej zgodności wszystkich firmware.

# Wersja 2.0.1 — szczegóły pomiarów

597 testów Python i 149 testów panelu przeszło lokalnie. Diagnostyka nie zmienia ograniczeń sterowania.

- Przypisana encja, platforma z rejestru HA, skończona wartość i jednostka, czas raportu, wiek oraz dopuszczalny wiek; brak odczytu nie jest zerem. Dane dostępowe i surowe nieprawidłowe stany nie trafiają do szczegółów.
- Podgląd przyczyn stale/wrong_unit/missing/restored/future/invalid, zduplikowanych przypisań i rozbieżności czasowej grupy mocy; obsługa pomiarów jednofazowych oraz faz CT. Dotychczasowe telemetry_issues i warunki regulatora pozostają źródłem decyzji.
- Przypadek 175 s przy limicie 120 s, brak czasu/limitu, zero, błędne jednostki i niepoprawne źródła; wskazówki ESPHome wyłącznie dla faktycznej platformy encji.
- Błędne wiersze widoczne od razu, prawidłowe rozwijane lokalnie; wybór i szkice pozostają po odświeżeniu. Stary lub przyszły cały snapshot ukrywa zapisane wcześniej szczegóły. Escapowanie treści i brak żądań sieciowych podczas renderowania.
- Nie wykonywano celowych awarii ani zmian progów bezpieczeństwa na instalacji produkcyjnej.

# Wersja 2.0.0 — modele i praca jednofazowa

588 testów Python i 139 testów panelu przeszło lokalnie. Scenariusze są syntetyczne; nie oznaczają fizycznej walidacji wszystkich modeli i firmware.

- 16 modeli LV i ich oficjalne granice; konfiguracja własna pozostaje zgodna z 1.x. Przypadki nieznanego modelu, niewłaściwej liczby faz, niezgodnego napięcia i niższych limitów użytkownika.
- Jednofazowy GRID/LOAD bez native L2/L3 i bez przełącznika bilansowania; falownik na L2 z pełnym pomiarem trójfazowego CT; jednofazowe CT, aliasy, braki i nieaktualne odczyty.
- Ograniczenia prądu i mocy w regulatorze oraz planerze, PV/BMS/Deye, przeciążenia własnej i obcej fazy, zachowanie dotychczasowego toru trójfazowego.
- Kreator modelu: podgląd, osobne potwierdzenie, obserwacja, anulowanie, nieaktualna odpowiedź i zmieniona konfiguracja; zachowanie szkicu przy odświeżaniu.
- Migracja 1.x zachowuje zapisane dane, źródła, wyłączone odbiorniki, prywatny Solcast, rezerwę, topologię i tryb; ładowanie starej konfiguracji nie zapisuje nowych pól za użytkownika.
- Kalendarz: sezon, weekendy/święta, czas lokalny i stały CET, przedziały przez północ i doby 23/25 h. Oficjalny profil operatora nie steruje sprzętem. Aktualizacja nie zastępuje starego harmonogramu nowym.

Archiwum jest budowane przez build_release.py i porównywane z przetestowanymi źródłami. Sprawdzanie HACS i hassfest odbywa się w CI. Stan publikacji, wersja plików, załadowana wersja HA, przyjęcie polecenia, odczyt rejestru i fizyczna reakcja to osobne etapy.

## Poprzednia walidacja 1.0.21 — adres repozytorium

- **528 testów Python i 121 testów panelu PASS.**
- Odnośniki instalacji, manifest, klient wydań i warunek publikacji wskazują `gaszu/deye-ems`. Testy klienta sprawdzają nowy kanoniczny URL bez przekierowania, a panel generuje odnośniki do wydań nowego repozytorium.
- Zmiana zachowuje domenę `deye_ems`, mapowania źródeł, silnik, regulator oraz limity. Repozytorium zachowuje identyfikator i dotychczasowe wydania.

# Wersja 1.0.20 — czysta instalacja i profile baterii

- **528 testów Python i 121 testów panelu PASS.** Regresje obejmują pustą listę dodatkowych odbiorników, brak automatycznego dziedziczenia pompy, zapisane kanały ON/OFF oraz pojedyncze liczenie LOAD.
- Sprawdzono domyślne natywne źródła Deye, opcjonalny YamBMS i własne mapowania, migrację starszych przypisań, podgląd prefiksu oraz osobny zapis. Puste selektory są pomijane zgodnie z walidacją HA i świadomie wyłączają źródło przy końcowym zapisie.
- Bieżący limit BMS, limit zero, alarm, błąd oraz brak/nieprawidłowość odczytów Deye testowano offline. Zachowano pierwszeństwo wcześniejszej numerycznej blokady. Nie wymuszano awarii ani reakcji urządzeń na produkcji.
- Test izolowanego budowania ZIP sprawdza widoczny komunikat o lewym menu na pierwszym ekranie, błędnym formularzu i po utworzeniu wpisu oraz kompletność tłumaczeń polskich i angielskich.

# Wersja 1.0.19 — przygotowanie katalogowe

- Wymagane kontrole katalogowe HACS i hassfest są uruchamiane bez pomijania sprawdzeń. Workflow wydania czeka na ich sukces przed utworzeniem nowego GitHub Release.
- Dodano lokalne, oryginalne ikony baterii i słońca w rozmiarach 256 i 512 px, z wariantem jasnym i ciemnym. Manifest ma kolejność wymaganą przez hassfest.
- Zmiany dotyczą opakowania i metadanych. Silnik i regulator zachowują kod z 1.0.18; ustawienia produkcyjne pozostają konfigurowane przez użytkownika.

# Wersja 1.0.18 — stan doładowania i diagnostyka oczekiwania

- **506 testów Python i 112 testów panelu PASS.** Dziewięć nowych testów backendu obejmuje pierwszy start, zwykły termin korekty, stabilność pomiarów, oczekujący odczyt, blokady ponowień, granicę okna, stan GC i kontrolowane przyczyny błędów pomiarów.
- Dziesięć nowych testów panelu rozdziela GC i nastawę od rzeczywistego przepływu energii; sprawdza zero, brak potwierdzenia, nieaktualne dane, obserwację, pierwszeństwo ochron, czas w Europe/Warsaw i brak wymyślonego terminu lub surowych komunikatów dostawcy.
- Diagnostyka jest odczytem istniejących warunków. Testy awarii wykonano offline. Nie zmieniano rezerwy, topologii, limitów ani decyzji regulatora i nie wymuszano reakcji falownika na produkcji.

# Wersja 1.0.17 — aktualizacje i pierwszy start w tanim oknie

- **497 testów Python i 102 testy panelu PASS.** Niezależne sprawdzenia sekcji aktualizacji potwierdziły102testy panelu,19WebSocket i11instalacji.
- Jedenaście nowych testów klienta wydań sprawdza brak HTTP podczas odczytu i startu, wersje, pojedyncze współdzielone pobranie, anulowanie, limit czasu i64KiB, przerwę między próbami, limity GitHub, uszkodzone odpowiedzi i brak ujawniania treści dostawcy. Publiczne API sprawdzono również z rzeczywistymi nagłówkami klienta: odpowiedź200.
- Pięć nowych testów WebSocket potwierdza admin-only przed planowaniem zadania, działanie przy aktywnym EMS bez usług urządzeń, odczyt zapisanych danych i bezpieczne błędy. Jedenaście nowych testów panelu obejmuje różnice wersji, brak/błąd/stary wynik, bezpieczne odnośniki, ochronę niezapisanych formularzy oraz zatrzymanie EMS i zmiany konfiguracji podczas oczekującego sprawdzenia.
- Piętnaście nowych testów pierwszego startu obejmuje pominiętą granicę czasu,120s stabilnych pomiarów, zapamiętaną zgodę całego okna, PV i restart, niepewny dziennik, niewysłanie, zmianę BMS/PV/taryfy/nastawy po Store oraz jednorazową jawną aktywację przy migracji. Zwykłe późniejsze korekty nadal respektują :00/:30.
- Awarie i reakcje urządzeń symulowano offline. Sprawdzenie dostępnej wersji nie jest instalacją, restartem, przejęciem sterowania ani potwierdzeniem fizycznego ładowania. Wersja backendu oznacza załadowany moduł, a nie same pliki czekające na restart.

# Wersja 1.0.16 — PV w bieżącej regulacji prądu

- **466 testów Python i 91 testów panelu PASS.** Niezależna próba 74 testów regulatora i granicy runtime przeszła poprawnie.
- Osiemnaście nowych scenariuszy regulatora obejmuje noc bez PV, częściowe i pełne pokrycie potrzeby ładowania, bypass LOAD, zewnętrzny odbiór 25 kW, niezależność od CT i nastawy, brak danych, tolerancje 200 W, łączne przeciążenie baterii, priorytet powodów ochronnych, odzyskiwanie rezerwy oraz harmonogram i zatrzask SoC.
- Jedenaście testów runtime sprawdza jednostki, restored, przyszłe i stare odczyty, granice 30 s i 10 s, aliasy źródeł, prawidłowe zero, rozdzielenie CT i portu GRID oraz zachowanie rejestru prób. Wzrost PV podczas zapisu Store blokuje nieaktualne zwiększenie prądu i włączenie GC. Sterowanie nie odpytuje Solcast ani historii.
- Pięć nowych testów panelu obejmuje dane tylko do odczytu, poprawne zero, brak/błąd/stary odczyt oraz rozdzielenie danych serwera od surowych encji, CT i nastawy. Moc jest opisana jako szacunek po stronie baterii.
- Dwie wcześniejsze próby utraty ACK zachowują pierwotne sprawdzenia; ich początkowy SoC zapewnia rzeczywistą potrzebę przygotowanej nastawy również po dodaniu kontroli ostatniej chwili.
- Testy awarii wykonano offline. Szacunek PV jest zachowawczy; bieżący wkład nie gwarantuje produkcji do końca slotu. Nie wymuszano produkcji PV, przeciążenia ani reakcji sprzętu na produkcji.

# Wersja 1.0.15 — sprzętowy budżet ładowania w prognozie

- **437 testów Python i 86 testów panelu PASS.** Niezależna pełna próba Python potwierdziła 437/437 PASS, a niezależne sprawdzenie panelu 86/86 PASS.
- Dziewięć nowych testów planera sprawdza ignorowanie dawnego limitu 5,3 kW, niezależne limity baterii i sieci, napięcie, moc falownika, brakujące/błędne dane, rzeczywiste zero, wspólny budżet PV i sieci, bilans energii i zachowanie chronionych okien. Nieprawidłowy limit nie podnosi skonfigurowanego maksymalnego SoC w fallbacku.
- Osiem nowych testów runtime sprawdza aktualne ograniczenia odczytane po wolnym pobraniu prognozy, dokładny ogólny limit Deye względem zaokrąglonego limitu sieci, blokadę BMS, utratę pomiarów, błędne mapowania i metadane, ignorowanie dawnej opcji oraz zachowanie pojemności i rezerwy. Sprawności AC/DC i magazynowania przekazane planerowi odpowiadają regulatorowi.
- Testy interfejsu obejmują wyłączenie wyłącznie własnych dawnych encji number bez usuwania historii, zachowanie wcześniejszych decyzji użytkownika i brak starego pola mimo obecności dawnej opcji w konfiguracji. Parametr rozładowania pozostaje dostępny.
- Scenariusze awarii i przekroczeń wykonano offline. Model używa prognozowanego zużycia i aktualnego limitu sprzętowego; nie przewiduje zmian BMS na 48 godzin ani rzeczywistego przyszłego obciążenia faz. Testy nie potwierdzają fizycznej reakcji falownika.

# Wersja 1.0.14 — stała sekcja układu instalacji

- **419 testów Python i 85 testów panelu PASS.** Niezależny przegląd ponownie uruchomił wszystkie 85 testów panelu.
- Osiem nowych scenariuszy panelu obejmuje stałą widoczność obu układów, zapisany wybór zamiast szkicu, niezgodny snapshot, nieznaną konfigurację, stare i nieprawidłowe odczyty, zachowanie rzeczywistego zera oraz nieobliczany bilans poza LOAD.
- Sprawdzono osobno odczyt trybu falownika, niezgodność z zapisaną topologią, brak aktualnego odczytu i bezpieczne wyświetlanie błędu bilansu. Surowy kod błędu nie jest treścią ostrzeżenia.
- Podgląd przeglądarki na danych syntetycznych potwierdził sekcję LOAD w jasnym motywie i LOAD i CT w ciemnym. Testy nie zmieniały topologii produkcyjnej ani parametrów sterowania i nie potwierdzają fizycznej reakcji falownika.

# Wersja 1.0.13 — dynamiczny limit i port GRID

- **419 testów Python i77 testów panelu PASS.** Dodano12scenariuszy pure,17runtime,6planera,3interfejsu encji i2panelu. Pozostałe scenariusze zachowują regresje harmonogramu, histerezy, trwałego rejestru i sterowania GC.
- Sprawdzono przekroczenie dawnego108A przy poprawnym limicie, niezależne ograniczenia Deye/BMS/zakresu encji, nieprawidłowe odczyty i metadane, stare ustawienie przy bieżącej komunikacji, utratę pomiarów oraz błędne przypisanie limitu do sterowanego wyjścia.
- Ograniczenie portu GRID działa przy wolnym przyłączu CT, w przeciążeniu jednej fazy, przed włączeniem GC i po zmianie limitu podczas zapisu Store. Testy obejmują też oczekującą wyższą nastawę i brak fikcyjnego potwierdzenia przez przyjęcie usługi.
- Dodatkowe regresje runtime i planera potwierdzają25kWgałęzi między CT a GRID:12kWz falownika oraz13kWbezpośrednio z sieci w chronionym slocie przy odpowiednim przyłączu. GC pozostaje OFF, import CT jest prawidłowy, a zużycie nie jest obcinane do mocy falownika.
- Losowe300zestawów limitów potwierdza nieprzekraczanie limitów prądu i proaktywnego budżetu portu. Przeliczenia napięcia/sprawności testowane są oddzielnie; modelowy parametr mocy ładowania jest zachowany.
- Migracja wyłącza tylko własną dawną encję number, nie usuwa jej historii i zachowuje wcześniejsze wyłączenie użytkownika. Sensor i panel pokazują brak danych zamiast108A lub fikcyjnego zera.
- Testy awarii wykonano offline z atrapami usług. Nie wywoływano przeciążenia ani błędu BMS na produkcji. Sprawdzenia oprogramowania nie potwierdzają fizycznej reakcji falownika.

# Wersja 1.0.12 — komunikat instalacyjny

- 381 testów Python i75 testów panelu PASS. Istniejące sprawdzenia obejmują pierwszy krok konfiguracji, rejestrację panelu z dostępem administratora oraz zgodność wersji panelu z integracją.
- Zbudowana paczka zawiera identyczny wyróżniony komunikat o pasku bocznym w `strings.json` i `translations/pl.json`. Źródłem treści jest generator `build_release.py`, więc kolejne budowanie jej nie usuwa.
- Poprawka zmienia opis kreatora i dokumentację. Nie zmienia sterowania ani zapisanych preferencji widoczności panelu.

# Wersja 1.0.11 — licznik API Solcast

- **381 testów Python i 75 testów panelu PASS.** Trzy testy statusu sprawdzają rozróżnienie włączonego/wyłączonego/nieskonfigurowanego klienta, brak klucza w statusie, zachowanie rejestru i brak dodatkowych HTTP oraz usług urządzeń przy odczycie.
- Siedem testów interfejsu obejmuje widoczność kart, aktualny limit i pozostałe próby, rzeczywiste zero, przekroczenie limitu, błędy API z prawidłowym licznikiem, uszkodzone lub brakujące dane, stary odczyt i inną dobę UTC. Reset jest formatowany w Europe/Warsaw, z godziną01 zimą i02 latem.
- Licznik dotyczy lokalnie zarejestrowanych prób klienta EMS, wraz z importem i błędami. Testy nie potwierdzają stanu wykorzystania całego konta Solcast przez inne aplikacje ani fizycznej reakcji falownika. Regulator i polityka zapytań nie zostały zmienione.

# Wersja 1.0.9 — sprawdzenia offline

- 378 testów Python i 68 testów panelu PASS. Limit przyłącza 16 kW przy falowniku 10 kW jest zapisywany i przekazywany do regulatora oraz planera; ograniczenie mocy falownika pozostaje niezależne. Porównanie CT przy 14 kW potwierdza różną decyzję dla przyłącza 10 i 16 kW.
- Edycja limitu łącznego i fazowego jest widoczna w głównym panelu w LOAD i CT, bez duplikowania pól.

# Wersja 1.0.8 — sprawdzenia offline

- 376 testów Python i 67 testów panelu PASS. Regresje obejmują tekstową wartość CT w schemacie WebSocket, odrzucenie obiektu jako wartości, trwały zapis i przeładowanie modelu CT oraz aktywację z poprawnymi pomiarami syntetycznymi.
- Panel odróżnia niezapisany szkic CT od zapisanego LOAD po błędzie oraz pokazuje zapisane CT po poprawnej odpowiedzi API.
- Sprawdzenia offline nie są potwierdzeniem instalacji ani fizycznej reakcji falownika.

# Wersja 1.0.7 — sprawdzenia offline

- 373 testy Python PASS i65 testów panelu PASS; paczkaZIP zbudowana i sprawdzona, w tym16 scenariuszy harmonogramu, histerezy i integracji runtime. Dawne testy modułu rampy zachowano jako regresje wspólnej ścieżki bezpieczeństwa; runtime używa nowej polityki półgodzinnej.
- Osiem testów dynamicznej rezerwy obejmuje zapis15%/odrzucenie14% przyLowSOC10%, wzrost skutecznej granicy iTOU, przekazanie jej do regulatora i planera, utratę odczytu i blokadę aktywacji, zachowanie poprzedniej granicy, natywne formularze, ułamkowy próg i prefiks oraz walidację solvera. Dwa testy panelu sprawdzają zmianę HTMLmin i blokadę przy braku odczytu.
- Dziesięć testów topologiiCT obejmujeCT=0 z eksportem portuGRID doCWU, poprawny import, jawny wybór trybu, braki/starość/restored/jednostki/kierunki i przesunięcie czasowe pomiarów, fazowe ukrycie ujemnego bilansu, profil pełnego zużycia z historii i brak samegoLOAD jako zastępstwa, unieważnienie kontekstu, wspólny limit10kW oraz blokadę zmian wactive. Test panelu odróżniaCT0 odGRID−2kW i pełnego obciążenia5kW.
- Siedem nowych testów prefiksu: generowanie nazw z zachowaniem domen, walidacja wejścia, podgląd bez zapisu, ręczna korekta i zachowanie innych źródeł, ponowna blokada przy aktywacji, pierwsza konfiguracja i komunikaty błędnych wartości.
- Cztery nowe testy diagnostyki aktywacji sprawdzają wszystkie wymagane tryby, łączne raportowanie braku encji i stanów restored/unavailable, mapowanie innej instancji oraz brak poleceń przy blokadzie.
- Pięć nowych testów panelu bocznego: trwałość preferencji i zachowanie motywu, odrzucenie błędnego zapisu, formularz przy aktywnym sterowaniu bez zmiany options, brak odświeżenia po błędzie zapisu oraz zachowanie trasy i bramki administratora przy ukryciu wpisu.
- Testy granic pierwszej minuty :00/:30, braku narastających ponowień, kwantyzacji i martwej strefy, natychmiastowej ochrony, restartu i trwałości zatrzasku SoC.
- Atrapy HA i usług oraz syntetyczne pomiary nie dowodzą reakcji fizycznego falownika. Nie wdrożono tego kandydata do HA.

# Sprawdzenia wersji 1.0.6

- **322/322 testów Python PASS** i **60/60 testów panelu PASS**.
- Zwykłe polecenia prądu respektują600s od każdej możliwej wysłanej nastawy, próg5A i krok20A. Testy obejmują bezpieczny start poniżej5A, brak nowego kroku przy opóźnionym odczycie oraz wznowienie po redukcji ochronnej.
- Testy trwałego rejestru rozróżniają pewne niewysłanie, transport o niepewnym wyniku i przyjęcie usługi. Sprawdzono60s po pewnej niewysłanej próbie bez kasowania wcześniejszej600s przerwy, odtworzenie przygotowanej próby po restarcie, stare metadane oraz zapis trwający dłużej niż600s.
- Zapas GRID jest ponownie sprawdzany po zapisie Store, bezpośrednio przed usługą. Scenariusze obejmują zmianę obciążenia, obcy znacznik próby, pełny zapas wymagany do GC ON i zmniejszenie zbyt wysokiej nastawy przed włączeniem ładowania.
- Możliwa wcześniejsza wyższa nastawa pozostaje ryzykiem po niższym poleceniu o wyniku accepted/uncertain/not_sent, aż do świeżego zgodnego odczytu. Przyjęcie usługi nadal nie oznacza potwierdzenia sprzętu.
- Przechodzą wcześniejsze regresje nieodnawialnego30s oczekiwania na bezpieczną redukcję, BMS, GRID, świeżości, własności sterowania i okien chronionych. Testy używają syntetycznych pomiarów i atrap usług; nie potwierdzają fizycznej reakcji falownika.

## Sprawdzenia wersji 1.0.5

- **289/289 testów Python PASS** i **60/60 testów panelu PASS**.
- Preferencja wyglądu ma osobny Store. Testy obejmują walidację dostępnych nazw motywów, admin-only WebSocket, trwały zapis przed publikacją, błąd zapisu bez zmiany wartości oraz serializację równoległych zapisów. Błąd odczytu kosmetycznej preferencji nie blokuje startu sterownika.
- Zapis wyglądu w active nie wywołuje koordynatora, przeładowania, planowania ani usług urządzeń. Konfiguracja energii i połączenia Solcast pozostaje oddzielona.
- Testy interfejsu obejmują lokalny CSSOM hosta, base i reguły trybu light/dark, odwołania zmiennych, wartości RGB, usuwanie starych kluczy i powrót do dziedziczenia profilu. Brak motywu nie powoduje automatycznego zapisu innej preferencji.
- Sprawdzono zachowanie wyboru przy odświeżaniu, bezpieczne wyświetlanie nazw motywów i zachowanie poprzedniego wyglądu po błędzie zapisu. Kod nie zmienia motywu dokumentu ani globalnego profilu HA.
- W przeglądarce na syntetycznych danych sprawdzono zastosowanie motywu z obrazem tła i półprzezroczystymi kartami, zapis innego motywu w jasnym trybie, usunięcie lokalnych zmiennych przy powrocie do dziedziczenia oraz ponowne zastosowanie wybranego motywu. Kolory podglądu pochodzą z definicji motywu, bez własnego przemalowywania.

## Sprawdzenia wersji 1.0.4

Wyniki dotyczą testów oprogramowania offline i syntetycznych scenariuszy przeglądarkowych. Nie stanowią raportu z konkretnej instalacji HA ani potwierdzenia fizycznej reakcji falownika.

## Wyniki

- **279/279 testów Python PASS**.
- **48/48 testów panelu PASS**.
- Podgląd i obsługa przeglądarki zostały sprawdzone na danych syntetycznych, bez połączenia z produkcyjnym HA i bez użycia rzeczywistego konta Solcast.

Testy runtime zastępują framework HA na granicy API, wykonując rzeczywiste funkcje planera, regulatora i obsługi stanu. HTTP Solcast i usługi HA są atrapami; nie potwierdzają wykonania polecenia przez sprzęt.

## Kreator Solcast

Sprawdzono natywny options flow, menu, formularze i ograniczenia schematów selectorów. Panel korzysta z POST/DELETE kreatora HA, a zapis konfiguracji pozostaje w options flow integracji.

Scenariusze obejmują:

- Otwarcie i anulowanie bez przełączenia źródła; usunięcie niezakończonego flow po anulowaniu, odłączeniu panelu i spóźnionej odpowiedzi.
- Zapis ręczny włączający klienta API oraz osobne potwierdzenie jego wyłączenia.
- Zachowanie szkicu po błędzie walidacji, kompletność pól i obsługę importu kalibracji.
- Brak zapisanego klucza w formularzu i publicznym statusie; prywatną, nietrwałą pamięć nowego klucza oraz czyszczenie jej po zakończeniu lub zamknięciu.
- Brak klucza w HTML `value`, planie, cache i diagnostyce.
- Blokadę anulowania podczas końcowego zapisu i brak automatycznego włączenia sterowania. Stary poprawny plan sprzed zapisu nie odblokowuje przycisku wznowienia.
- Utrwalanie wykorzystania API przed HTTP, rozliczanie doby UTC, błędy API i zachowanie wykorzystania po restarcie lub zmianie konfiguracji.
- Import 24/48 współczynników, wartości zerowych, wykluczeń i pierwszeństwa tabeli globalnej; odrzucanie niepełnej kalibracji.
- Snapshot kalibracji bez migracji dalszego samouczenia i bez automatycznego zatrzymywania innego klienta. Korekty dotyczą tylko surowych odpowiedzi API EMS.

Kontrakt interfejsów porównano z [HA Core 2026.11 — config entries](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/config/config_entries.py) i [data entry flow](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/helpers/data_entry_flow.py). Zasady zewnętrznego API opisuje [dokumentacja Solcast](https://docs.solcast.com.au/docs/section/rooftop-sites-hobbyist).

## Silnik i regulator

Testy obejmują bilans energii, cele sezonowe, datowany cache, profil LOAD, liczniki slotów, warunki fallbacku oraz ograniczenia baterii i falownika. Sprawdzają świeżość i jednostki pomiarów, BMS, faktyczne limity GRID, rozdzielenie limitów importu od mocy konwersji i wybór modelu fazowego na podstawie potwierdzonych ustawień.

Regresje bezpiecznej redukcji obejmują opóźniony odczyt, zmianę limitu podczas zapisu, nieudaną usługę lub zapis, brak dowodu przyjęcia, nieodnawialny limit 30 s, wzrost odczytu, utratę wymaganej flagi, BMS, GRID, stare pomiary, konflikt właściciela i okno chronione. Rejestr próby, przyjęcie usługi i odczyt urządzenia mają osobne znaczenie.

Sprawdzono również, że opóźnione pobieranie prognozy nie blokuje bieżącej regulacji, a wynik planowania nie jest przyjmowany po zmianie jego konfiguracji.

## Odbiorniki, panel i instalacja

Testy dodatkowych zużyć obejmują tworzenie, edycję, usuwanie, trwałe ON/OFF, zachowanie identyfikatorów, walidację jednostek, konflikt wersji listy oraz blokadę zmian w active. Kanały są używane wyłącznie w prognozie SoC i nie podwajają bieżącego LOAD.

Testy panelu obejmują zachowanie szkiców, wyścigi odpowiedzi, zmiany trybu podczas edycji, obsługę błędów, brak fikcyjnych zer i ochronę przed wstawieniem kodu HTML. Podgląd przeglądarki obejmuje kreator Solcast, kalibrację, jawne przejście do obserwacji, osobne wznowienie i potwierdzenie wyłączenia. Pastelowa kolorystyka wykorzystuje zmienne motywu HA; sprawdzono również ciemny podgląd.

Sprawdzenia struktury obejmują platformy integracji, manifest, zgodność wersji panelu, konfigurację WebSocket z autoryzacją administratora oraz strukturę paczki. Specyfikacja silnika pozostaje **1.0.0**; wydanie 1.0.4 dotyczy kreatora i wyglądu panelu.

## Powtórzenie testów

```shell
python -m unittest discover -s tests -q
node tests/test_frontend.cjs
python build_release.py
```

Pełne warunki działania opisuje [SPECIFICATION.md](SPECIFICATION.md), instalację [INSTALL.md](INSTALL.md), a zasady przejścia i powrotu [MIGRATION.md](MIGRATION.md). Wynik testów syntetycznych nie zastępuje sprawdzenia własnych mapowań, pomiarów i reakcji urządzenia.

Dodatkowy test API potwierdza przekazanie trzech jawnych pól dynamicznej rezerwy bez prywatnych opcji. Dwa testy selektora LOAD/CT w panelu sprawdzają zapis tylko po przycisku oraz blokadę zapisu wactive.
