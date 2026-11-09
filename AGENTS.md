# Deye EMS — samodzielna integracja

- Użytkownik chce niezależny, instalowalny custom component HA z własnym silnikiem i maksymalnie prostym panelem. Bez EMHASS, helperów i automatyzacji pomocniczych.
- Publikacja wyłącznie prywatnie: gaszu/ha-deye-ems. Nie publikuj danych dostępu ani bieżącej/historii telemetrii domu.
- Podstawą pierwszej wersji są dotychczasowe mechanizmy sezonowe, datowany cache prognoz, profil LOAD i odbiorników, sloty G13 i Deye/YamBMS. Dalsze strojenie później.
- Minimalny bezpieczny SoC to osobna trwała konfiguracja, domyślnie40%, zakres40–90%. Cele pogodowe i sieciowe nie mogą obniżać tego progu. Domyślne limity:12kW razem,5kW na fazę,108A/BMS.
- Dodatkowe zużycia: lista nazw i liczników energii, opcjonalnie mocy; included_in_load zapobiega podwójnemu liczeniu. Domyślny PC obejmuje całą pompę, nie jedną fazę.
- Pierwszy start tylko shadow/obserwacja. Zmiany wyjść i odbiorników wymagają obserwacji. Nie wyłączaj innego regulatora automatycznie.
- Zwykła praca i restart wymagają zachowania zapamiętanych właścicieli OFF. Jawne ponowne przejęcie pozwala po świadomym usunięciu starego EMS przyjąć aktualną listę istniejących właścicieli.
- Po instalacji i zweryfikowanym przejęciu użytkownik chce USUNĄĆ automatyzacje, helpery, sensory i dashboardy OBU poprzednich EMS; nie poprzestawać na OFF. Najpierw sporządź dokładny aktualny inwentarz i odtwarzalną kopię lokalną. Nie usuwaj niezwiązanych funkcji domu ani sterowników źródłowych ESPHome/MQTT/YamBMS/Recorder/PV.
- Rozróżniaj model, wybrany cel, próbę polecenia, odczyt nastawy i fizyczną reakcję. Nie obiecuj idealnego zera importu ani fizycznego SoC.
- Obecna dokumentacja potwierdza122testyPython+14panelu offline; natywny start HA i sprzęt wymagają osobnego odczytu. Nie opisuj samego opublikowania ZIP jako wdrożenia produkcyjnego.
- Po zmianie zbudujZIP build_release.py i zsynchronizuj prywatne repo, weryfikując treść/blobSHA. Nie kopiuj plików z nadrzędnego starego projektu jako zależności runtime.
