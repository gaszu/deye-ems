# Sprawdzenia wersji 1.0.3

- **279/279 testów Python PASS i 31/31 testów panelu PASS**.
- Testy CRUD obejmują domyślną PC, trwałe usunięcie, ON/OFF z zachowaniem konfiguracji i identyfikatora, walidację jednostek i źródeł, konflikt wersji listy, blokadę active i kolejność zapisu przed reload.
- Testy panelu sprawdzają zachowanie szkicu, przełączenie trybu podczas edycji, zgodność wersji wiersza z jego formularzem i przełącznikiem oraz brak ujawniania danych dostępu.
- W podglądzie przeglądarki na syntetycznych danych dodano, zmieniono i usunięto testowy odbiornik oraz przełączono PC OFF i ON. Te czynności nie zmieniały konfiguracji domu.
- Cały LOAD pozostaje źródłem zużycia domu: kanały, także historyczne z flagą poza LOAD, nie doliczają mocy/energii i nie blokują regulatora przy braku opcjonalnego pomiaru. Kanały ON służą wyłącznie modelowaniu prognozy SoC.
- Potwierdzone ON bilansowania faz i Zero Export To Load aktywuje model zbilansowanego poboru GRID; brak/OFF/stare dane zachowują wariant zachowawczy. Limity importu sumy/faz i osobny limit konwersji falownika sprawdzono niezależnie.
- Regresje utrzymania GC przy bezpiecznym obniżeniu obejmują stary odczyt, zmianę limitu w trakcie zapisu, nieudaną usługę, brak dowodu przyjęcia, timeout bez odnawiania 30 s, wzrost odczytu, utratę flagi, BMS, GRID, stare pomiary, zmianę właściciela i okno chronione. Dowód przyjęcia usługi nie jest traktowany jako fizyczny odczyt urządzenia.

## Weryfikacja poprawki 1.0.2

Poprawka panelu, 10 listopada 2026:

- Zachowanie aktualnego stanu `details.open` przy przebudowie widoku. Pierwszy widok pozostaje zwinięty; kolejne odświeżenia zachowują ostatni wybór użytkownika.
- **19/19 testów panelu PASS**. Nowe regresje obejmują wielokrotne odświeżanie otwartej sekcji przy aktualizujących się pomiarach, ręczne zamknięcie, powodzenie i błąd polecenia oraz zamknięcie podczas oczekiwania na jego wynik.
- W podglądzie przeglądarki na danych syntetycznych potwierdzono utrzymanie rozwiniętej sekcji po kilku automatycznych odświeżeniach. Testy instalacji i zgodności wersji panelu: **10/10 PASS**.

## Weryfikacja poprawki 1.0.1

Poprawka panelu, 10 listopada 2026:

- Ustalono natywną przyczynę braku danych: `AttributeError: ActiveConnection has no attribute require_admin` w obu handlerach WebSocket. Zastąpiono wywołanie oficjalnym dekoratorem HA 2026.11, w kolejności przed `async_response`.
- 8 nowych testów granicy WebSocket PASS: administrator, blokada zwykłego użytkownika i braku użytkownika przed uruchomieniem handlera, polecenia, błędy walidacji i brak prywatnych ustawień Solcast w odpowiedzi.
- 15 testów panelu Node.js PASS, w tym regresja aktualizacji komponentu przy już zarejestrowanej poprzedniej wersji w przeglądarce. Rejestracja HA, nazwa elementu i URL modułu wskazują tę samą wersję.
- Pełny zestaw Python po poprawce: **213/213 PASS**.
- Specyfikacja algorytmu pozostaje 1.0.0. Wydanie 1.0.1 nie zmienia obliczeń ani parametrów użytkownika.
- Workflow GitHub wykonuje testy i buduje paczkę przed utworzeniem nowego wydania. Istniejące tagi i pliki wydań pozostają niezmienione.
- Po instalacji 1.0.1 przez natywny Marketplace i restarcie HA sprawdzono prawdziwe wywołania `deye_ems/status` oraz polecenia `recalculate` i `mode`: poprawne odpowiedzi bez wcześniejszego `Unknown error`. Rejestr paneli HA wskazuje komponent `deye-ems-panel-1-0-1` i moduł `?v=1.0.1`.
- Po uzyskaniu świeżych pomiarów i pełnego planu ponownie włączono produkcyjne sterowanie bez konfliktów właścicieli. Weryfikacja API nie jest równoznaczna z wizualnym sprawdzeniem wszystkich widoków przeglądarki.

