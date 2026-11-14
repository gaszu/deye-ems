# Specyfikacja Deye EMS 2.1.4

## Zwykłe dodatnie nastawy — 2.1.4

- Obowiązuje kroczące minimum 600 s między możliwie wysłanymi zwykłymi dodatnimi nastawami, zarówno przy starcie z zera, jak i korekcie niezerowej. Nie ma bramki pierwszej minuty :00/:30 ani licznika dodatnich zapisów na blok półgodzinny. Ten odstęp nie dotyczy natychmiastowych redukcji ochronnych i zerowania; takie działania nie przesuwają historii zwykłych dodatnich nastaw.
- Najwcześniejszy termin jest maksimum z bieżącego czasu, końca wymaganej stabilizacji 120 s, ostatniej możliwie wysłanej zwykłej dodatniej próby + 600 s, ostatniego możliwego polecenia + 120 s oraz ostatniego pewnego niewysłania + 60 s. Brak wiarygodnej historii lub potwierdzenia nastawy blokuje dodatnie polecenie. Termin nie zastępuje aktualnych kontroli bezpieczeństwa i nie gwarantuje usługi.
- Trwały rejestr rozróżnia zwykłe dodatnie polecenia od redukcji i zerowania oraz zachowuje wcześniejszy wpis potrzebny przy pewnym niewysłaniu. Prepared po awarii jest możliwie wysłaną próbą; niepewność nie skraca odstępu. Odczyt starszego formatu i migracja nie mogą tworzyć fikcyjnej pustej historii.
- Jednorazowa zgoda pierwszego startu nie jest zwracana przez zero, restart, zmianę slotu ani upływ czasu i nie omija minimum 600 s. Po zapisie próby, tuż przed usługą, nadal sprawdzane są odczyt nastawy, zgoda Grid Charge, potrzeba ładowania, taryfa, świeżość, zgodność czasowa, stabilność i limity GRID/LOAD, falownika oraz BMS.

## Datowanie natywnych raportów — 2.1.3

- Dwie poprawne wiadomości z tego samego połączenia i aktualnego przypisania nadal są wymagane. Najnowsza musi odpowiadać bieżącej wartości HA, urządzeniu, encji i jednostce; oba odbiory muszą mieścić się w dotychczasowym limicie wieku źródła.
- `reported_at` oznacza najnowszy rzeczywisty odbiór i służy do świeżości wartości oraz istniejącej kontroli zgodności czasowej. `confirmed_at` oznacza wcześniejszy odbiór pary i pozostaje osobno walidowany: `confirmed_at <= reported_at <= now`, świeżość obu oraz wymagane przejście obu raportów po zdarzeniu unieważniającym. Natywny znacznik jest używany tylko wtedy, gdy jest późniejszy od poprawnego znacznika HA. Nie tworzy się sztucznych znaczników ani nie zmienia limitów 30 s mocy, 120 s napięcia i 10 s rozbieżności grupy mocy.
- Przerwa ponad dopuszczalny wiek, cofnięcie zegara, rozłączenie lub zmiana źródła unieważniają parę. Znaczniki są czasami odbioru przez EMS, a nie chwilą akwizycji Modbus. Pomiary, nastawy i ich potwierdzenia nadal przechodzą dotychczasowe kontrole.

## Wygląd panelu — 2.1.2

- Przyklejona karta sterowania ze stanem trybu i przyciskiem korzysta ze wspólnych zmiennych kart HA: powierzchni, obramowania, promienia, cienia, filtra i odstępów.
- Opis panelu, topologia LOAD/CT, sprzęt i aktualizacje są przeniesione do jednego istniejącego bloku ustawień zaawansowanych. Stan rozwinięcia oraz sprawdzanie wydań w tle są zachowane.
- Odnośniki Marketplace i opisu wydania mają ten sam styl, typografię, odstępy, fokus i zachowanie hover co sąsiednie przyciski. Pozostają natywnymi odnośnikami z dotychczasowymi adresami i otwieraniem strony wydania w nowej karcie.

## Panel i zachowanie konfiguracji — 2.1.1

