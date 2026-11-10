# Deye EMS — samodzielna integracja

- Użytkownik chce niezależny, instalowalny custom component HA z własnym silnikiem i maksymalnie prostym panelem. Bez EMHASS, helperów i automatyzacji pomocniczych.
- Użytkownik zatwierdził PUBLICZNY kod gaszu/ha-deye-ems, aby umożliwić instalację przez Marketplace na innych instancjach HA. Tylko ten projekt może być publiczny; pozostałe repozytoria starego EMS i indywidualne dane pozostają prywatne. Nie publikuj danych dostępu ani bieżącej/historii telemetrii domu.
- Podstawą pierwszej wersji są dotychczasowe mechanizmy sezonowe, datowany cache prognoz, profil LOAD i odbiorników, sloty G13 i Deye/YamBMS. Dalsze strojenie później.
- Minimalny bezpieczny SoC to osobna trwała konfiguracja, domyślnie40%, zakres40–90%. Cele pogodowe i sieciowe nie mogą obniżać tego progu. Domyślne limity:12kW razem,5kW na fazę,108A/BMS.
- Dodatkowe zużycia: lista nazw i liczników energii, opcjonalnie mocy; included_in_load zapobiega podwójnemu liczeniu. Domyślny PC obejmuje całą pompę, nie jedną fazę.
- Pierwszy start tylko shadow/obserwacja. Zmiany wyjść i odbiorników wymagają obserwacji. Nie wyłączaj innego regulatora automatycznie.
- Zwykła praca i restart wymagają zachowania zapamiętanych właścicieli OFF. Jawne ponowne przejęcie pozwala po świadomym usunięciu starego EMS przyjąć aktualną listę istniejących właścicieli.
- Po instalacji i zweryfikowanym przejęciu użytkownik chce USUNĄĆ automatyzacje, helpery, sensory i dashboardy OBU poprzednich EMS; nie poprzestawać na OFF. Najpierw sporządź dokładny aktualny inwentarz i odtwarzalną kopię lokalną. Nie usuwaj niezwiązanych funkcji domu ani sterowników źródłowych ESPHome/MQTT/YamBMS/Recorder/PV.
- Rozróżniaj model, wybrany cel, próbę polecenia, odczyt nastawy i fizyczną reakcję. Nie obiecuj idealnego zera importu ani fizycznego SoC.
- Wbudowany klient Solcast jest częścią integracji; osobna integracja solcast_solar nie jest wymagana. Klucz i konfiguracja źródła pozostają prywatne w ConfigEntry. Panel, plan, cache, diagnostyka ani publiczne repo nie mogą zawierać klucza. Limit konta jest na dobę UTC, zapis próby przed HTTP; zmiana źródła nie zeruje wykorzystanego limitu.
- Prognoza całej instalacji pozostaje1:1. Moc PV kWp jest ustawieniem, cache jest z nią powiązany. Tylko jawny tryb specific_profile skaluje przez stosunek mocy. Parametry geometrii Hobbyist ustawia się w Solcast Toolkit, nie komercyjnym API.
- Pobieranie prognoz i Recorder nie może blokować bieżącej regulacji ładowania. Testy offline opisuje VALIDATION.md; natywny start HA i sprzęt wymagają osobnego odczytu. Nie opisuj samego opublikowania ZIP jako wdrożenia produkcyjnego.
- Po zmianie zbudujZIP build_release.py i zsynchronizuj repo, weryfikując treść/blobSHA. Nie kopiuj plików z nadrzędnego starego projektu jako zależności runtime.
