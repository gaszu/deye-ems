# Specyfikacja silnika Deye EMS

Kafelki układu pod podsumowaniem pokazują moc i kierunek przepływu portu GRID, a w trybie CT także przyłącza. Odczyty faz są na tych samych kafelkach.

EMS używa wewnętrznego CT Deye (suma i wymagane fazy) do pomiaru portu GRID w obu trybach. Zewnętrzne CT jest wymagane tylko w Zero Export To CT, gdzie mierzy przyłącze. Zapisane niestandardowe przypisania pozostają w użyciu. EMS blokuje sterowanie bez wymaganych świeżych pomiarów.

Specyfikacja wydania [Deye EMS 2.6.10](https://github.com/gaszu/deye-ems/releases/tag/v2.6.10). Silnik planowania i regulacji działa lokalnie w Home Assistant. Prognozy, statystyki Recorder i panel korzystają z tego samego modelu instalacji. Odczyt historii i pobieranie Solcast odbywają się w tle, poza ścieżką ochronnej regulacji prądu.

## Pomiary i topologie

- W **Zero Export To Load** dom jest mierzony na wyjściu LOAD. Mierniki portu GRID opisują wymianę falownika z siecią.
- W **Zero Export To CT** wymianę przyłącza mierzy CT. Port GRID oznacza port falownika. Oba pomiary mają znak dodatni dla importu do odpowiednio instalacji i falownika. Obciążenie pomiędzy portem GRID a CT wynika z bilansu CT minus GRID, a zapotrzebowanie domu obejmuje je razem z LOAD.
- Konwerter falownika ma wspólny budżet mocy. Silnik sprawdza sumy i spójność pomiarów faz oraz osobne limity falownika i przyłącza. W układzie trójfazowym ocena możliwości zwiększenia prądu może uwzględnić bilansowanie potwierdzone pomiarami natywnego portu GRID. W układzie jednofazowym używa przypisanej fazy falownika.
- Ochrona sprawdza aktualność i spójność odczytów, BMS, konfigurację i zgodność trybów pracy. Skuteczna rezerwa uwzględnia aktualne Battery low SOC falownika powiększone o 5 p.p.

[Katalog falowników](custom_components/deye_ems/inverter_models.py) · [Limity i bilans mocy](custom_components/deye_ems/grid_control.py)

## Prognoza zużycia

Recorder dostarcza godzinowe statystyki z maksymalnie 42 dni. Model wyznacza średnią dla danej godziny osobno dla dni roboczych i weekendów, kiedy dostępnych jest co najmniej kilka porównywalnych dni. Przy krótszej historii korzysta z dostępnej wspólnej próbki. Dla powtarzającej się lokalnej godziny przy zmianie czasu próbki z tej samej daty są uśredniane razem.

Kiedy próbka pozwala porównać ostatnie dni z wcześniejszymi tygodniami, silnik dodaje połowę obserwowanej różnicy, ograniczoną do większej z wartości 100 W i 30% średniej bazowej. Korekta ma tłumić jednorazowe skoki i zachować reakcję na powtarzający się wzrost lub spadek obciążenia. Przy niewystarczających danych do porównania model bazuje na średniej z dostępnych próbek.

Dla dodatkowych odbiorników silnik oddziela ich historyczne zużycie od pomiaru łącznego tylko tam, gdzie dane godzinowe są wystarczające i spójne. Suma prognoz odbiorników i pozostałego zużycia tworzy prognozę domu. Gdy nie można bezpiecznie wydzielić kanałów, używany jest profil łączny. Limity importu opierają się na bieżących pomiarach instalacji. [Profil zużycia i źródła danych](custom_components/deye_ems/coordinator.py)

## Prognoza PV i cele SoC

- P10 modeluje słabszą produkcję PV. Planer używa go do doboru zapasu energii na chronione przedziały, sprawdzenia osiągalności celu i wykrycia ryzyka niedoboru.
- P50 jest scenariuszem środkowym. Na jego podstawie powstaje wykres przewidywanego SoC, a zimą także ocena pokrycia zużycia przez PV używana przy celu pogodowym.
- Wbudowany Solcast korzysta z lokalnie skonfigurowanego klucza API, identyfikatorów instalacji, limitu zapytań i cache powiązanego z instalacją. Można użyć także prognozy udostępnianej przez encje HA. Planer sprawdza horyzont i jakość danych. Niedostępne wartości pozostają nieznane, a plan zachowawczy jest oznaczany osobno.
- Cel planu, skuteczna rezerwa i maksymalny dopuszczalny SoC służą odrębnym funkcjom. Twardy limit ładowania ma pierwszeństwo przed całą optymalizacją.

[Planer](custom_components/deye_ems/planner.py) · [Klient Solcast](custom_components/deye_ems/solcast.py)

## Taryfa i TOU

Nowa konfiguracja może wybrać profile TAURON Dystrybucja G11, G12, G12w i G13. Kalendarz wymaga zgodności z zapisanym profilem, potwierdzenia i właściwego zegara. Sterowanie G13 używa tego samego harmonogramu w każdym dniu danego sezonu. Profil G12w może mieć niską strefę przez całą dobę taryfową w sobotę, niedzielę lub święto ustawowe.

Panel oznacza rodzaj dnia dla dziś i jutra według czasu lokalnego. Informacja o całodobowej niskiej strefie zależy od rzeczywistego pokrycia doby przedziałami potwierdzonego kalendarza, również przy stałym CET. Taryfa płaska G11 ma jedną strefę. Sześć slotów fizycznego TOU opisuje techniczny podział używany przez falownik. [Profile, dni wolne i zegar licznika](TARIFFS.md)

## Regulacja ładowania

- **Grid Charge.** W potwierdzonej taryfie uzbrajane są dozwolone sloty TOU, gdy przejdą zabezpieczenia. W dozwolonym slocie prąd może pozostawać na 0 A po osiągnięciu celu. Koniec okna lub warunek ochronny może wymagać wyłączenia ładowania.
- **Okno nocne.** W dozwolonym oknie potwierdzonej taryfy od 21:00 do 07:00 czasu lokalnego EMS dąży do celu SoC z bieżącą bezpieczną mocą. Między dodatnimi poleceniami zachowuje co najmniej 120 s. Po osiągnięciu celu ustawia 0 A. Zatrzask celu stosuje histerezę 5 p.p. z uwzględnieniem rezerwy.
- **Zwykłe ładowanie.** Poza przyspieszonym trybem nocnym EMS dopasowuje prąd do potrzeb i czasu pozostałego do celu. Zwykłe korekty mają rampę do 10 A i co najmniej 600 s między dodatnimi poleceniami, z uwzględnieniem progów, kroku urządzenia i limitów. Po miękkim celu prąd może być stopniowo wygaszany. Twardy limit SoC może zatrzymać go od razu.
- **Ochrona.** Nagły wzrost obciążenia, ograniczenie BMS albo nieprawidłowe dane mogą spowodować natychmiastową redukcję. Po ustaniu ograniczenia dodatnie korekty podlegają odstępom regulatora. Przed wysłaniem polecenia EMS ponownie sprawdza pomiary, uprawnienie i nastawy.
- **Diagnostyka.** Silnik rozróżnia wyliczoną nastawę, próbę polecenia, przyjęcie przez usługę, odczyt urządzenia i fizyczną moc baterii. Trwały zapis prób wspiera wznowienie po restarcie i ogranicza powtarzanie poleceń. Tryb obserwacji umożliwia weryfikację planu, a start sterowania wymaga prawidłowych danych i braku wykrytego konfliktu właścicieli.

## TOP BALANCE

Tryb ręczny w aktywnym EMS. Cel jest liczbą całkowitą do 100% w granicach akceptowanych przez falownik i konfigurację. EMS zapisuje oryginalne nastawy slotu, może włączyć Grid Charge także podczas drogiej strefy i dobiera prąd do aktualnych limitów. Po osiągnięciu celu lub ręcznym zakończeniu odtwarza zapisany próg SoC i ustawienie Grid Charge, a zwykły regulator ponownie oblicza prąd. Przy zmianie slotu najpierw odtwarza poprzedni. Po restarcie odzyskuje zapisane nastawy przerwanej sesji. Wyrównywanie ogniw realizuje BMS.

## Dokumenty powiązane

[Instalacja](INSTALL.md) · [Taryfy](TARIFFS.md) · [Migracja i powrót](MIGRATION.md) · [Walidacja](VALIDATION.md) · [Archiwum specyfikacji](https://github.com/gaszu/deye-ems/blob/9c31606c64830fbc868c778e385cffb8cfe551c7/SPECIFICATION.md)

## Ryzyko i diagnostyka planu

Panel pokazuje SoC w P10/P50 przed terminem oraz ewentualny niedobór energii w chronionym oknie. Silnik ocenia osiągalność każdego celu osobno, a panel rozróżnia cel planu i cel używany przez regulator. Podniesienie celu ochronnego na podstawie nieosiągalnego planu wymaga ryzyka wyczerpania rezerwy. Diagnostyka odbiornika podaje dostępne i wykorzystane godziny Recorder oraz zakres osobnego profilu. Problemy telemetrii podczas startu i w czasie pracy są rozróżniane.

Przy doborze osobnych profili zużycia każdy licznik jest sprawdzany osobno. Kanał z brakami pozostaje w zużyciu łącznym. Profile mogą korzystać tylko ze wspólnych godzin, w których ich łączne zużycie mieści się w pomiarze domu.