- Karty dni i kołowe wskaźniki powstają z `tariff_slot_targets`; rzeczywiste strefy operatora pozostają osobne od technicznych wpisów TOU. Jedna strefa całodobowa, wiele przedziałów i zmiany czasu nie wymagają stałego układu sześciu kart.
- Koło celu ładowania, koło minimalnego zapasu, aktualny pomiar SoC i prognoza mają odrębne etykiety. Brak wartości nie staje się zerem. Cel zachowawczy nie jest przedstawiany jako projekcja ani dowód osiągalności.
- Stan rozwinięcia ustawień jest zachowany podczas odświeżania oraz zmiany motywu. Opóźnione zdarzenia zastąpionego elementu nie zmieniają nowego widoku.
- Zwykłe przeładowanie po zapisie opcji zachowuje istniejącą trasę panelu EMS. Zagnieżdżone lub równoległe przeładowania nie zwalniają cudzej rejestracji. Błąd, anulowanie, rzeczywiste wyłączenie lub usunięcie sprzątają nieużywany panel.
- Nie zmieniono modelu energii, zasad taryf, rezerwy, ograniczeń prądu/mocy, mapowań, sposobu potwierdzania zapisów ani warunków uruchomienia sterowania.

## Taryfy i obsługa zapisu — 2.1.0

