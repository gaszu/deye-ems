# Sprawdzenia wersji 0.1.0

Data: 10 listopada 2026, Europe/Warsaw.

- 122 testy Python PASS: planer, limity i rampa, cache, pomiary slotów, runtime, start/reload integracji oraz bezpieczna konfiguracja.
- 14 testów panelu Node.js PASS: prosty widok, brak fikcyjnych zer, XSS, błędy poleceń, zachowanie edytowanych pól i wyścigi odpowiedzi.
- Sprawdzono składnię Python/JSON/JavaScript, komplet platform, manifest i strukturę ZIP.
- Sprawdzono wizualnie panel w przeglądarce na danych syntetycznych; zapis rezerwy 55% w podglądzie aktualizuje widok. Nie jest to zmiana ustawienia HA.
- Porównano użyte API instalacji, panelu i Recorder z kodem HA Core 2026.11.0.

Testy runtime i cyklu życia podstawiają framework HA na granicy API; rzeczywiste funkcje planera i regulatora są wykonywane. Nie jest to potwierdzenie załadowania na serwerze HA ani fizycznego wykonania przez Deye. Pierwszy start w HA odbywa się w obserwacji.

Paczka nie zawiera tokenów, haseł ani historii domu. Przykłady i testy są syntetyczne.
