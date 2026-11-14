# Przejście z innego EMS i powrót z kopii

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