- Zakres to prosumenci na dotychczasowych zasadach opustu i pięciu OSD: PGE Dystrybucja, TAURON Dystrybucja, Enea Operator, Energa Operator, PGE Energetyka Kolejowa. Katalog ma 30 zweryfikowanych profili, dwie pozycje zablokowane i osobny `legacy_g13`. Metadane źródeł, okresy obowiązywania i warunki umów opisuje [TARIFFS.md](TARIFFS.md).
- Wybór operatora zawęża listę taryf. Użytkownik sprawdza umowę, wybiera jawnie `local` lub `fixed_cet` i zatwierdza podgląd. Niezgodny operator, profil poza ważnością, brak potwierdzenia umowy/zegara albo nieobsługiwane reguły blokują sterowanie. Zmiana konfiguracji unieważnia stary podgląd.
- Sezon taryfy jest niezależny od zmiany czasu. Kalendarz obsługuje dni tygodnia, święta i ich ciągi, doby 23/25 h oraz przedziały przez północ. Harmonogram i terminy celów pochodzą z wybranego profilu, a nie stałych godzin G13.
- Plan tworzy cel przed każdym ciągłym okresem droższym od najtańszej strefy. Taryfy całodobowe i długie okresy tanie zachowują jawnie opisany punkt kontrolny planera; nie jest on nową strefą OSD. `plan.targets` ma klucze terminów dla rzeczywistych profili. Podsumowanie zgodności `night/peak` nie dodaje poleceń.
- `plan.tariff_slot_targets` opisuje rzeczywiste przedziały operatora, zgodę na doładowanie, cel, rezerwę, projekcję i jakość. Cele zachowawcze nie udają prognozy; minione lub nieznane projekcje są `null`. Bieżąca projekcja startuje od chwili obliczenia, nie od fikcyjnego pomiaru na początku przedziału.
- Sześć wpisów Deye TOU jest osobnym programem sprzętowym. Taki sam pierwszy i ostatni fragment doby może tworzyć jeden przedział przez północ; dodatkowe podziały wypełniają tylko tę samą strefę. Nie mieszczący się lub niejednoznaczny program jest odrzucany. Przed zmianą godzin wymagane jest wyłączenie GC i potwierdzenie nastaw; odczyt nowego programu jest wymagany przed ładowaniem.
- Cykliczne sześć TOU ilustrują oficjalne instrukcje EU LV: [SG04LP3-EU 5–12 kW, PDF 41 / druk 39](https://www.deyeinverter.com/deyeinverter/2024/08/13/instructions_sun-5-12k-sg04lp3-eu_240813_en.pdf#page=41) oraz [SG05LP1-EU 3,6–8 kW, PDF 37 / druk 35](https://www.deyeinverter.com/deyeinverter/2026/03/19/rand/6545/%E3%80%90b%E3%80%91manual_sun-3.6-8k-sg05lp1-eu_20260319_en.pdf#page=37). Przykład rozpoczyna się o 01:00 i ostatnim przedziałem wraca do 01:00 przez północ. To podstawa modelu, nie potwierdzenie zachowania każdego firmware ani fizycznego wykonania.
- Końcowy zapis kreatora źródeł, modelu, Solcast lub taryfy zamyka formularz. Manager w HA przygotowuje nową konfigurację i plan, po czym zwykłą ścieżką aktywuje sterowanie tylko po spełnieniu zabezpieczeń. Oczekiwanie jest ograniczone czasowo; błędy pozostają jawne. Działa bez otwartego panelu. Anulowanie szkicu nie tworzy zamiaru aktywacji.
- Zapis podczas aktywnej pracy wymaga wcześniejszego żądania GC OFF / 0 A i poprawnych odczytów potwierdzających. Limit oczekiwania wynosi 30 s; brak potwierdzenia blokuje przeładowanie. Stary runtime nie może sterować według zmienionych, niezaładowanych opcji.
- Mechanizm sprawdzania po zapisie obejmuje zmienione opcje wpisu integracji, również odbiorniki i parametry zapisywane z panelu. Motyw i widoczność menu bocznego są przechowywane oddzielnie; ich zapis, odczyt katalogu, podgląd, anulowanie bez zapisu i ręczny STOP nie tworzą zamiaru aktywacji.
- Ręczny STOP anuluje oczekujący start także podczas przeładowania i nie może zostać nadpisany przez starszy zapis. Nowy zapis unieważnia wcześniejszy zamiar. Sekrety i wewnętrzne tokeny rewizji nie są udostępniane w statusie.
- Panel pokazuje rzeczywisty tryb z przyciskiem na górze, wynik sprawdzania po zapisie oraz trwały komunikat ostatniej nieudanej akcji. Zamknięcie tego komunikatu nie usuwa bieżącej blokady pomiarów lub zabezpieczeń.
- Aktualizacja plików zachowuje ustawienia, profil i tryb. Przejście z własnego G13 na operatora wymaga osobnego potwierdzenia; nie następuje automatycznie po instalacji nowego wydania.

Poniższe sekcje opisują zachowane mechanizmy i historię ich wprowadzania; nowy sposób wyboru taryfy i startu po zapisie określa sekcja 2.1 powyżej.

## Źródła i limity — zachowane rozszerzenie 2.0.3

- W profilu Deye, gdy dedykowana encja CCL nie istnieje albo jej przypisanie wyłączono, limit baterii pochodzi z niezależnej nastawy maksymalnego prądu falownika. Limit sieci nadal wynosi 95% tej nastawy. Wymagane pozostają poprawne i świeże pomiary Deye oraz kontrola alarmów. Istniejący odczyt CCL jest wiążący: zero blokuje, a błąd nie przełącza na zastępstwo. YamBMS i profil ręczny zachowują wymagane źródła BMS. `battery_limit_source` rozróżnia nastawę Deye, CCL odczytany z Deye i zewnętrzny BMS.
- Dla wybranego modelu 1F kreator może zaproponować istniejące encje `battery`, `time_of_use_<n>_charge_enable` oraz tekstowe statusy `device_alarm/device_fault`. Te ostatnie zezwalają na pracę tylko przy literalnym `OK`. Nie zmienia to firmware ani automatycznie zapisanych przypisań.
- Dodatkowy klient ESPHome tylko do odczytu może dostarczyć dowód odbioru dwóch poprawnych natywnych raportów z tej samej sesji i aktualnego przypisania urządzenia, encji i jednostki; najnowszy musi odpowiadać bieżącej wartości HA. Od 2.1.3 aktualną wartość datuje najnowszy odbiór, a wcześniejszy odbiór potwierdzający parę jest walidowany oddzielnie. Oba muszą być świeże według dotychczasowych limitów. Żaden nie jest czasem pomiaru Modbus. Rozłączenie i zmiana źródeł kasują dowody; utrata oryginalnego klienta HA zamyka własny klient EMS. Nastawy sterujące i ich potwierdzenia nadal używają oryginalnych stanów HA.

Poniższy opis 1.x zachowuje kontekst historyczny; powyższe rozszerzenie definiuje aktualne zachowanie profilu Deye bez dedykowanego CCL.

## Rozszerzenia linii 2.x

- Dokładny model EU lub profil własny określa jedną/trzy fazy i granice sprzętowe. W katalogu 2.0.0 znajdują się 16 modeli LV SG04LP1-EU, SG05LP1-EU-SM2-P i SG04LP3-EU. HV nie jest jeszcze obsługiwane. Katalog nie zastępuje mapowań ani potwierdzenia zgodności firmware.
- Limity producenta ograniczają moc oraz całkowity prąd ładowania, wspólny dla PV i sieci. Nie nadpisują niższych nastaw użytkownika, BMS ani Deye. Automatyczne minus 5% dotyczy aktualnego maksymalnego prądu Deye; port GRID i przyłącze są kontrolowane oddzielnie. Przepustowość AC producenta jest informacją, nie podwyższeniem obecnego limitu portu.
- Dla jednej fazy falownika wystarczają jego sumaryczne pomiary GRID i LOAD; są przypisane do rzeczywistej fazy połączenia. Pozostałe fazy falownika nie istnieją. Trójfazowy pomiar przyłącza CT nadal wymaga trzech rzeczywistych faz CT. Brak pomiaru lub przeciążenie fazy przyłącza blokuje zwiększanie ładowania.
- Model i fazy są zapisywane atomowo przez kreator, wyłącznie w obserwacji, po osobnym potwierdzeniu podglądu. Przypisania źródeł, rezerwa i topologia nie są zmieniane przez wybór modelu. Nowa instalacja zaczyna w obserwacji; wznowienie po końcowym zapisie opisuje sekcja 2.1 poniżej.
- Migracja 1.x zachowuje zapisane ustawienia i stan. Brak nowych pól oznacza profil własny, falownik/przyłącze trójfazowe i L1 jako etykietę fazy; trzyfazowe obliczenia pozostają zachowane.
- Moduł kalendarza rozdziela sezon taryfy od podstawy zegara licznika i obsługuje przedziały przez północ oraz doby 23/25 h. Sterowanie 2.0.0 zachowuje dawny codzienny harmonogram G13. Oficjalny profil operatora jest podglądem bez uprawnienia do sterowania; katalog operatorów/taryf jest kolejnym etapem. Szczegóły w [TARIFFS.md](TARIFFS.md).

## Zachowana podstawa wersji 1.x

Uzgodniona podstawa wersji 1.0.0. Kolejne poprawki mają zachowywać opisane zachowanie; rozszerzenia i strojenie będą opisywane w następnych wersjach.

## Źródła nowej instalacji — rozszerzenie 1.0.20

- Pierwsza konfiguracja domyślnie używa profilu baterii Deye. YamBMS jest opcjonalny; profil ręczny zachowuje własne przypisania. Dodatkowe odbiorniki, w tym pompa ciepła, nie mają domyślnych liczników.
- Prefiks i profil tworzą wyłącznie podgląd. Zapis mapowań jest osobną czynnością w obserwacji. Ręczne lub wyłączone źródła tego samego profilu są zachowywane; jawny wybór innego profilu proponuje zmianę grupy źródeł baterii. Puste opcjonalne selektory są pomijane przez formularz i zapisywane jako wyłączone źródła.
- Profil Deye używa SoC, rzeczywistego napięcia baterii, bieżącego limitu ładowania BMS oraz alarmu i błędu baterii. Bieżący limit CAN (rejestr 212) nie jest maksymalnym limitem CAN (218) ani nastawą prądu ładowania falownika. Zero ogranicza ładowanie do zera. Alarm lub błąd ogranicza je do zera; brak poprawnych źródeł unieważnia telemetrię. Napięcie pozostaje świeżym punktem odniesienia dla zatrzaskiwanych wartości BMS. Definicje: [Sunsynk](https://kellerza.github.io/sunsynk/reference/definitions), [Solarman Deye](https://github.com/davidrapan/ha-solarman/blob/main/custom_components/solarman/inverter_definitions/deye_p3.yaml).
- Starsze zapisane źródła baterii bez wyboru profilu pozostają ręczne. Jawnie skonfigurowana numeryczna blokada zachowuje dotychczasowe znaczenie i pierwszeństwo; aktualizacja nie zastępuje jej sygnałem alarmowym Deye.
- Kreator informuje przed wypełnieniem pól oraz po utworzeniu wpisu, że panel Deye EMS znajduje się w lewym menu administratora HA. Paczka zawiera pełne tłumaczenia polskie i angielski plik zastępczy wymagany przez HA.

## Stan doładowania i oczekiwanie — rozszerzenie 1.0.18

- Panel rozróżnia odczyt Grid Charge, zapisany limit prądu i fizyczną moc baterii. Nastawa ani włączony Grid Charge nie stanowią pomiaru energii pobranej z sieci.
- Backend podaje przyczynę oczekiwania oraz najwcześniejszy możliwy termin korekty, uwzględniając pierwszy start, stabilność pomiarów i ograniczenia ponowień. Termin nie jest obietnicą wysłania: potrzeba ładowania i zabezpieczenia są sprawdzane ponownie.
- Brak aktualnych pomiarów lub potwierdzenia rejestru nie jest przedstawiany jako działające ładowanie. Diagnostyka wskazuje źródła odrzucone przez dotychczasową walidację. Rozszerzenie nie zmienia decyzji ani harmonogramu regulatora.

## Priorytet PV w regulatorze — rozszerzenie 1.0.16

- `C = max(-battery_power, 0)` jest zmierzonym ładowaniem DC. `G = max(grid_port_power, suma faz portu GRID, 0)` jest dodatnim dopływem AC do falownika. Kredyt nadwyżki lokalnej wynosi `max(C - G - 200 W, 0)`. Odjęcie całego G przy sprawności 1 jest zachowawcze; nie przypisuje strat prostowania do PV i uwzględnia GRID zasilający dom przez bypass. CT, całkowita produkcja PV i nastawa prądu nie zastępują tych pomiarów.
- Kredyt pomniejsza wymagane tempo ładowania DC przed podzieleniem przez napięcie. Poniżej rezerwy żądane tempo łączne podnoszone jest do budżetu Deye/BMS, a dopiero potem odejmowany jest kredyt PV. Zwykły harmonogram zapisów i zatrzask SoC pozostają zachowane; pokrycie potrzeby przez PV nie oznacza osiągnięcia celu SoC.
- Ścisłe limity nastawy zachowują Deye−5%, ogólny limit Deye/BMS, zakres encji oraz istniejące budżety mocy i faz. Zmierzone przekroczenie łącznej mocy baterii ponad budżet prądu razy napięcie, po tolerancji 200 W, może jedynie zmniejszyć nastawę. Różnica nastawy i rzeczywistej mocy nie daje prawa do zwiększenia.
- Bateria i natywny GRID mają niezależne encje, poprawne jednostki, nieprzywrócone odczyty do 30 s i rozbieżność znaczników nie większą niż 10 s. Błąd unieważnia telemetrię ładowania. Potrzeba jest ponownie sprawdzana bezpośrednio przed zwiększeniem prądu i włączeniem GC, po oczekującym zapisie rejestru próby.
- Szacunek dotyczy nadwyżki po zasileniu odbiorów. Nie jest dokładnym licznikiem udziału źródeł; inne lokalne źródło DC również może uczestniczyć w bilansie. Obserwowany teraz wkład PV nie jest gwarancją produkcji do końca slotu. Regulator aktualizuje obliczenia z kolejnymi pomiarami.

## Pierwszy start ładowania — rozszerzenie 1.0.17

- Pierwsza nastawa z zera w tanim oknie może zostać wysłana po 120 s stabilnych obserwacji i po upływie odstępu zwykłych dodatnich nastaw z 2.1.4, przy znanej historii, bez niepotwierdzonej dodatniej nastawy i przy spełnieniu limitów oraz potrzeby ładowania. Od ostatniego możliwego polecenia nadal wymagane są 120 s, a od pewnego niewysłania 60 s.
- Uprawnienie jest trwałe i obejmuje całe okno do terminu celu: zimowe 21:00–07:00 jest jednym oknem także przez północ i zmianę slotów TOU. Każda możliwie wysłana dodatnia nastawa zużywa uprawnienie, również zwykła korekta. Zapisy zerowe go nie odnawiają. Prepared zapis po restarcie jest traktowany zachowawczo jako potencjalnie wysłany.
- Nieprawidłowy zapis lub niejednoznaczna historia starego wydania blokują automatyczny pierwszy start. Jawna zmiana z obserwacji do aktywnego sterowania może jednorazowo nadać brakujące uprawnienie przy znanej historii i zerowej nastawie, bez dodatniego oczekującego polecenia. Nie odnawia już zużytej ani uszkodzonej zgody.
- Kontrola ostatniej chwili po Store ponownie potwierdza okno, zerową nastawę i uprawnienie oraz wszystkie dotychczasowe zabezpieczenia. Zmiana PV/BMS, taryfy lub odczytu nastawy może zablokować przygotowaną próbę. Od 2.1.4 następne zwykłe dodatnie nastawy wymagają co najmniej 600 s od poprzedniej takiej możliwie wysłanej próby.

## Instalacja i niezależność

- Instalowalna integracja Home Assistant 2026.11+, publiczny kod `gaszu/deye-ems`, własne repozytorium Marketplace/HACS i paczka ZIP.
- Własny lokalny silnik, bez EMHASS, zewnętrznego solvera, pomocniczych automatyzacji i helperów EMS.
- Własne encje integracji, prosty panel, konfiguracja przez interfejs HA; pierwszy start w obserwacji.
- Istniejące sterowniki fizyczne Deye/ESPHome/MQTT/YamBMS oraz Recorder pozostają źródłami danych.

## Parametry instalacji

- Pojemność magazynu w kWh, stały minimalny bezpieczny SoC, bufor prognozy i cele sezonowe.
- Rzeczywista moc PV w kWp, osobna moc referencyjna prognozy oraz jawny wybór jej interpretacji.
- Moc falownika łącznie i dopuszczalna moc na fazę — osobno od limitów importu.
- Regulowane limity importu, prądu i modelowej mocy ładowania/rozładowania. Wartości początkowe: rezerwa40%, magazyn66kWh, import12kW łącznie/5kW na fazę; wartości należy dopasować do instalacji.
- Lista dodatkowych odbiorników: nazwa, licznik energii, opcjonalna moc. Uzupełnienie 1.0.3: checkbox ON/OFF włącza wyłącznie profil prognozy SoC. Główny LOAD obejmuje wszystkie odbiorniki domu; ich mocy i energii nie dolicza się ponownie do LOAD ani regulatora importu.

## Sterowanie

- Zima X–III: tanie okna21–07 i13–16, chronione07–13 i16–21.
- Lato IV–IX: tanie okna22–07 i13–19, chronione07–13 i19–22.
- Zimą pierwszeństwo mają autokonsumpcja, zapas na chronione okna i ograniczanie importu; pogodowy punkt odniesienia około75% przy słabej prognozie maleje wraz z dostępnością PV, z zachowaniem stałej rezerwy.
- Latem PV zasila dom, następnie utrzymuje wysoki poziom baterii, a nadwyżka jest eksportowana. Doładowanie z sieci jest awaryjne, wyłącznie w tanich oknach przy deficycie lub utracie wiarygodnego planu/cache.
- Ładowanie rozłożone na dostępne tanie okno. Zwykła nastawa jest wyliczana z brakującej energii i czasu do terminu, bez rampy20A. Od 2.1.4 zwykła dodatnia nastawa wymaga co najmniej 600 s od poprzedniej możliwie wysłanej zwykłej dodatniej nastawy; nie zależy od pierwszej minuty bloku półgodzinnego. Zaokrąglenie do5A bez przekroczenia ograniczeń; zmiana co najmniej10A, z wyjątkiem bezpiecznego startu z0A. Zapas GRID i całego ustawienia przy GC ON pozostają obowiązkowe. Osiągnięcie celu zatrzaskuje stop dla danego terminu; wznowienie po spadku o2p.p. lub poniżej minimalnej rezerwy, a przy nowym terminie według jego celu. Wznowienie wymaga120s ciągłych poprawnych obserwacji i najbliższego dopuszczonego terminu zapisu. Restart zachowuje zatrzask i rejestr poleceń, ale rozpoczyna obserwację bezpieczeństwa od nowa. Redukcje ochronne i zakończenie okna pozostają natychmiastowe w cyklu. Pominięty termin lub niepewne polecenie nie powodują serii ponowień.
- Limity importu GRID sumy/faz i ograniczenie mocy konwersji falownika są sprawdzane osobno. BMS i twarde ograniczenia mają pierwszeństwo.
- Uściślenie 1.0.3: potwierdzone bilansowanie faz w Zero Export To Load pozwala modelować równy pobór GRID. Przy bezpiecznej redukcji przyjętej przez usługę GC może pozostać ON podczas oczekiwania na odczyt, najwyżej30s bez odnawiania przez ponowienia; twarde ograniczenia i okna chronione pozostają nadrzędne.
- Regulacja lokalna co10s; pobieranie prognoz i historii w tle. Powolne API nie zatrzymuje kontroli obciążenia.
- Jeden właściciel sterowania, kontrola konfliktów, trwały zapis próby przed poleceniem, kontrolowany odczyt nastawy. Model, polecenie i pomiar fizyczny są rozróżniane.

## Solcast i prognozy

- Wbudowany klient Solcast: klucz API, identyfikatory instalacji, częstotliwość i limit zapytań, wykluczenia oraz korekty. Osobna integracja Solcast nie jest wymagana.
- Geometrię instalacji Hobbyist — moc AC/DC, azymut, nachylenie, sprawność — ustawia się w Solcast Toolkit. EMS korzysta z prognozy zapisanej tam instalacji.
- Prognoza całej instalacji jest zachowana1:1, także gdy jej moc jest celową wartością kalibracyjną. Skalowanie stosunku mocy działa wyłącznie w jawnym trybie profilu referencyjnego.
- Import dostępnych ustawień i bieżących24/48 współczynników z istniejącego Solcasta. Globalna tabela ma pierwszeństwo przed tabelami instalacji. Import współczynników jest ich stanem; nie przenosi pełnej historii ani mechanizmu dalszego samouczenia poprzedniej integracji.
- Korekty są stosowane do surowych odpowiedzi API. Prognozy odczytywane z encji HA są już skorygowane i nie otrzymują ich ponownie.
- P10/P50, własny datowany cache, walidacja pełnego horyzontu i powiązania z instalacją. Brak danych jest brakiem danych, nie zerem.
- Trwały rejestr zapytań na dobę UTC, zapis przed HTTP, uwzględnienie błędów i limitów API. Klucz nie trafia do panelu, planu, cache ani publicznego repo.

## Pomiary i migracja

- Wewnętrzne pomiary energii w slotach, w tym3 i5 oraz slotach nocnych; jawna kompletność i braki pomiarów.
- Prognoza48h oparta na PV i profilach domu/odbiorników z Recorder, sezonowy bilans energii oraz zachowawczy fallback.
- Usunięcie składników obu poprzednich EMS następuje po odtwarzalnej kopii, sprawdzeniu zależności i zweryfikowanym przejęciu produkcji. Źródła fizyczne i niezwiązane funkcje domu pozostają.
- Publikacja i testy offline nie oznaczają same w sobie przejęcia produkcyjnego ani potwierdzenia reakcji sprzętu. Aktualny zakres sprawdzeń opisuje `VALIDATION.md`.

## Wersja1.0.7 — jawna topologia CT

- Dom pod LOAD oraz pasywne odbiory między GRID falownika a CT przy przyłączu. CT i port GRID są osobnymi mapowaniami sumy/faz; oba dodatnie do domu/falownika. Bilans zewnętrznej gałęzi toCT−GRID. LOAD jest samo UPS/LOAD, a pełne zapotrzebowanie obejmuje LOAD plus tę gałąź dokładnie raz.
- Wymiana z siecią, limity importu i rejestr energii slotów używają CT. PortGRID może oddawać do CWU przyCT=0 bez eksportu do sieci. Historia zapotrzebowania dodaje różnicę zgodnych godzin CT−GRID do LOAD.
- Wymagany trybZero Export To CT jest wybrany jawnie; dotychczasowy wariantLoad-only nadal wymagaZero Export To Load. Żadnego automatycznego przełączania trybów. Zmiana kontekstu pomiarowego unieważnia plan i pozostawia obserwację.
- Wspólna znamionowa moc oraz limit modelowy obejmują falownik jako całość. Model rozdziela dostępny limit między PV i baterię na pełne obciążenie; nie są to dwa niezależne limity dla LOAD i CWU. EMS nie zapisuje sprzętowego ograniczenia mocy falownika.

## Strojenie 1.0.13 — automatyczny limit i port GRID

- Górny limit prądu ładowania z sieci to `floor(95% × Maximum Battery Charge Current)` odczytany z Deye. Nastawa Maximum Battery Grid Charge Current pozostaje wyjściem sterownika. Stałe 108 A oraz dawny ręczny parametr nie ograniczają ani nie zastępują poprawnego odczytu. BMS i zakres wyjścia nadal ograniczają wynik.
- Import portu GRID, suma i fazy, podlega skonfigurowanej mocy falownika osobno od wymiany przyłącza na CT. Przy szacowaniu zapasu portu używany jest natywny LOAD, a przy kontroli przyłącza pełny bilans domu. Odbiory między CT a portem GRID nie są doliczane do portu drugi raz.
- Chroniony slot blokuje ładowanie baterii z sieci i preferuje pokrywanie domu z PV/baterii w dostępnych granicach. Nie ustanawia twardego CT=0: duży odbiór między CT a portem GRID może pobierać resztę mocy bezpośrednio z sieci. Przykład25kWodbioru, GRID−12kW, CT+13kW jest dozwolony, jeśli spełniony jest niezależny limit przyłącza i pozostałe warunki. Natywny LOAD współdzieli moc wyjściową falownika z odbiorami gałęzi.
- W prognozie bez osobnego przyszłego profilu gałęzi CT pełny dom jest traktowany zachowawczo jako obciążenie portu; może to obniżyć modelową dostępność ładowania. Bieżący regulator korzysta z oddzielnych rzeczywistych pomiarów.
- Wymagany prąd i prognozowana energia używają aktualnego napięcia baterii oraz osobno sprawności konwersji AC/DC i magazynowania. Od 1.0.15 stały `charge_max_kw` jest ignorowany. Planer otrzymuje `battery_charge_max_a = min(Deye Max A Charge, BMS)` oraz `grid_current_max_a = min(floor(0,95 × Deye Max A Charge), BMS, zakres nastawy GRID)`. Wspólna moc PV i sieci nie przekracza `battery_charge_max_a × napięcie / 1000` ani mocy falownika. Sieć dodatkowo mieści się w własnym limicie prądowym, budżecie pozostałym po PV oraz przewidywanym zapasie mocy przyłącza i falownika. Limity prądowe i napięcie są odczytywane po wolnych odczytach historii/PV. Brak lub błąd danych daje brak poprawnej projekcji; prawidłowe zero lub blokada BMS daje zerowe ładowanie. Regulator wykonawczy zachowuje niezależne bieżące kontrole limitów sumarycznych i fazowych, bez stałego ograniczenia 5,3 kW.
- Zwykłe dodatnie nastawy zachowują co najmniej 600 s odstępu zgodnie z 2.1.4; histereza SoC pozostaje. Nowe twarde limity są sprawdzane także po zapisie rejestru próby, bezpośrednio przed poleceniem; redukcje ochronne nie czekają na harmonogram.
