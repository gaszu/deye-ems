# Przejście z innego EMS i powrót z kopii

## Przejście na 2.1.9

Zachowaj kopię konfiguracji bez danych dostępu oraz ZIP 2.1.8. Sprawdź konfigurację HA, zatrzymaj sterowanie i potwierdź odczyt 0 A oraz wyłączone GC przed wymaganym restartem. Po uruchomieniu sprawdź wersję, pomiary, dotychczasowe przypisania, rezerwę, zegary i topologię; przywróć wcześniejszy tryb po spełnieniu warunków. W razie problemu zatrzymaj sterowanie, przywróć pliki 2.1.8, wykonaj jeden kontrolowany restart i ponownie sprawdź warunki przed wznowieniem. Cofnięcie plików nie cofa historii ani ustawień.

## Przejście na 2.1.7

Wydanie poprawia wyłącznie mylący podpis czterech dostępnych taryf TAURON. Nie wymaga zmiany ustawień ani ponownego wyboru taryfy. Zachowaj kopię bez danych dostępu i ZIP 2.1.6, sprawdź konfigurację, wykonaj wymagany restart i zweryfikuj załadowaną wersję, dotychczasowy tryb oraz ustawienia. Powrót do 2.1.6 przywraca poprzedni podpis; reguły silnika pozostają takie same.

## Przejście na 2.1.6

Nowy wybór w instalatorze i panelu obejmuje tylko TAURON G11, G13, G12w i G12, ze stałym operatorem. Istniejąca konfiguracja innego operatora lub własna nie jest automatycznie zamieniana na TAURON; otwarcie i anulowanie szkicu nie zapisują opcji ani nie zmieniają trybu. Wybór innego nowego profilu jest obecnie niedostępny.

TAURON korzysta ze stałych godzin sezonowego szablonu TOU. Dni wolne zmieniają strefy i flagi zgody na ładowanie, nie godziny wpisów. Karty w widoku lokalnego zegara zachowują sześć przedziałów również w całodobowo tanim dniu. Wszystkie korzystają z istniejących terminów planu, bez tworzenia sześciu nowych celów. Zapisany zegar i podstawa sezonu pozostają wymagane; nie utożsamiaj każdego początku wpisu z granicą strefy cenowej.

Przed aktualizacją zachowaj prywatną kopię ustawień i runtime bez danych dostępu, dotychczasowe odczyty godzin/flag TOU oraz ZIP 2.1.5. Po instalacji sprawdź konfigurację, wymagany restart i rzeczywiście załadowaną wersję silnika oraz panelu. Osobno zweryfikuj sześć odczytanych godzin i ich flagi, zegar, taryfę, źródła, rezerwę, pomiary, plan i tryb. Podgląd przygotowanego programu nie jest dowodem odczytu nastaw ani fizycznego ładowania. Zmiana godzin nadal podlega wyłączeniu ładowania i dotychczasowym potwierdzeniom.

**Powrót do 2.1.5:** zachowaj wpis konfiguracji i runtime, zainstaluj poprzedni ZIP, sprawdź konfigurację i uruchom HA ponownie. Wraca wcześniejszy sposób kompilacji programu, więc sam powrót plików nie dowodzi przywrócenia wcześniejszych godzin urządzenia. Porównaj rzeczywiste odczyty z zachowaną kopią i zweryfikuj flagi, źródła, rezerwę, pomiary oraz tryb. Nie obniżaj zabezpieczeń ani nie usuwaj historii poleceń w celu wymuszenia startu.

## Przejście na 2.1.5

Aktualizacja poprawia łańcuch ochronnych redukcji i jego oczekiwanie na odczyt. Opóźniony stan HA nie może podnieść wcześniejszego niższego żądania; dodatnia redukcja jest zaokrąglana w dół do 5 A, z dopuszczeniem całkowitej nastawy 1–4 A, zaokrąglonej w dół przy limicie poniżej 5 A. Ponowienie tej samej przyjętej redukcji nie odnawia maksymalnego 30 s oczekiwania. Wymagane surowsze zero zachowuje pierwszeństwo. Zwykły odstęp 600 s, stabilizacja 120 s, BMS, zgoda GC i walidacja pomiarów pozostają skuteczne.

