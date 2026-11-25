# Walidacja Deye EMS

Automatyczne sprawdzenia obejmują testy silnika w Pythonie, testy panelu w Node.js oraz walidację Hassfest i HACS. Wynik konkretnego wydania jest widoczny w przebiegu GitHub Actions przypisanym do jego commitu.

Testy wydania **2.4.2** sprawdzają komunikat o braku zapasu na fazie przy świeżych pomiarach i pomijalnej mocy ładowania. Zestaw sprawdza też, że brak historii jednego licznika nie blokuje pozostałych ani nie zwiększa prognozy przez podwójne doliczenie energii. Zestaw obejmuje także test niezależnej akceptacji celu porannego i test komunikatu ryzyka P10/P50. Regresja kalendarza obejmuje rozpoznanie weekendu i święta, całodobową niską strefę G12w, zwykły sezonowy harmonogram G13 oraz rozróżnienie taryfy płaskiej G11. Testy korzystają z danych syntetycznych. Stan wdrożenia i fizyczna odpowiedź falownika wymagają osobnej weryfikacji na danej instalacji.

- [Przebiegi walidacji i publikacji](https://github.com/gaszu/deye-ems/actions/workflows/release.yml)
- [Wydanie 2.4.2](https://github.com/gaszu/deye-ems/releases/tag/v2.4.2)
- [Archiwalne raporty walidacji](https://github.com/gaszu/deye-ems/blob/761398b9f798db75a2ebb71f777dad0f84eb1fad/VALIDATION.md)
