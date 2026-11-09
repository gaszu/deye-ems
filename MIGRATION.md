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

Następnie w Deye EMS wybierz active. Integracja sprawdza pomiary, tryby falownika, komplet i unikalność przypisań wyjść oraz znanych konkurujących sterowników. Nie wyłącza automatycznie innego regulatora. W nowej instalacji HA nie wymaga istnienia żadnego starego automatu.

Po przejęciu sprawdź oddzielnie: obliczenie, próbę polecenia, odczyt nastawy oraz rzeczywistą moc baterii i Grid. Pomiary aktualizują się z opóźnieniem. Zmiana prądu nie jest dowodem osiągnięcia przyszłego SoC.

## 3. Usunięcie pozostałych elementów starego i nowego EMS

Nowa integracja nie korzysta z helperów `ems_` ani pomocniczych automatyzacji EMS. Sama mierzy energię slotów, przechowuje prognozy i cele z datami oraz rejestruje próby poleceń.

Po potwierdzeniu pracy, zgodnie z decyzją użytkownika, usuń dawne logistyki nocy, pomiary slotów 3/5, cache Solcast i potwierdzanie progów SoC, a także automatyzacje wykonawcze, helpery i dashboardy obu poprzednich EMS. Przed usunięciem zapisz odtwarzalną kopię konfiguracji oraz lokalną kopię stanu. Bieżących odczytów domu i danych dostępu nie publikuj w repozytorium.

Na czas świadomego usuwania wpisów starych sterowników przełącz nową integrację w obserwację. Po zakończeniu porządkowania jawnie wybierz active — ponowne przejęcie sprawdzi aktualnie istniejące regulatory. Zniknięcie zapamiętanego sterownika podczas zwykłej aktywnej pracy pozostaje konfliktem, a nie automatycznym zezwoleniem na pominięcie ochrony.

Przed wyłączeniem sprawdź rzeczywistych konsumentów: inne dashboardy, sensory lub niezwiązane automatyzacje mogą nadal odczytywać te encje. Dla każdego elementu odnotuj: poprzedni stan, zależności, decyzję i sposób odtworzenia. Historyczny inwentarz starego projektu nie zastępuje aktualnego odczytu HA.

**Zachowaj wejścia fizyczne i integracje źródłowe:** Deye ESPHome, YamBMS, pomiary odbiorników, Recorder i źródła prognoz PV. Nie są częścią likwidowanej warstwy helperów EMS.

## 4. Powrót do obecnego wykonawcy EMHASS

1. Przełącz Deye EMS do obserwacji; sprawdź GC i prąd sieciowy.
2. Odtwórz usunięte helpery i sensory z kopii według spisanej listy.
3. Przywróć pomocnicze mechanizmy telemetryczne i potwierdzacz zgodnie z kopią.
4. Włącz koordynator EMHASS i ochronę właściciela, a następnie jego wykonawcę.
5. Siedem dawnych wykonawców pozostaje OFF.
6. Sprawdź odczyty i rzeczywiste przepływy. Deye EMS pozostaje w obserwacji.

Konflikt wykryty w aktywnym Deye EMS powoduje rezygnację z jego własnego sterowania. Nie uruchamia starej wersji automatycznie.

