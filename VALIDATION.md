# Sprawdzenia wersji 1.0.0

Data: 10 listopada 2026, Europe/Warsaw.

- 202 testy Python PASS: planer, limity i rampa, cache, pomiary slotów, runtime, start/reload integracji, konfiguracja i wbudowany klient oraz importer Solcast.
- 14 testów panelu Node.js PASS: prosty widok, brak fikcyjnych zer, XSS, błędy poleceń, zachowanie edytowanych pól i wyścigi odpowiedzi.
- Sprawdzono składnię Python/JSON/JavaScript, komplet platform, manifest i strukturę ZIP.
- Sprawdzono wizualnie panel w przeglądarce na danych syntetycznych; zapis rezerwy 55% w podglądzie aktualizuje widok. Nie jest to zmiana ustawienia HA.
- Porównano użyte API instalacji, panelu i Recorder z kodem HA Core 2026.11.0.
- Solcast: quota UTC przed HTTP, restart i zmiana źródła bez zerowania limitu, pełne pokrycie prognozy, błędy API, import korekt i brak klucza w panelu/cache/planie. HTTP jest atrapą; nie wykonano testu prawdziwym kluczem.
- Symulowane zablokowane pobieranie HTTP nie zatrzymuje regulacji: przy przeciążeniu żądanie prądu spada do 0 A w wywołaniu trwającym poniżej 0,5 s. Sprawdzono anulowanie zadania oraz odrzucenie planu dla nieaktualnej konfiguracji.
- Niższa skonfigurowana moc falownika i fazy ogranicza prąd oraz model niezależnie od wyższych limitów sieci.
- Import 24/48 współczynników zachowuje prawdziwe zero, odrzuca braki, uwzględnia pierwszeństwo ALL/global i wykluczenia. Korekty są stosowane tylko do surowego API, bez ponownego mnożenia skorygowanych prognoz HA.

Testy runtime i cyklu życia podstawiają framework HA na granicy API; rzeczywiste funkcje planera i regulatora są wykonywane. Nie jest to potwierdzenie załadowania na serwerze HA ani fizycznego wykonania przez Deye. Pierwszy start w HA odbywa się w obserwacji.

Paczka nie zawiera tokenów, haseł ani historii domu. Przykłady i testy są syntetyczne.
