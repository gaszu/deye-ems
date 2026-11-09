# Instalacja Deye EMS

Wymagany Home Assistant **2026.11.0 lub nowszy**. W tej wersji używane są aktualne interfejsy config flow, panelu i walidacji HA. Silnik nie pobiera pakietów spoza HA.

1. Pobierz ZIP z katalogu `dist` tego prywatnego repozytorium.
2. Rozpakuj go. Skopiuj cały katalog `custom_components/deye_ems` do katalogu konfiguracji HA, zwykle `/config/custom_components/deye_ems`.
3. Uruchom ponownie Home Assistant, aby wykrył nową integrację.
4. Otwórz **Ustawienia → Urządzenia i usługi → Dodaj integrację → Deye EMS**.
5. Ustaw minimalny bezpieczny SoC i znane parametry. Dotychczasowe uzgodnione wartości to 40%, 66 kWh, 12 kW łącznie i 5 kW na fazę.
6. Integracja zaczyna w trybie **shadow / obserwacja**. Panel Deye EMS pojawi się w menu bocznym administratora.
7. W **Konfiguruj → Encje pomiarowe i sterujące** sprawdź przypisania. Domyślne identyfikatory odpowiadają obecnej instalacji Adama i można je zastąpić własnymi.
8. W **Dodatkowe zużycia** dodaj odpowiednie liczniki pompy ciepła, CWU, klimatyzacji itd.
9. Porównaj pomiary i cele z działającym EMS. Przejście produkcyjne opisano w [MIGRATION.md](MIGRATION.md).

## Wymagane pomiary

SoC i napięcie tego samego BMS; prąd dopuszczony i blokada BMS; suma i trzy fazy Grid/LOAD; rzeczywista moc baterii; odczyt limitu prądu ładowania. Dynamiczne pomiary mocy muszą być świeże i mieć poprawne jednostki.

Integracja używa standardowego Recorder HA do profilu historycznego LOAD i liczników energii. LOAD zawiera cały dom, w tym pompę ciepła. Zalecana jest co najmniej tygodniowa historia, z minimum trzema porównywalnymi obserwacjami każdej godziny. Brak historii daje jawny fallback.

Prognozy PV są opcjonalnymi danymi planowania; obsługiwany jest format `detailedForecast` z `period_start`, `pv_estimate10`, `pv_estimate`. Cache jest przypisany do konkretnych dat i przedziałów. Brak kompletnych danych nie jest zastępowany fikcyjną produkcją zero.

## HACS / Marketplace

Repozytorium zawiera strukturę `custom_components` i `hacs.json`. Dla prywatnego repozytorium dostęp z HACS zależy od uprawnień jego połączenia GitHub. Instalacja ręczna z ZIP nie wymaga przekazywania tokenu integracji EMS.

## Aktualizacje i usunięcie

Aktualizacja: podmień wyłącznie katalog integracji i uruchom HA ponownie. Nie usuwaj jej konfiguracji ani magazynu runtime, jeżeli chcesz zachować ustawienia i cache.

Przed usunięciem wybierz obserwację. Gdy integracja nadal ma wyłączną kontrolę, świadome przejście z active do shadow próbuje wyłączyć Grid Charge i ustawić prąd sieciowy 0 A; trzeba sprawdzić odczyty urządzenia. Wyładowanie samego kodu nie wysyła poleceń sprzętowych. Ostatnie ustawienia falownika mogą pozostać zapisane, więc jego stan należy zweryfikować.

