# Deye EMS

[Polski](#polski) · [English](#english) · [Wydania / Releases](https://github.com/gaszu/deye-ems/releases)

## Polski

**Deye EMS to lokalny system zarządzania energią dla Home Assistant, przeznaczony do instalacji z hybrydowym falownikiem Deye i magazynem energii.** Wyznacza cele naładowania baterii (SoC) na podstawie prognozy produkcji PV, przewidywanego zużycia domu, taryfy i zadanej rezerwy. Następnie dopasowuje ładowanie z sieci do bieżących warunków. Silnik działa w Home Assistant. Solcast jest opcjonalnym źródłem prognozy PV.

### Jak działa

1. **Planowanie.** EMS łączy prognozę PV, profil zużycia z historii Home Assistant i kalendarz taryfy. Panel pokazuje prognozę SoC, cele ładowania i plan na dziś oraz jutro.
2. **Sterowanie.** W slotach dopuszczających ładowanie EMS zarządza ustawieniem Grid Charge i reguluje prąd. Bierze pod uwagę aktualne pomiary, dostępną moc, limity falownika i przyłącza oraz ograniczenia BMS. W dozwolonym oknie nocnym priorytetem jest osiągnięcie porannego celu SoC. Po osiągnięciu celu histereza zapobiega częstemu wznawianiu ładowania.
3. **Zabezpieczenia.** Ustawienia rezerwy, stan baterii, aktualność pomiarów i zgodność odczytów z konfiguracją ograniczają działanie regulatora. Tryb obserwacji pokazuje plan i diagnostykę bez przejmowania sterowania falownikiem.
4. **TOP BALANCE.** Operator może zadać własny cel SoC do 100%, w zakresie akceptowanym przez falownik, i uruchomić ładowanie z sieci także w drogiej strefie. EMS respektuje limity instalacji i BMS. Po osiągnięciu celu lub ręcznym zakończeniu przywraca nastawy slotu i wraca do zwykłego planu. Balansowaniem ogniw zajmuje się BMS.

### Zintegrowany Solcast

Deye EMS ma własnego klienta Solcast API, dostępnego z panelu Home Assistant. Można skonfigurować jedną lub kilka instalacji PV, ustalić odstęp pobierania i dopasować budżet zapytań do konta. Panel pokazuje prognozy P50 i P10 na dziś, pozostałą część dnia i jutro oraz wskazuje, czy dane pochodzą z API, lokalnego cache czy encji Home Assistant. EMS sprawdza aktualność i pokrycie prognozy przed użyciem jej do planowania. Można też korzystać z prognozy udostępnianej przez istniejące encje Home Assistant. [Konfiguracja Solcast](INSTALL.md#solcast--konfiguracja-w-panelu)

### Falowniki i układy pomiarowe

Katalog zawiera profile wybranych europejskich, niskonapięciowych falowników hybrydowych Deye. Przy konfiguracji wybierz dokładny model z listy.

| Rodzina | Fazy | Zakres mocy modeli w katalogu |
| --- | --- | --- |
| SUN-SG04LP1-EU | 1 | 3–6 kW |
| SUN-SG05LP1-EU-SM2-P | 1 | 3,6–10 kW |
| SUN-SG04LP3-EU | 3 | 5–12 kW |
| SUN-SG05LP3-EU-SM2 | 3 | 3–20 kW |

Konfiguracja własna pozwala ręcznie określić parametry falownika i przypisać wymagane encje. Integracja obsługuje **Zero Export To Load**, gdzie dom jest mierzony na wyjściu LOAD, oraz **Zero Export To CT**, gdzie osobne odczyty portu GRID i licznika CT pozwalają uwzględnić również odbiorniki między falownikiem a przyłączem. Możliwość sterowania zależy od dostępności wymaganych pomiarów i nastaw TOU w Home Assistant. [Katalog modeli](custom_components/deye_ems/inverter_models.py)

### Taryfy

Do nowej konfiguracji można wybrać **TAURON Dystrybucja G11, G12, G12w i G13**. Kalendarz stosuje reguły danego profilu, w tym sezonowość, dni tygodnia i święta tam, gdzie przewiduje je taryfa. Przy zapisie trzeba potwierdzić zgodność profilu z umową oraz wybrać sposób pracy zegara licznika. Katalog zawiera też profile informacyjne innych operatorów i zachowuje wcześniej zapisane profile zgodnie z ich regułami. Zakres dostępny dla nowej konfiguracji określa selektor taryf. [Katalog taryf](custom_components/deye_ems/tariff_profiles.json) · [Reguły wyboru](custom_components/deye_ems/tariff_settings.py)

### Bateria, BMS i YamBMS

- **Deye** jest domyślnym źródłem danych. EMS odczytuje z encji falownika SoC, napięcie, bieżący limit prądu ładowania oraz alarmy i błędy baterii dostępne z komunikacji falownika z BMS.
- **YamBMS** jest opcjonalnym źródłem danych magazynu. Może udostępniać zagregowany SoC, napięcie, limit prądu i blokadę ładowania z jednego lub kilku BMS. EMS odczytuje te dane z encji Home Assistant, a polecenia ładowania nadal przekazuje falownikowi Deye.
- **Ręczne przypisanie** pozwala wskazać encje z własnej integracji BMS. Przy sprzęcie takim jak JK-BMS zgodność zależy od tego, czy Deye, YamBMS lub osobna integracja poprawnie udostępnia wymagane pomiary oraz sygnały blokady lub alarmu.

### Instalacja i dokumentacja

Zainstaluj integrację przez Marketplace albo użyj paczki ZIP z opublikowanego wydania. Po dodaniu integracji panel Deye EMS jest dostępny w menu bocznym administratora.

[Instrukcja instalacji](INSTALL.md) · [Specyfikacja silnika](SPECIFICATION.md) · [Podgląd na danych syntetycznych](preview/README.md) · [Wydania](https://github.com/gaszu/deye-ems/releases)

## English

**Deye EMS is a local energy management system for Home Assistant installations with a Deye hybrid inverter and battery storage.** It sets battery state-of-charge (SoC) targets using the PV forecast, expected household demand, the electricity tariff and a configured reserve. It then adjusts grid charging to measured conditions. The engine runs in Home Assistant. Solcast is an optional source of PV forecasts.

### How it works

1. **Planning.** The engine combines the PV forecast, a demand profile derived from Home Assistant history and the tariff calendar. The dashboard shows the projected SoC, charge targets and the plan for today and tomorrow.
2. **Control.** In slots that allow grid charging, EMS manages the inverter’s Grid Charge setting and adjusts the charge current. It uses live measurements, available power, inverter and service connection limits, and BMS constraints. During an eligible overnight window, it prioritises the morning SoC target. After reaching the target, hysteresis avoids frequent restarts.
3. **Safeguards.** The battery reserve, battery status, measurement freshness and consistency with the configured installation all constrain control. Observation mode shows the plan and diagnostics without taking control of the inverter.
4. **TOP BALANCE.** An operator can set an SoC target up to 100%, within the inverter’s accepted range, and start grid charging even during an expensive tariff period. EMS respects installation and BMS limits. When the target is reached or the operator stops the session, EMS restores the slot settings and resumes the normal plan. The BMS handles cell balancing.

### Built-in Solcast

Deye EMS includes a Solcast API client configured from its Home Assistant panel. You can configure one or more PV sites, set the polling interval and match the request budget to your account. The panel shows P50 and P10 forecasts for today, the rest of today and tomorrow, and identifies whether the data came from the API, the local cache or Home Assistant entities. EMS checks forecast freshness and coverage before using it to plan charging. Forecasts exposed by existing Home Assistant entities are also supported. [Solcast setup](INSTALL.md#solcast--konfiguracja-w-panelu)

### Inverters and metering layouts

The catalogue includes profiles for selected European low-voltage Deye hybrid inverters. Choose the exact model during setup.

| Family | Phases | Power range of listed models |
| --- | --- | --- |
| SUN-SG04LP1-EU | 1 | 3–6 kW |
| SUN-SG05LP1-EU-SM2-P | 1 | 3.6–10 kW |
| SUN-SG04LP3-EU | 3 | 5–12 kW |
| SUN-SG05LP3-EU-SM2 | 3 | 3–20 kW |

A custom profile allows manual entry of inverter parameters and mapping of the required entities. The integration supports **Zero Export To Load**, where household demand is measured at the LOAD output, and **Zero Export To CT**, where separate GRID-port and CT readings also account for loads between the inverter and the service connection. Control requires the relevant measurements and writable Time of Use (TOU) settings in Home Assistant. [Inverter catalogue](custom_components/deye_ems/inverter_models.py)

### Tariffs

New configurations can select **TAURON Dystrybucja G11, G12, G12w and G13**. The calendar applies each profile’s rules, including seasons, weekdays and public holidays where relevant. Setup asks the operator to confirm that the tariff matches their contract and to select the meter’s clock basis. The catalogue also contains reference profiles for other operators. Existing saved profiles are retained according to their own rules. The tariff selector determines which profiles are available for new configurations. [Tariff catalogue](custom_components/deye_ems/tariff_profiles.json) · [Selection rules](custom_components/deye_ems/tariff_settings.py)

### Battery, BMS and YamBMS

- **Deye** is the default battery data source. EMS reads the SoC, voltage, current charge limit, alarms and faults that the inverter exposes from its BMS link.
- **YamBMS** is an optional battery data source. It can expose aggregate SoC, voltage, charge current limit and charge blocking from one or more BMS units. EMS reads those Home Assistant entities and continues to send charge commands to the Deye inverter.
- **Manual mapping** allows entities from a separate BMS integration. With hardware such as JK-BMS, compatibility depends on whether Deye, YamBMS or another integration exposes the required measurements and charge-blocking or alarm signals correctly.

### Installation and documentation

Install through Marketplace or use the ZIP from a published release. Once the integration has been added, the Deye EMS panel appears in the administrator’s sidebar.

[Installation guide](INSTALL.md) · [Engine specification](SPECIFICATION.md) · [Demo with synthetic data](preview/README.md) · [Releases](https://github.com/gaszu/deye-ems/releases)
