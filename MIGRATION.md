# Aktualizacja, migracja i powrót do poprzedniej wersji

EMS używa wewnętrznego CT Deye (suma i wymagane fazy) do pomiaru portu GRID w obu trybach. Zewnętrzne CT jest wymagane tylko w Zero Export To CT, gdzie mierzy przyłącze. Zapisane niestandardowe przypisania pozostają w użyciu. EMS blokuje sterowanie bez wymaganych świeżych pomiarów. Jeżeli zmieniły się efektywne źródła, EMS przechodzi do obserwacji. Przed ponowną aktywacją sprawdź przypisania i bilans mocy.

Instrukcja dla wydania [Deye EMS 2.5.6](https://github.com/gaszu/deye-ems/releases/tag/v2.5.6). Wybierz niżej procedurę odpowiednią do tego, czy aktualizujesz istniejący Deye EMS, przechodzisz z innego sterownika, czy wracasz do poprzedniej wersji.

## Aktualizacja istniejącego Deye EMS

1. Zapisz prywatną kopię aktualnej konfiguracji, przypisań i trybu pracy. Kopię przeznaczoną do porównania przygotuj bez kluczy i danych dostępowych. Odtwarzalną kopię Home Assistant przechowuj prywatnie. Zachowaj paczkę obecnie używanego wydania oraz zapisane dane runtime.
2. Jeśli działa TOP BALANCE, zakończ sesję i poczekaj na potwierdzenie przywrócenia nastaw slotu.
3. Zaktualizuj przez Marketplace lub zainstaluj właściwą paczkę ZIP zgodnie z [instrukcją instalacji](INSTALL.md). Zachowaj istniejący wpis integracji, przypisania encji i magazyn runtime. Sam pobrany ZIP nie potwierdza załadowania nowego kodu.
4. Uruchom kontrolę konfiguracji Home Assistant. Po poprawnym wyniku wykonaj wymagany restart. Falownik może zachować ostatnie nastawy w czasie restartu.
5. W ustawieniach zaawansowanych panelu sprawdź wersję **Uruchomiona w HA** i odśwież kartę, aby załadować zgodną wersję panelu. Potwierdź zapisany tryb pracy, aktualność telemetrii, jakość planu, brak konfliktów oraz zachowane ustawienia i przypisania. Jeżeli EMS sygnalizuje blokadę, sprawdź jej przyczynę przed ręcznym wznowieniem.

Wydanie 2.5.6 doprecyzowuje komunikat o wstrzymaniu doładowania przy braku zapasu mocy na przyłączu lub porcie GRID falownika. Wydanie 2.4.1 umożliwia wykorzystanie poprawnego profilu odbiornika, gdy inny licznik ma braki w historii. Harmonogram G13 nadal używa tych samych godzin sterowania każdego dnia sezonu. Po aktualizacji sprawdź zgodność wyświetlanego planu z potwierdzonym profilem i zegarem licznika. [Taryfy i zegar](TARIFFS.md)

## Przejście z innego EMS

1. Zapisz kopię konfiguracji dotychczasowego EMS. Spisz wszystkie automatyzacje, aplikacje i inne systemy zapisujące nastawy falownika, w tym mechanizmy automatycznego ponownego uruchamiania.
2. Dodaj Deye EMS w obserwacji. Sprawdź topologię LOAD lub CT, encje pomiarowe i zapisywalne, jednostki oraz znaki mocy, limity przyłącza i falownika, rezerwę, dane BMS i źródło prognozy. Zweryfikuj plan względem odczytów.
3. Przed końcowym zapisem, który może uzbroić automatyczne włączenie sterowania, zatrzymaj konkurujące regulatory. Deye EMS sprawdza znane konflikty i warunki startu. Zatrzymaj oczekujący start przyciskiem **Zatrzymaj i obserwuj**, jeśli przejęcie ma nastąpić później.
4. Po przejęciu sprawdź oddzielnie wyliczone żądanie, przyjęcie polecenia, odczyt nastawy i rzeczywisty przepływ energii. Jeśli wykryjesz konflikt, wstrzymaj przejęcie i ustal, który system zapisuje nastawy.

Przed usunięciem starych automatyzacji lub helperów sprawdź ich zależności. Zachowaj integrację dostarczającą pomiary falownika, BMS, statystyki Recorder i używane encje prognozy. Przy przejściu na wbudowany Solcast pamiętaj o wspólnym budżecie zapytań API. [Konfiguracja Solcast](INSTALL.md#solcast--konfiguracja-w-panelu)

## Powrót do poprzedniego wydania Deye EMS

1. Przejdź do obserwacji. Potwierdź zatrzymanie ładowania sieciowego i sprawdź odczyty nastawy prądu oraz Grid Charge. Sam restart lub wyładowanie integracji nie zeruje falownika.
2. Zabezpiecz bieżący stan. Wybierz dokładną wersję z wcześniej zachowanej paczki lub z [GitHub Releases](https://github.com/gaszu/deye-ems/releases). Dla powrotu z 2.5.6 do bezpośredniego poprzednika użyj [Deye EMS 2.5.5](https://github.com/gaszu/deye-ems/releases/tag/v2.5.5). Jeżeli aktualizujesz bezpośrednio z 2.3.07, zachowaj paczkę 2.3.07 jako własny punkt powrotu.
3. Zainstaluj poprzednią wersję, sprawdź konfigurację HA i uruchom ponownie. Zachowaj wpis integracji. Jeżeli dana ścieżka wymaga starszego formatu konfiguracji lub runtime, odtwórz pasującą kopię zgodnie z notatkami konkretnego wydania. Pełne przywrócenie kopii HA może cofnąć też niezwiązane zmiany.
4. Potwierdź wersję załadowaną przez HA i wersję panelu, ustawienia i przypisania, bieżące pomiary oraz plan. Po sprawdzeniu jawnie przywróć sterowanie, jeżeli było wcześniej włączone.

Przy powrocie do innego EMS pozostaw Deye EMS w obserwacji. Odtwórz poprzedniego wykonawcę i jego zależności z prywatnej kopii. Sprawdź, czy tylko wybrany sterownik wysyła polecenia.

## Starsze ścieżki migracji

Uwagi dotyczące dawnych wydań są dostępne w [archiwum instrukcji](https://github.com/gaszu/deye-ems/blob/d3bfe209c8150ffa636305f85659b31dcdfb9c88/MIGRATION.md) oraz w [historii wydań](https://github.com/gaszu/deye-ems/releases).