## Weryfikacja bazowej wersji 1.0.0

Data: 10 listopada 2026, Europe/Warsaw.

- 205 testów Python PASS: planer, limity i rampa, cache, pomiary slotów, runtime, start/reload integracji, konfiguracja i wbudowany klient oraz importer Solcast.
- 14 testów panelu Node.js PASS: prosty widok, brak fikcyjnych zer, XSS, błędy poleceń, zachowanie edytowanych pól i wyścigi odpowiedzi.
- Sprawdzono składnię Python/JSON/JavaScript, komplet platform, manifest i strukturę ZIP.
- Sprawdzono wizualnie panel w przeglądarce na danych syntetycznych; zapis rezerwy 55% w podglądzie aktualizuje widok. Nie jest to zmiana ustawienia HA.
- Porównano użyte API instalacji, panelu i Recorder z kodem HA Core 2026.11.0.
- Solcast: quota UTC przed HTTP, restart i zmiana źródła bez zerowania limitu, pełne pokrycie prognozy, błędy API, import korekt i brak klucza w panelu/cache/planie. HTTP jest atrapą; nie wykonano testu prawdziwym kluczem.
- Symulowane zablokowane pobieranie HTTP nie zatrzymuje regulacji: przy przeciążeniu żądanie prądu spada do 0 A w wywołaniu trwającym poniżej 0,5 s. Sprawdzono anulowanie zadania oraz odrzucenie planu dla nieaktualnej konfiguracji.
- Niższa skonfigurowana moc falownika i fazy ogranicza prąd oraz model niezależnie od wyższych limitów sieci.
- Import 24/48 współczynników zachowuje prawdziwe zero, odrzuca braki, uwzględnia pierwszeństwo ALL/global i wykluczenia. Korekty są stosowane tylko do surowego API, bez ponownego mnożenia skorygowanych prognoz HA.
- Natywny start w HA Core2026.11: wpis integracji `loaded`, własne encje i tryb obserwacji; brak wpisów błędów `deye_ems` w dzienniku systemowym. Dotychczasowy regulator pozostał aktywny.
- Następnie sprawdzono przejęcie produkcyjne: poprzedni wykonawca i jego nadzór OFF, nowa integracja `active`, brak konfliktu właścicieli, zgodny odczyt nastawy prądu, aktywny GC w bieżącym tanim slocie i pomiar ładowania baterii. GC w chronionych slotach3/5 pozostajeOFF. To obserwacja konkretnych odczytów, nie gwarancja osiągnięcia każdego celu SoC.
- Po pełnej kopii HA usunięto poprzednią warstwę EMS, jej wpisy rejestru i aplikację EMHASS. Wykonano restart, sprawdzenie konfiguracji bez błędów, przeliczenie planu na świeżych danych i ponowne przejęcie `active`. Zachowane źródła fizyczne i Solcast pozostały załadowane; dziennik nowej integracji nie zawierał błędów. Dokładny inwentarz, kopie i odczyty wdrożenia są przechowywane prywatnie.
- Stała flaga blokady BMS nie wymaga cyklicznych zmian wartości. Jej poprawny odczyt nadal wymaga dostępności i świeżego napięcia tego samego BMS; aktywna blokada, przywrócony stan lub nieprawidłowe dane blokują ładowanie.

Testy runtime i cyklu życia podstawiają framework HA na granicy API; rzeczywiste funkcje planera i regulatora są wykonywane. Osobno potwierdzono natywne załadowanie, przejęcie sterowania i odczyty opisane powyżej. Pełna ocena działania w różnych warunkach pogodowych i obciążeniach wymaga obserwacji w czasie.

Paczka nie zawiera tokenów, haseł ani historii domu. Przykłady i testy są syntetyczne.