Zachowaj prywatną kopię ustawień i runtime bez danych dostępu oraz ZIP 2.1.4. Po instalacji sprawdź konfigurację, wymagany restart, rzeczywiście załadowaną wersję silnika i panelu, oryginalne ustawienia oraz tryb pracy. Prywatny ślad `data.command_diagnostics` obejmuje ostatnie 20 prób i liczniki w RAM od bieżącego uruchomienia; restart zeruje go i nie odtwarza wcześniejszych poleceń. Zapisz potrzebną diagnostykę prywatnie przed restartem. Przyjęcie usługi, odczyt nastawy i fizyczny przepływ sprawdzaj oddzielnie. Nie wyciągaj liczby zapisów z samego wykresu encji HA i nie publikuj eksportu danych instalacji.

**Powrót do 2.1.4:** zachowaj wpis i runtime, zainstaluj poprzedni ZIP, sprawdź konfigurację i uruchom HA ponownie. Wróci poprzednia obsługa ochronnej redukcji; nowy ślad diagnostyczny może być niedostępny w starszej wersji, więc zachowaj potrzebny eksport prywatnie przed powrotem. Zweryfikuj źródła, nastawy, pomiary, plan i tryb. Nie usuwaj historii poleceń ani nie zmieniaj ograniczeń w celu wymuszenia ładowania.

## Przejście na 2.1.4

Aktualizacja zastępuje bramkę pierwszej minuty :00/:30 kroczącym minimum 600 s między możliwie wysłanymi zwykłymi dodatnimi nastawami. Dotyczy startu z zera i niezerowych korekt. Redukcje ochronne oraz wyłączenie pozostają natychmiastowe. Uprawnienie pierwszego startu nie jest zwracane ani używane do ominięcia odstępu; aktualne pomiary, odczyt nastawy, stabilność, taryfa, plan i ograniczenia nadal są wymagane.

Zachowaj prywatną kopię ustawień i runtime bez danych dostępu oraz ZIP 2.1.3. Nie usuwaj rejestru poleceń, aby wymusić ładowanie. Przy nieznanej lub niejednoznacznej historii dodatkowe polecenie pozostaje zablokowane; przygotowana próba po awarii jest traktowana zachowawczo jako możliwie wysłana. Po instalacji sprawdź konfigurację, wymagany restart, załadowaną wersję silnika i panelu, oryginalne ustawienia oraz rzeczywisty tryb. Najwcześniejszy termin w panelu nie jest obietnicą uruchomienia; usługę, nastawę i fizyczny przepływ sprawdzaj osobno.

**Powrót do 2.1.3:** zachowaj wpis konfiguracji i runtime, zainstaluj poprzedni ZIP, sprawdź konfigurację i uruchom HA ponownie. Przywrócony zostaje starszy harmonogram :00/:30, więc może powrócić oczekiwanie po przegapionym terminie. Zweryfikuj historię poleceń, źródła, pomiary, plan i tryb przed wznowieniem dotychczasowej pracy. Nie kasuj historii ani nie zmieniaj zabezpieczeń w celu ominięcia blokady.

## Przejście na 2.1.3

Aktualizacja poprawia wyłącznie sposób datowania natywnych raportów ESPHome i odpowiadający mu opis diagnostyki. Najnowszy raport wyznacza wiek bieżącej wartości; starszy raport nadal osobno potwierdza poprawną parę z jednej sesji. Dotychczasowe limity wieku, zgodności czasowej i warunki wznowienia pozostają skuteczne. Po rozłączeniu, zmianie przypisania lub przerwie w raportach przekraczającej limit wieku wymagana jest nowa para; świeży odbiór nie dowodzi chwili pomiaru Modbus ani reakcji falownika.

Zachowaj prywatną kopię ustawień bez danych dostępu oraz ZIP 2.1.2. Aktualizacja zachowuje źródła, taryfę, rezerwę, limity i zapisany tryb. Po instalacji sprawdź konfigurację, wymagany restart, rzeczywiście załadowaną wersję silnika i panelu, oryginalne ustawienia oraz diagnostykę raportów. Potrzebę ładowania, zgodę regulatora, przyjęcie polecenia, nastawę i fizyczny przepływ sprawdzaj osobno.

**Powrót do 2.1.2:** zachowaj wpis konfiguracji i runtime, zainstaluj poprzedni ZIP, sprawdź konfigurację i uruchom HA ponownie. Konfiguracja pozostaje zgodna. Starsza wersja ponownie używa wcześniejszego czasu odbioru również do datowania wartości, więc może wrócić opisana blokada świeżości. Zweryfikuj źródła, pomiary, plan i tryb; nie wymuszaj sterowania przy niespełnionych warunkach.

