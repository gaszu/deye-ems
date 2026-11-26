# Taryfy i harmonogram sterowania Deye EMS

Opis dotyczy wydania [Deye EMS 2.6.10](https://github.com/gaszu/deye-ems/releases/tag/v2.6.10). Nową konfigurację można zapisać dla **TAURON Dystrybucja G11, G12, G12w lub G13**. Wybierz profil zgodny z umową i potwierdź zegar licznika. EMS używa profilu do planowania i sterowania ładowaniem. Rozliczenie energii odbywa się zgodnie z umową z dostawcą. [Dostępne profile](custom_components/deye_ems/tariff_settings.py)

## Godziny zapisane w profilach EMS

Godziny w tabeli odnoszą się do wybranego zegara taryfowego. Profile TAURON w tej wersji mają zakres ważności od 1 stycznia do 31 grudnia 2026 r. Po upływie ważności EMS blokuje sterowanie oparte na wygasłym profilu do czasu wyboru i potwierdzenia aktualnego kalendarza. [Katalog profili i źródeł](custom_components/deye_ems/tariff_profiles.json)

| Profil | Okna taryfowe używane przez EMS | Weekendy i święta ustawowe |
| --- | --- | --- |
| **G11** | Jedna strefa przez całą dobę. | Ta sama strefa każdego dnia. Panel opisuje ją jako taryfę jednostrefową. |
| **G12** | Niższa strefa 13:00–15:00 oraz 22:00–06:00. | Te same godziny każdego dnia. |
| **G12w** | W dni robocze niższa strefa 13:00–15:00 oraz 22:00–06:00. | Niższa strefa przez całe soboty, niedziele i święta ustawowe w zegarze licznika. |
| **G13** | Szczyt poranny 07:00–13:00. Szczyt wieczorny 16:00–21:00 od października do marca oraz 19:00–22:00 od kwietnia do września. Pozostałe godziny są pozaszczytowe w harmonogramie EMS. | EMS stosuje te same godziny sterowania przez cały dany sezon. |

## Zegar licznika i rodzaj dnia

- **Czas lokalny** stosuje godziny stref bezpośrednio w strefie Europe/Warsaw, z automatyczną zmianą czasu.
- **Stały CET** stosuje UTC+01:00 przez cały rok. Latem granice stref mogą wypadać o godzinę później na lokalnym zegarze. Doba widoczna w panelu jest warszawska, więc przy stałym CET może obejmować fragmenty dwóch dat taryfowych.

W sekcji **Plan na dziś i jutro** panel oznacza dzień roboczy, weekend albo święto ustawowe według daty lokalnej. Komunikat **Tania strefa przez całą dobę** pojawia się, gdy niska strefa potwierdzonego harmonogramu faktycznie pokrywa całą dobę widoczną w panelu. Dzień wolny udzielony indywidualnie przez pracodawcę nie jest świętem ustawowym w kalendarzu EMS.

## Wpływ taryfy na plan i falownik

Kalendarz wskazuje, w których przedziałach planer może rozważyć ładowanie z sieci. Planer wylicza cele SoC na podstawie prognozy PV, historii zużycia i rezerwy baterii. Jeżeli ma odpowiednią historię, może wyliczyć inny cel dla weekendu nawet przy jednakowych godzinach sterowania G13. Prognoza zużycia nie zmienia reguł taryfy.

Sześć slotów TOU falownika odwzorowuje techniczny szablon doby. Podział na sloty może rozdzielić jedną strefę taryfową na kilka części. Grid Charge zależy od dopuszczenia danego slotu oraz warunków sterowania. Bieżący prąd EMS dobiera z uwzględnieniem celu i limitów instalacji oraz BMS. Sam komunikat o taniej strefie przez całą dobę nie oznacza ciągłego ładowania. [Opis regulacji i konfiguracji](INSTALL.md)

## Istniejące profile i archiwum

Silnik zachowuje wcześniej zapisane profile zgodnie z ich dostępnością, ważnością i regułami. Dotychczasowy własny harmonogram `legacy_g13` jest oddzielnym profilem od TAURON G13. Pełny katalog, w tym profile innych operatorów, jest dostępny w źródłach. Historyczne zestawienia i źródła są dostępne w archiwalnej wersji dokumentu. [Katalog profili](custom_components/deye_ems/tariff_profiles.json) · [Archiwalna dokumentacja](https://github.com/gaszu/deye-ems/blob/c20c92cac6ffbd62432102594d39d0a02f7487ef/TARIFFS.md)
