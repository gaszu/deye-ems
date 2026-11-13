# Kalendarz taryf OSD w 2.1.0

Katalog odwzorowuje godziny stref **dystrybucyjnych** pięciu wybranych operatorów: PGE Dystrybucja, TAURON Dystrybucja, ENEA Operator, ENERGA-OPERATOR i PGE Energetyka Kolejowa Operator. Jest przeznaczony do planowania EMS u prosumentów pozostających w systemie opustów. Nie zmienia umowy, operatora, grupy taryfowej ani zasad rozliczeń. Nie oblicza cen, uprawnień do ulg ani salda wirtualnego magazynu.

Stary profil `legacy_g13` pozostaje oddzielny: zachowuje sześć dotychczasowych slotów codziennie, również w weekendy i święta. Aktualizacja nie zastępuje go taryfą operatora. Jawny wybór OSD i grupy oraz potwierdzenie umowy i zegara licznika są wymagane do uruchomienia rzeczywistego profilu.

## Zakres katalogu

| Operator | Potwierdzone kalendarze | Pozycje wymagające odrębnego źródła |
|---|---|---|
| PGE Dystrybucja | G11, G12, G12w, G12n, G12as | G12e: wymagany właściwy obszar i jego oficjalny harmonogram. |
| TAURON Dystrybucja | G11, G12, G12w, G12as, G13, G13s | G14dynamic: wymagane aktualne dane Energetycznego Kompasu. |
| ENEA Operator | G11, G11p, G11pewna, G12, G12p, G12w, G12as, G12sezON, G13active | Brak dodatkowego, domyślnie włączanego kalendarza. |
| ENERGA-OPERATOR | G11, G11f, G12, G12w, G12r, G12as | Brak klasycznej G13 w zweryfikowanej taryfie. |
| PGE Energetyka Kolejowa Operator | G11, G12, G12w, G12as | Brak G13 w zweryfikowanej taryfie. |

To 30 potwierdzonych kalendarzy operatorów, dwie jawnie zablokowane pozycje informacyjne oraz zachowany profil legacy. „Potwierdzony kalendarz” oznacza potwierdzone godziny, a nie automatyczne zakwalifikowanie każdej umowy do każdej oferty sprzedawcy. Warianty przedpłatowe i szczególne grupy jednostrefowe zachowują własne nazwy; kalendarz nie odwzorowuje ich pozostałych warunków finansowych.

G12as ma potwierdzoną noc22:00–06:00, ale preferencyjna opłata dotyczy przyrostu zużycia względem odpowiedniego okresu bazowego. EMS nie uznaje, że cały nocny pobór otrzyma taką ulgę. G13s wymaga spełnienia warunków tej grupy, m.in. właściwego licznika i rozliczenia; wybór w EMS nie jest wnioskiem o zmianę umowy. Nie wykryto w odczytanych warunkach godzin zakazu zachowania opustów przez sam wybór powyższych grup, ale zgodność konkretnej umowy musi potwierdzić użytkownik.

## Zegar, sezon i dni wolne

Wszystkie pięć taryf opisuje podstawowo zegar ustawiony na **stały czas zimowy CET**, z wyjątkiem urządzeń automatycznie utrzymujących opublikowane godziny stref w okresach letnim i zimowym. Dlatego przy wyborze rzeczywistego profilu trzeba jawnie potwierdzić jeden wariant:

- `local`: licznik zachowuje wskazane lokalne godziny przy zmianach czasu; kalendarz `Europe/Warsaw`.
- `fixed_cet`: UTC+01:00 przez cały rok; podczas czasu letniego panel pokazuje granice o godzinę później na zegarku lokalnym.

Datę, miesiąc, dzień tygodnia i święto rozstrzyga się w **wybranym zegarze taryfowym**. Przy stałym CET lokalna pierwsza godzina letniej doby należy jeszcze do poprzedniej daty licznika. Doby widoczne w panelu mają pełne pokrycie rzeczywistych23/24/25godzin. Sezon taryfy, najczęściej1kwietnia–30września, jest odrębny od marcowej i październikowej zmiany DST.

