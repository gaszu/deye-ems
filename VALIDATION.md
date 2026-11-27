# Walidacja Deye EMS

Regresja trybu CT sprawdza 13 kW na przyłączu i 6 kW na porcie GRID oraz blokadę sterowania po utracie wewnętrznego CT.

Automatyczne sprawdzenia obejmują testy silnika w Pythonie, testy panelu w Node.js oraz walidację Hassfest i HACS. Wynik konkretnego wydania jest widoczny w przebiegu GitHub Actions przypisanym do jego commitu.

Przy weryfikacji panelu 2.7.1 przejdź do każdej sekcji z menu i sprawdź podczas przewijania, czy poprzednie karty znikają przed półprzezroczystym paskiem. Testy obejmują szybkie zimowe ładowanie G13 od 13:00 do 16:00 i uruchomienie TOP BALANCE bez zwykłej zwłoki. Testy regulacji sprawdzają komunikat o braku zapasu na fazie, na całym przyłączu lub na porcie GRID falownika przy świeżych pomiarach i pomijalnej mocy ładowania. Zestaw sprawdza też, że brak historii jednego licznika nie blokuje pozostałych ani nie zwiększa prognozy przez podwójne doliczenie energii. Zestaw obejmuje także test niezależnej akceptacji celu porannego i test komunikatu ryzyka P10/P50. Regresja kalendarza obejmuje rozpoznanie weekendu i święta, całodobową niską strefę G12w, zwykły sezonowy harmonogram G13 oraz rozróżnienie taryfy płaskiej G11. Testy korzystają z danych syntetycznych. Stan wdrożenia i fizyczna odpowiedź falownika wymagają osobnej weryfikacji na danej instalacji.

- [Przebiegi walidacji i publikacji](https://github.com/gaszu/deye-ems/actions/workflows/release.yml)
- [Wydanie 2.7.1](https://github.com/gaszu/deye-ems/releases/tag/v2.7.1)
- [Archiwalne raporty walidacji](https://github.com/gaszu/deye-ems/blob/761398b9f798db75a2ebb71f777dad0f84eb1fad/VALIDATION.md)
