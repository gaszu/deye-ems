# Przejście z innego EMS i powrót z kopii

Instalacja Deye EMS nie wyłącza innych regulatorów. Poniższa procedura jest ogólną instrukcją dla operatora instalacji.

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
