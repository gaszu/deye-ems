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
- Lista dodatkowych odbiorników: nazwa, licznik energii, opcjonalna moc, informacja o ujęciu w LOAD. Odbiornik już ujęty w LOAD nie jest dodawany ponownie.

## Sterowanie

- Zima X–III: tanie okna21–07 i13–16, chronione07–13 i16–21.
- Lato IV–IX: tanie okna22–07 i13–19, chronione07–13 i19–22.
- Zimą pierwszeństwo mają autokonsumpcja, zapas na chronione okna i ograniczanie importu; pogodowy punkt odniesienia około75% przy słabej prognozie maleje wraz z dostępnością PV, z zachowaniem stałej rezerwy.
- Latem PV zasila dom, następnie utrzymuje wysoki poziom baterii, a nadwyżka jest eksportowana. Doładowanie z sieci jest awaryjne, wyłącznie w tanich oknach przy deficycie lub utracie wiarygodnego planu/cache.
- Ładowanie rozłożone na całe dostępne tanie okno, także nocą. Wzrost nastawy maks.2A/30s, zwykły spadek5A/30s; redukcja bezpieczeństwa jest natychmiastowa w cyklu sterownika.
- Efektywne limity sumy i faz są przecięciem limitów importu oraz skonfigurowanej mocy falownika/fazy. Ograniczenia BMS i falownika mają pierwszeństwo.
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