## Przejście na 2.1.2

Aktualizacja ujednolica kartę sterowania i odnośniki aktualizacji oraz przenosi opis panelu, układ LOAD/CT, sprzęt i aktualizacje do istniejących ustawień zaawansowanych. Zachowaj kopię ustawień bez danych dostępu oraz ZIP 2.1.1. Po instalacji sprawdź konfigurację, wymagany restart, załadowaną wersję silnika i panelu, przypisania, ustawienia oraz dotychczasowy tryb.

**Powrót do 2.1.1:** zachowaj istniejący wpis i dane runtime, zainstaluj poprzedni ZIP, sprawdź konfigurację, uruchom HA ponownie i zweryfikuj wersję oraz tryb. Konfiguracja pozostaje zgodna z 2.1.1.

## Przejście na 2.1.1

Aktualizacja zmienia panel i utrzymanie jego trasy podczas zapisu opcji. Nie wybiera innej taryfy, nie zmienia zegara, rezerwy, źródeł ani limitów i nie zastępuje sprawdzenia trybu po starcie. Zachowaj prywatną kopię ustawień bez danych dostępu i ZIP 2.1.0. Po instalacji sprawdź konfigurację, wykonaj wymagany restart oraz porównaj załadowaną wersję, przypisania i ustawienia. Dotychczasowy tryb przywracaj dopiero po zwykłej kontroli aktualnych pomiarów i planu.

**Powrót do 2.1.0:** zachowaj istniejący wpis konfiguracji i dane runtime, zainstaluj poprzednie pliki przez Marketplace lub z zachowanego ZIP, sprawdź konfigurację i uruchom HA ponownie. Profil taryfy jest zgodny z 2.1.0. Sprawdź wersję, źródła, rezerwę, harmonogram, świeże pomiary i tryb; nie uruchamiaj równolegle drugiego wykonawcy. Sam odczyt nastawy nie dowodzi fizycznej reakcji baterii.

## Przejście na 2.1.0

Przed zmianą zachowaj prywatną kopię ustawień bez danych dostępu, poprzedni ZIP i informacje o trybie oraz wpisach TOU. Zwykła aktualizacja nie wybiera operatora ani nowego harmonogramu: dotychczasowy `legacy_g13`, źródła, limity, rezerwa i topologia pozostają zachowane. Instalacja plików, załadowana wersja i tryb po starcie wymagają osobnego sprawdzenia.

Nowy profil wybieraj dopiero po potwierdzeniu operatora, taryfy, zegara i warunków umowy. Podgląd nie zapisuje ustawień. Po końcowym zapisie kreator zamyka się, a manager HA może sam wznowić sterowanie po kontroli warunków. Ręczny STOP anuluje ten zamiar, również podczas przeładowania. Przy braku potwierdzenia GC OFF / 0 A przeładowanie jest blokowane. Nigdy nie traktuj samego przyjęcia polecenia lub odczytu nastawy jako dowodu fizycznej reakcji baterii.

Po przejściu na profil OSD sprawdź rzeczywiste przedziały dziś/jutro, zegar, terminy celów i oddzielny plan sześciu TOU. Plan zachowawczy musi być jawnie oznaczony; brak danych nie może wyglądać jak prognoza zerowego poboru.

**Powrót do 2.0.4:** najpierw STOP, potwierdzenie odczytów wyłączenia doładowania i brak oczekującego startu. Poprzednie wydanie nie obsługuje nowych taryf. Jeśli wybrano profil operatora, przywróć zgodną kopię konfiguracji i harmonogramu sprzed zmiany, a nie tylko pliki ZIP. Pozostaw obserwację podczas kontroli i restartu. Zweryfikuj źródła, rezerwę, limity, zegar i TOU przed jawnym przywróceniem poprzedniego trybu. Pełna kopia HA sprzed zmiany może służyć odtworzeniu również runtime; nie uruchamiaj starego algorytmu na nowym, nieobsługiwanym harmonogramie.

## Przejście na 2.0.3

Zachowaj kopię ustawień bez danych dostępu i poprzedni ZIP. Aktualizacja zachowuje przypisania, rezerwę, topologię, limity i tryb pracy. Nowe propozycje źródeł jednofazowych zapisujesz oddzielnie w kreatorze w obserwacji. W profilu Deye bez dedykowanego CCL źródłem limitu staje się niezależna nastawa Deye; YamBMS i źródła ręczne zachowują wymagania. Sprawdź opis źródła limitu i alarmy przed włączeniem sterowania.

