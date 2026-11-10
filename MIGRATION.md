# Przejście z dotychczasowego EMS

Ta instrukcja jest procedurą. Samo zainstalowanie albo opublikowanie integracji nie wyłącza dotychczasowego EMS.

## 1. Instalacja i porównanie

Dodaj Deye EMS w obserwacji. Obecny wykonawca EMHASS pozostaje jedynym sterownikiem. Sprawdź: rezerwę 40%, godziny zimowe i letnie, jednostki i znaki mocy, prognozę PV z datami, profil LOAD/odbiorników, wybrany cel na termin oraz ograniczenia 12 kW / 5 kW na fazę.

Plan i runtime mają sygnalizować braki danych i nieosiągalność. Nie zastępuj tych stanów deklaracją „0 kWh importu”. Pierwsze niepełne pomiary slotów mają niepełne pokrycie.

## 2. Przejęcie wykonawcy

Zachowaj kopie konfiguracji oraz listę włączonych encji. W obecnej instalacji stare siedem sterowników ma pozostać OFF. Wyłącz również:

- `automation.ems_emhass_sterowanie_produkcyjne`;
- `automation.ems_emhass_ochrona_wlasciciela`;
- `automation.ems_emhass_plan_shadow_co_5_minut`.

Następnie w Deye EMS wybierz **Sterowanie** (`active`). Integracja sprawdza pomiary, tryby falownika, komplet i unikalność przypisań wyjść oraz znanych konkurujących sterowników. Nie wyłącza automatycznie innego regulatora. W nowej instalacji HA nie wymaga istnienia żadnego starego automatu.

Po przejęciu sprawdź oddzielnie: obliczenie, próbę polecenia, odczyt nastawy oraz rzeczywistą moc baterii i Grid. Pomiary aktualizują się z opóźnieniem. Zmiana prądu nie jest dowodem osiągnięcia przyszłego SoC.

## 3. Usunięcie obu poprzednich EMS

Nowa integracja nie korzysta z helperów `ems_` ani pomocniczych automatyzacji EMS. Sama mierzy energię slotów, przechowuje prognozy i cele z datami oraz rejestruje próby poleceń.

Po potwierdzeniu pracy, zgodnie z decyzją użytkownika, usuń dawne logistyki nocy, pomiary slotów 3/5, cache Solcast i potwierdzanie progów SoC, a także automatyzacje wykonawcze, helpery i dashboardy obu poprzednich EMS. Przed usunięciem zapisz odtwarzalną kopię konfiguracji oraz lokalną kopię stanu. Bieżących odczytów domu i danych dostępu nie publikuj w repozytorium.

Na czas świadomego usuwania wpisów starych sterowników przełącz nową integrację w **Obserwację**, gdy stare sterowniki jeszcze istnieją i są OFF. Potwierdź odczyt **0 A prądu sieciowego i GC OFF**, zanim usuniesz pierwszego właściciela. Samo automatyczne przejście do obserwacji po wykryciu konfliktu nie zeruje nastaw falownika. Po zakończeniu porządkowania jawnie wybierz **Sterowanie** — ponowne przejęcie sprawdzi aktualnie istniejące regulatory. Zniknięcie zapamiętanego sterownika podczas zwykłej aktywnej pracy pozostaje konfliktem, a nie automatycznym zezwoleniem na pominięcie ochrony.

Przed wyłączeniem sprawdź rzeczywistych konsumentów: inne dashboardy, sensory lub niezwiązane automatyzacje mogą nadal odczytywać te encje. Dla każdego elementu odnotuj: poprzedni stan, zależności, decyzję i sposób odtworzenia. Historyczny inwentarz starego projektu nie zastępuje aktualnego odczytu HA.

**Zachowaj wejścia fizyczne i integracje źródłowe:** Deye ESPHome, YamBMS, pomiary odbiorników, Recorder i źródła prognoz PV. Nie są częścią likwidowanej warstwy helperów EMS.

Przy korzystaniu z prognoz z encji HA zachowaj integrację **Solcast Solar** i wskazane encje prognozy. Usunięcie dawnych helperów cache EMS nie usuwa tego niezależnego źródła. Wbudowany klient API Solcast jest alternatywną konfiguracją źródła, a jego uruchomienie opisuje [INSTALL.md](INSTALL.md). Przy zmianie klienta zachowaj wykorzystany budżet API i zakończ równoległe odpytywanie konta.

## 4. Restart Home Assistant

Falownik podczas restartu HA zachowuje swoje ostatnie nastawy i harmonogram TOU. Wyładowanie integracji nie jest poleceniem zerowania prądu.

Po uruchomieniu sprawdź **Tryb pracy**, świeżość pomiarów, plan i konflikty. Jeżeli wymagane źródła nie były gotowe podczas startu, integracja zapisuje **Obserwację** i nie włącza później sterowania samoczynnie. Po przywróceniu źródeł przelicz plan i jawnie wybierz **Sterowanie**. Nie wymuszaj przejęcia przy nieprawidłowych danych lub konflikcie właścicieli.

## 5. Powrót do EMHASS z kopii

1. Przełącz Deye EMS do obserwacji; sprawdź GC i prąd sieciowy.
2. Odtwórz usuniętą aplikację EMHASS wraz z jej danymi oraz helpery, sensory, pakiety i makra według spisanej listy. Same eksporty definicji nie odtwarzają dokładnych identyfikatorów wpisów rejestru; do tego służy natywna kopia HA. Przywrócenie pełnej kopii cofa także inne zmiany od momentu jej wykonania i restartuje HA — wymaga osobnej decyzji operatora.
3. Przywróć pomocnicze mechanizmy telemetryczne i potwierdzacz zgodnie z kopią.
4. Włącz koordynator EMHASS i ochronę właściciela, a następnie jego wykonawcę.
5. Siedem dawnych wykonawców pozostaje OFF.
6. Sprawdź odczyty i rzeczywiste przepływy. Deye EMS pozostaje w obserwacji.

Konflikt wykryty w aktywnym Deye EMS powoduje rezygnację z jego własnego sterowania. Nie uruchamia starej wersji automatycznie.