Kalendarz świąt uwzględnia ustawowe święta stałe, Wielkanoc i Poniedziałek Wielkanocny, Zielone Świątki i Boże Ciało, a także Wigilię od2025r. Dzień wolny przyznany przez pracodawcę za święto sobotnie nie staje się świętem taryfowym. Sobota jest uwzględniana osobno tylko w grupach, które ją wskazują. TAURON dopuszcza zachowanie poprzednich godzin lub katalogu świąt w starszych, jeszcze nieprzeprogramowanych licznikach: taki przypadek wymaga potwierdzenia ustawień, nie zgadywania przez EMS.

## Najważniejsze różnice godzin

Godziny poniżej są podane w potwierdzonym zegarze taryfowym, a nie zawsze w czasie zegarka użytkownika.

| Grupa / operator | Niższa strefa lub szczególna reguła |
|---|---|
| G11 i warianty jednostrefowe | Jedna strefa00:00–24:00; brak operatorowego końca taniego okna. |
| G12 TAURON/ENEA/ENERGA/PGE EK |13:00–15:00 oraz22:00–06:00, codziennie. |
| G12 PGE Dystrybucja | Zimą13:00–15:00, latem15:00–17:00, zawsze22:00–06:00. |
| G12w TAURON/ENERGA/PGE EK | Jak ich G12 w dni robocze; całe soboty, niedziele i święta niższe. |
| G12w PGE Dystrybucja | Jak sezonowe G12; całe soboty, niedziele i święta niższe. |
| G12w ENEA |21:00–06:00 w dni robocze; całe weekendy/święta niższe. **Bez dziennego bloku13:00–15:00.** |
| G12n PGE Dystrybucja |01:00–05:00 poniedziałek–sobota; całe niedziele/święta niższe. Zwykła sobota nie jest cała tańsza. |
| G12r ENERGA |13:00–16:00 i22:00–07:00, każdy dzień, bez całodobowego weekendowego wyjątku. |
| G13 TAURON | Szczyt rano07:00–13:00; wieczorem zimą16:00–21:00, latem19:00–22:00. Pozostałe godziny i całe weekendy/święta pozaszczytowe. |
| G13s TAURON | Latem: dzienna pozaszczytowa09:00–17:00, noc21:00–07:00, szczyt07:00–09:00 i17:00–21:00. Zimą: dzienna pozaszczytowa10:00–15:00, noc21:00–07:00, szczyt07:00–10:00 i15:00–21:00. |
| G12sezON ENEA | Zima22:00–06:00 i11:00–13:00; lato04:00–06:00 i09:00–17:00. Bez całodobowego weekendowego wyjątku. |
| G13active ENEA | Miesięczny rozkład trzech stref, przedstawiony poniżej; bez całodobowego weekendowego wyjątku. |

W G13s weekend/święto zmienia stawki, **nie usuwa stref szczytowych**. Kolejność preferencji dystrybucji latem: dzienna pozaszczytowa, noc, szczyt; zimą: noc, dzienna pozaszczytowa, szczyt. Kalendarz pozwala rozważać ładowanie z sieci tylko w najniższej klasie; nie oznacza to nakazu ładowania, szczególnie latem przy prognozie PV.

G13active ENEA:

| Miesiąc | Zalecany pobór (`low`) | Zalecane ograniczanie (`high`) |
|---|---|---|
| I |23:00–06:00 |07:00–10:00,15:00–20:00 |
| II |23:00–06:00 |07:00–09:00,16:00–21:00 |
| III |10:00–16:00 |06:00–09:00,16:00–23:00 |
| IV |10:00–16:00 |06:00–09:00,18:00–23:00 |
| V–VIII |09:00–17:00 |06:00–09:00,18:00–23:00 |
| IX |10:00–16:00 |06:00–09:00,17:00–23:00 |
| X |10:00–16:00 |07:00–09:00,16:00–23:00 |
| XI |23:00–06:00 |07:00–09:00,14:00–21:00 |
| XII |23:00–06:00 |07:00–10:00,13:00–20:00 |