Po restarcie sprawdź załadowaną wersję, oryginalne ustawienia i diagnostykę raportów. Dodatkowy klient ESPHome nie zmienia firmware. Powrót: obserwacja, poprzedni ZIP, kontrola konfiguracji, restart i weryfikacja. Jeśli zmieniono źródła na nowe jednofazowe statusy tekstowe, starszy kod może ich nie obsługiwać — przywróć również zgodną kopię przypisań i osobno sprawdź możliwość sterowania.

## Przejście na 2.0.0

Instalacja plików nie zmienia przypisań, odbiorników, Solcast, pojemności, SoC, limitów, topologii ani zapisanego trybu pracy. Stare wpisy pozostają profilem własnym trójfazowym. Nowy model/fazy wybierasz osobno w obserwacji; podgląd wymaga potwierdzenia i nie uruchamia automatycznie sterowania. Jednofazowe nowe instalacje nie wymagają pomiarów native L2/L3; sprawdź jednak encje swojego firmware i pomiar CT, jeśli jest używany.

Przed aktualizacją zachowaj prywatną kopię ustawień bez danych dostępu i poprzedni ZIP. Po restarcie zweryfikuj wersję silnika i panelu, źródła, limity, plan i tryb. Powrót: obserwacja, pliki poprzedniego wydania, restart i weryfikacja. Jeżeli po aktualizacji zmieniono model lub liczbę faz, nie uruchamiaj 1.x z konfiguracją jednofazową — przywróć zgodną kopię 1.x albo pozostań w obserwacji. Poprzedni kod nie obsługuje nowych profili.

Instalacja Deye EMS nie wyłącza innych regulatorów. Poniższa procedura jest ogólną instrukcją dla operatora instalacji.

## Aktualizacja adresu repozytorium w 1.0.21

Repozytorium ma stały identyfikator i nowy adres `https://github.com/gaszu/deye-ems`. Zachowaj istniejący wpis integracji, źródła i magazyn runtime; nie instaluj drugiej kopii. Marketplace powinien rozpoznać zmianę przy odświeżeniu informacji. W razie niepowodzenia sprawdź adres i identyfikator repozytorium zamiast usuwać integrację.

Powrót do 1.0.20 wykonuj standardowo: prywatna kopia ustawień, obserwacja i potwierdzone zatrzymanie doładowania sieciowego, instalacja zachowanej paczki, kontrola konfiguracji i sprawdzenie załadowanej wersji, pomiarów oraz planu przed jawnym przywróceniem poprzedniego trybu. Silnik i format ustawień pozostają zgodne.

## Powrót z 1.0.20 do 1.0.19

Zachowaj prywatną kopię ustawień i runtime oraz paczkę 1.0.19. Przejdź do obserwacji, potwierdź zatrzymanie doładowania sieciowego i zainstaluj wcześniejsze wydanie. Sprawdź konfigurację i uruchom HA ponownie. Przed jawnym wznowieniem sterowania sprawdź zapisane źródła, dodatkowych odbiorników, pomiary i plan. Starsze wydanie ma dawne domyślne przypisania pompy dla nowych lub niepełnych konfiguracji, dlatego nie używaj go do czystej instalacji.

## Powrót z 1.0.19 do 1.0.18

Zachowaj prywatną kopię ustawień i runtime oraz paczkę 1.0.18. Przejdź do obserwacji i potwierdź wyłączenie doładowania sieciowego. Zainstaluj 1.0.18, sprawdź konfigurację i uruchom HA ponownie. Po sprawdzeniu ustawień, aktualnych pomiarów i planu jawnie przywróć wcześniejszy tryb. Powrót usuwa lokalne ikony, a silnik, regulator i format zapisanych ustawień pozostają zgodne.

## Powrót z 1.0.18 do 1.0.17

Zachowaj prywatną kopię ustawień i runtime oraz paczkę 1.0.17. Przejdź do obserwacji i potwierdź wyłączenie doładowania z sieci. Zainstaluj 1.0.17, sprawdź konfigurację i uruchom HA ponownie. Po sprawdzeniu ustawień, aktualnych pomiarów i planu jawnie przywróć wcześniejszy tryb. Powrót usuwa dokładniejszy opis oczekiwania i diagnostykę pomiarów; harmonogram, limity oraz trwały znacznik pierwszego startu pozostają zgodne.

