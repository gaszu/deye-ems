# Specyfikacja Deye EMS 1.0.0

Uzgodniona podstawa wersji 1.0.0. Kolejne poprawki mają zachowywać opisane zachowanie; rozszerzenia i strojenie będą opisywane w następnych wersjach.

## Instalacja i niezależność

- Instalowalna integracja Home Assistant 2026.11+, publiczny kod `gaszu/ha-deye-ems`, własne repozytorium Marketplace/HACS i paczka ZIP.
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
- Ładowanie rozłożone na dostępne tanie okno. Kandydat1.0.7: zwykła nastawa wyliczana z brakującej energii i czasu do terminu, bez rampy20A. Polecenie tylko w pierwszej minucie :00/:30, najwyżej jedno możliwe wysłanie w bloku półgodzinnym. Zaokrąglenie do5A bez przekroczenia ograniczeń; zmiana co najmniej10A, z wyjątkiem bezpiecznego startu z0A. Zapas GRID i całego ustawienia przy GC ON pozostają obowiązkowe. Osiągnięcie celu zatrzaskuje stop dla danego terminu; wznowienie po spadku o2p.p. lub poniżej minimalnej rezerwy, a przy nowym terminie według jego celu. Wznowienie wymaga120s ciągłych poprawnych obserwacji i najbliższego dopuszczonego terminu zapisu. Restart zachowuje zatrzask i rejestr poleceń, ale rozpoczyna obserwację bezpieczeństwa od nowa. Redukcje ochronne i zakończenie okna pozostają natychmiastowe w cyklu. Pominięty termin lub niepewne polecenie nie powodują serii ponowień.
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