Pozostałe godziny G13active to `normal`. Są odrębną strefą operatora, ale sam jej wybór nie udziela zgody na ładowanie z sieci.

## Kontrakt modułu i połączenie z planerem

`tariff_calendar.py` i wersjonowany `tariff_profiles.json` są niezależne od Home Assistanta i falownika. Nie wykonują połączeń sieciowych. Publiczne funkcje:

- `calendar_operators()` i `calendar_profiles(operator_id=None)`: kopie metadanych katalogu, z identyfikatorem, etykietą, źródłem, stroną, datami, wymaganym potwierdzeniem i przyczyną ewentualnej blokady.
- `describe_calendar(now, profile_id="legacy_g13", clock_basis="local")`: dzisiejsze i jutrzejsze przedziały w czasie lokalnym Warszawy, bieżąca strefa i następna zmiana. Sam podgląd nie aktywuje profilu.
- `intervals_between(start,end,profile_id,clock_basis)`: pełne pokrycie półotwartego przedziału `[start,end)` datowanymi wierszami UTC. Każdy zawiera ISO i timestamp granic, strefę, klasę `tier`, sezon, datę licznika, zgodę kalendarza na rozważenie ładowania oraz `within_validity`.
- `calendar_context(now,options)`: bieżący przedział, całe ciągłe okno ładowania przez północ/weekend/święta, kolejne okno i ciągłe okresy wymagające zapasu baterii. Sąsiednie `normal` i `high` łączy na potrzeby pokrycia zapotrzebowania, zachowując oddzielne wiersze stref w podglądzie.

Opcje rzeczywistego profilu to `tariff_profile`, `tariff_clock_basis` i ścisłe `tariff_contract_confirmed=true`. Brak potwierdzenia, wygaśnięcie danych lub znana blokada daje `valid=false` bez okien planistycznych. Nieznany profil/zegar jest błędem; nie uruchamia zastępczego legacy. Dane2026 nie potwierdzają taryfy2027. Planer musi sprawdzać ważność każdego używanego wiersza także wtedy, gdy horyzont prognozy przecina koniec roku.

`tier` jest kolejnością preferencji, nie ceną. `grid_charge_allowed` jest tylko zgodą kalendarza na **rozważenie** poboru do baterii. Nadal obowiązują prognoza PV, zasady zimowej i letniej pracy, rezerwa SoC, BMS/Deye, pomiary i ograniczenia mocy. Cele SoC powstają dla realnych terminów i zapotrzebowania; taryfa nie narzuca stałego poziomu baterii.

Jednostrefowa G11 nie ma operatorowego terminu końca taniego okna: `charge_window.continuous=true`, granice są puste. Planer może użyć jawnie opisanego terminu planistycznego wynikającego z prognozy i rezerwy. Nie wolno przedstawiać go jako nowej strefy operatora.

Liczba wierszy planu jest niezależna od sześciu fizycznych pozycji Deye TOU. G13active może mieć siedem wierszy po przecięciu doby o północy. Adapter falownika musi zmieścić rzeczywiste dyspozycje w obsługiwanym harmonogramie, łączyć tylko zgodne działania i jawnie zgłaszać niewykonalność; nie może obciąć końca planu ani przesuwać godzin operatora. Parametry zachowania EMS można edytować wewnątrz granic stref, a granice wynikające z taryfy pozostają źródłowe.