## Powrót z 1.0.17 do 1.0.16

Przejdź do obserwacji, potwierdź zatrzymanie doładowania sieciowego, zachowaj prywatną kopię ustawień i runtime oraz paczkę1.0.16. Zainstaluj1.0.16, sprawdź konfigurację i uruchom HA ponownie. Po weryfikacji ustawień, pomiarów i planu jawnie przywróć wcześniejszy tryb. Powrót usuwa sekcję aktualizacji i wyjątek pierwszego startu;1.0.16 znów wymaga zwykłego harmonogramu :00/:30. Nie zmienia mapowań ani parametrów baterii. Starszy kod ignoruje dodatkowy znacznik pierwszego startu.

## Powrót z 1.0.16 do 1.0.15

Zachowaj prywatną kopię ustawień i paczkę 1.0.15. Przejdź do obserwacji, potwierdź zerowy prąd sieciowy i wyłączone GC, zainstaluj 1.0.15, sprawdź konfigurację i uruchom HA ponownie. Wersja 1.0.16 nie zmienia schematu ustawień ani rejestru encji względem 1.0.15. Po sprawdzeniu pomiarów, planu i zachowania ustawień jawnie przywróć wcześniejszy tryb. W 1.0.15 pozostaje dynamiczny model prognozy, a bieżący regulator nie odejmuje jeszcze lokalnej nadwyżki od potrzeby ładowania sieciowego.

## Powrót z 1.0.15 do 1.0.14

Przed aktualizacją zachowaj prywatną kopię ustawień i informację, czy dawna encja number o unique_id kończącym się `_charge_max_kw` była włączona. Wersja 1.0.15 wyłącza ją przez rejestr integracji, ale zachowuje historię i zapisaną wartość opcji.

Aby wrócić, przejdź do obserwacji, sprawdź zerową nastawę prądu sieci i wyłączone Grid Charge, zainstaluj 1.0.14 przez Marketplace, sprawdź konfigurację i uruchom HA ponownie. Jeżeli dawna encja była wcześniej włączona, a aktualizacja wyłączyła ją przez integrację, włącz ponownie wyłącznie tę własną encję w rejestrze HA i przeładuj wpis zgodnie z komunikatem HA. Nie przywracaj encji wyłączonej wcześniej przez użytkownika. Sprawdź ustawienia, pomiary i plan przed jawnym wznowieniem wcześniejszego trybu. W 1.0.14 zapisana wartość `charge_max_kw` ponownie uczestniczy w prognozie.

## Przygotowanie

1. Zapisz odtwarzalną kopię Home Assistant oraz ustawień dotychczasowego EMS. Zachowaj ją prywatnie.
2. Sporządź aktualną listę sterowników, ich wejść, wyjść i zależności. Uwzględnij automatyzacje, aplikacje i zewnętrzne systemy zapisujące nastawy falownika.
3. Dodaj Deye EMS w obserwacji. Wskaż własne encje i sprawdź jednostki, znaki mocy, zakres pomiaru LOAD, daty prognozy oraz limity i rezerwę baterii.
4. Porównaj plan z pomiarami. Brak danych i nieosiągalny cel wymagają wyjaśnienia; nie oznaczają zerowego zużycia lub importu.

## Przejęcie sterowania

Zatrzymaj wszystkich konkurujących wykonawców i ich mechanizmy automatycznego ponownego uruchamiania. Następnie jawnie wybierz sterowanie w Deye EMS. Integracja sprawdza bieżące pomiary, przypisania wyjść, tryby falownika i znanych właścicieli. Nie wyłącza innych regulatorów samoczynnie i nie zastępuje pełnego inwentarza operatora.

Sprawdź oddzielnie wyliczone żądanie, przyjętą próbę polecenia, odczyt rejestru i fizyczny przepływ energii. Zgodność jednego z tych etapów nie potwierdza wszystkich pozostałych ani osiągnięcia przyszłego SoC.

## Usuwanie nieużywanych elementów

Samodzielny Deye EMS nie wymaga helperów lub automatyzacji innego EMS. Przed usunięciem każdego starego elementu sprawdź jego konsumentów i sposób odtworzenia. Zachowaj fizyczne pomiary, integrację falownika i baterii, Recorder oraz wybrane źródła prognozy.

