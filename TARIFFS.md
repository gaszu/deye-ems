# Kalendarz taryf w 2.0.0

Moduł `tariff_calendar.py` jest niezależną podstawą pod przyszły katalog polskich operatorów i taryf. Nie pobiera cen ani nie zmienia nastaw falownika.

- `legacy_g13` opisuje sześć dotychczasowych slotów EMS, również w weekendy i święta. Dzięki temu instalacja 1.x zachowuje swój harmonogram. Ten profil nie oznacza pełnego odwzorowania taryfy operatora.
- `tauron_g13_2026` jest wyłącznie podglądem zasad TAURON Dystrybucja: rozróżnia sezon, weekendy i święta. Ma `preview_only=true` oraz `runtime_allowed=false`. Nie może zastąpić aktywnej polityki przez samo wyświetlenie podglądu.

Sezon kalendarzowy i zmiana czasu to dwie różne reguły. Podgląd obsługuje zegar lokalny (`local`) oraz stały czas zimowy licznika (`fixed_cet`), prezentując wynik w godzinach lokalnych Warszawy. Przedziały mają granicę końcową wyłączną i są porównywane jako chwile UTC; zmiana czasu daje poprawne doby 23- i 25-godzinne.

`grid_charge_allowed` oznacza tylko zgodność przedziału z polityką kalendarza. Nie zastępuje kontroli SoC, BMS, pomiarów, mocy ani prawidłowości rejestrów. Poza zakresem dat taryfy wynik jawnie wskazuje `within_validity=false`. Kalendarz nie oblicza rozliczenia opustów ani kosztu zakupu.

Kolejny etap obejmie wybór OSD i taryfy, potwierdzenie wariantu zegara, edycję zachowania EMS wewnątrz granic operatora oraz adapter do harmonogramu TOU falownika. Nowe profile będą publikowane po osobnej weryfikacji; 2.0.0 nie deklaruje obsługi wszystkich operatorów i taryf w Polsce.

Źródła:

- [TAURON Dystrybucja — taryfa 2026, pkt 2.2, sezony i czas zegara](https://www.tauron-dystrybucja.pl/-/media/offer-documents/dystrybucja/aktualna-taryfa/taryfa-tauron-dystrybucja-2026_ocr.ashx).
- [Ustawa o dniach wolnych od pracy — tekst jednolity z 2025 r.](https://eli.gov.pl/eli/DU/2025/296/ogl), w tym Wigilia od 2025 r.