Instrukcje Deye pokazują harmonogram **cykliczny**: przykładowe sześć początków 01:00, 05:00, 08:00, 10:00, 15:00 i 18:00 domyka ostatni przedział następnego dnia o 01:00. Potwierdzają to [SG04LP3-EU, instrukcja z 13.08.2024, strona PDF 41 / drukowana 39](https://www.deyeinverter.com/deyeinverter/2024/08/13/instructions_sun-5-12k-sg04lp3-eu_240813_en.pdf#page=41) oraz [SG05LP1-EU 3,6–8 kW, instrukcja z 19.03.2026, strona PDF 37 / drukowana 35](https://www.deyeinverter.com/deyeinverter/2026/03/19/rand/6545/%E3%80%90b%E3%80%91manual_sun-3.6-8k-sg05lp1-eu_20260319_en.pdf#page=37). Zatem ten sam rodzaj strefy po obu stronach północy może należeć do jednego cyklicznego przedziału; północ nie musi zużywać osobnego rejestru. Jest to podstawa sposobu kompilacji, a nie potwierdzenie zachowania konkretnej wersji firmware lub przyjęcia nastaw przez urządzenie.

## Źródła i daty weryfikacji

Katalog sprawdzono13.11.2026. Zapis źródeł obejmuje godziny i warunki ich stosowania; nie odtwarza pełnych dokumentów taryfowych.

- [TAURON Dystrybucja, taryfa2026](https://www.tauron-dystrybucja.pl/-/media/offer-documents/dystrybucja/aktualna-taryfa/taryfa-tauron-dystrybucja-2026_ocr.ashx), strony9,11–13: grupy, godziny, sezony i zegar; s.44: względna kolejność stref G13s. [Opis G13s operatora](https://www.tauron-dystrybucja.pl/grupa-taryfowa-g13s) — warunki licznika i cyklu rozliczeń.
- [PGE Dystrybucja, tekst jednolity od01.02.2026](https://pgedystrybucja.pl/content/download/15f0a79cad0e85c168cd6b8430b4a2e9/file/tekst-jednolity-od-01.02.2026_taryfa-pge-dystrybucja-na-rok-2026.pdf?inLanguage=pol-PL&version=3&contentId=27274), strony10–12,16–17,59. §2.2.9 odsyła szczególne godziny G12e do [obszaru taryfy elastycznej](https://pgedystrybucja.pl/taryfaelastyczna); jego nieodczytany harmonogram nie został zastąpiony źródłem wtórnym.
- [ENEA Operator, aktualny wyciąg01.10–31.12.2026](https://www.operator.enea.pl/media/5191/enea-operatorwyciag-z-taryfy01102026-31122026pdf.pdf), strony2–3: godziny,12miesięcy G13active i zegar; [pełna taryfa2026 z decyzją URE](https://www.operator.enea.pl/media/3259/uslugi-dystrybucyjne/decyzja-prezesa-ure-z-dnia-17-grudnia-2025-rpdf.pdf). Konkretne godziny G12 potwierdza [FAQ operatora](https://www.operator.enea.pl/obsluga-klienta/pytania-i-odpowiedzi).
- [ENERGA-OPERATOR, taryfa2026](https://cdn-netpr.pl/file/mediakit/2933024/8/20251217_taryfa_2026.pdf), strony8,12; [oficjalna strona taryfy](https://energa-operator.pl/uslugi/oplaty-i-faktury/taryfa) potwierdza okres01.01–31.12.2026.
- [PGE Energetyka Kolejowa, taryfa dystrybucyjna2026 zatwierdzona19.12.2025](https://bip.ure.gov.pl/download/3/20368/PGEEnergetykaKolejowaSA.pdf), strony drukowane taryfy9–10,13. Skan tabel sprawdzono wizualnie. [Decyzja URE07.04.2026](https://bip.ure.gov.pl/download/3/20661/PGEEnergetykaKolejowa.pdf) zmienia nazwę na PGE Energetyka Kolejowa Operator, zachowując taryfę. To inny operator niż PGE Dystrybucja i inny dokument niż taryfa sprzedaży.
- [Ustawa o dniach wolnych, tekst jednolity Dz.U.2025poz.296](https://api.sejm.gov.pl/eli/acts/DU/2025/296/text.pdf), strona2, w tym Wigilia od2025r.

Stoen nie należy do wybranego przez użytkownika zakresu pięciu operatorów i nie jest obecny w katalogu2.1.0.