Na czas świadomego usuwania wpisów znanych sterowników wybierz obserwację, gdy dotychczasowi wykonawcy jeszcze istnieją i są wyłączeni. Potwierdź odczyt zerowego prądu ładowania sieciowego i wyłączenie Grid Charge przed zmianami właścicieli. Samo automatyczne wycofanie sterowania po konflikcie nie zeruje nastaw falownika.

Po zakończeniu zmian jawne ponowne przejęcie sprawdza aktualnie istniejących właścicieli. W zwykłej aktywnej pracy zniknięcie zapamiętanego właściciela pozostaje konfliktem.

Jeżeli prognoza pochodzi z encji HA, zachowaj dostarczającą je integrację. Wbudowany klient Solcast jest alternatywą opisaną w [INSTALL.md](INSTALL.md). Przy zmianie klienta zachowaj zużyty budżet API i unikaj równoległego odpytywania jednego konta.

## Restart

Falownik może zachować ostatnie nastawy i harmonogram podczas restartu HA. Wyładowanie integracji nie jest poleceniem zerowania prądu. Po uruchomieniu sprawdź tryb, świeżość wejść, plan i konflikty. Brak wymaganych danych podczas startu może pozostawić EMS w obserwacji; po wyjaśnieniu problemu przelicz plan i jawnie wznów sterowanie.

## Powrót do poprzedniego EMS

1. Przełącz Deye EMS do obserwacji i potwierdź bezpieczny stan ładowania.
2. Odtwórz poprzedni system według prywatnej kopii oraz jego instrukcji. Eksport definicji nie zawsze odtwarza identyfikatory rejestru; do pełnego odtworzenia służy natywna kopia HA.
3. Pełne przywrócenie kopii cofa również niezwiązane zmiany i restartuje HA. Operator powinien świadomie wybrać ten zakres odtwarzania.
4. Przywróć wymagane pomiary i usługi poprzedniego EMS, a potem jego jedynego wykonawcę i nadzór. Pozostaw Deye EMS w obserwacji.
5. Sprawdź odczyty nastaw i rzeczywiste przepływy. Konflikt nie uruchamia poprzedniego regulatora automatycznie.

## Podgląd prognoz 2.1.8

Zachowaj kopię ustawień bez danych dostępu i poprzedni ZIP 2.1.7, sprawdź konfigurację przed restartem i dotychczasowy tryb po starcie. Wydanie nie zmienia źródeł ani limitów. Wyłączenie osobnego Solcast jest oddzielną czynnością; nie wyłączaj jedynego źródła encji HA przed przejściem na API EMS.


## Ładowanie i sekwencyjne pomiary — 2.1.9

Kolejne pomiary RS485 mogą pochodzić z różnych części cyklu odczytu. Wspólna tolerancja różnicy znaczników grupy mocy baterii i portu GRID oraz kontroli CT wynosi teraz 20 s. Maksymalny wiek mocy nadal wynosi 30 s, napięcia 120 s. Jednostki, zakresy, brak raportów, alarmy BMS i limity mocy pozostają sprawdzane. Panel zachowuje ostatnio wykryte źródło i przyczynę problemu także po odzyskaniu prawidłowych pomiarów; zapis historyczny nie zastępuje aktualnej walidacji. Nie wymaga to zmiany firmware ESPHome.

Po osiągnięciu celu histereza wznowienia wynosi 5 p.p. SoC. W ostatniej godzinie taniego okna silnik może jednokrotnie zwolnić tę blokadę, gdy SoC jest poniżej celu. Następne osiągnięcie celu ponownie zatrzymuje ładowanie. Nie podnosi to ustawionego celu ani maksymalnego SoC.

Małe, jeszcze nierozpoczęte doładowanie (obliczona potrzeba do 10 A) można odłożyć bliżej końca taniego okna. Silnik uwzględnia aktualny limit prądu, napięcie, sprawność, obserwowane rozładowywanie i zapas rezerwy; pozostawia co najmniej godzinę oraz margines czasu. Niski limit lub zagrożenie rezerwy powodują wcześniejszy start. Rozpoczęte ładowanie nie jest zatrzymywane wyłącznie przez ten mechanizm odkładania. Nagła zmiana obciążenia może zmienić termin; osiągnięcie celu nie jest gwarantowane.

Zwykłe dodatnie nastawy zachowują odstęp co najmniej 600 s, krok 5 A i martwą strefę 10 A. Ochronne redukcje pozostają natychmiastowe; powrót wymaga 120 s stabilnych warunków. Nie zmieniono godzin TOU, taryfy, rezerwy, topologii ani przypisań encji.
