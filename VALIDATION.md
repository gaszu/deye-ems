# Sprawdzenia wersji 1.0.5

- **289/289 testów Python PASS** i **60/60 testów panelu PASS**.
- Preferencja wyglądu ma osobny Store. Testy obejmują walidację dostępnych nazw motywów, admin-only WebSocket, trwały zapis przed publikacją, błąd zapisu bez zmiany wartości oraz serializację równoległych zapisów. Błąd odczytu kosmetycznej preferencji nie blokuje startu sterownika.
- Zapis wyglądu w active nie wywołuje koordynatora, przeładowania, planowania ani usług urządzeń. Konfiguracja energii i połączenia Solcast pozostaje oddzielona.
- Testy interfejsu obejmują lokalny CSSOM hosta, base i reguły trybu light/dark, odwołania zmiennych, wartości RGB, usuwanie starych kluczy i powrót do dziedziczenia profilu. Brak motywu nie powoduje automatycznego zapisu innej preferencji.
- Sprawdzono zachowanie wyboru przy odświeżaniu, bezpieczne wyświetlanie nazw motywów i zachowanie poprzedniego wyglądu po błędzie zapisu. Kod nie zmienia motywu dokumentu ani globalnego profilu HA.
- W przeglądarce na syntetycznych danych sprawdzono zastosowanie motywu z obrazem tła i półprzezroczystymi kartami, zapis innego motywu w jasnym trybie, usunięcie lokalnych zmiennych przy powrocie do dziedziczenia oraz ponowne zastosowanie wybranego motywu. Kolory podglądu pochodzą z definicji motywu, bez własnego przemalowywania.

## Sprawdzenia wersji 1.0.4

Wyniki dotyczą testów oprogramowania offline i syntetycznych scenariuszy przeglądarkowych. Nie stanowią raportu z konkretnej instalacji HA ani potwierdzenia fizycznej reakcji falownika.

## Wyniki

- **279/279 testów Python PASS**.
- **48/48 testów panelu PASS**.
- Podgląd i obsługa przeglądarki zostały sprawdzone na danych syntetycznych, bez połączenia z produkcyjnym HA i bez użycia rzeczywistego konta Solcast.

Testy runtime zastępują framework HA na granicy API, wykonując rzeczywiste funkcje planera, regulatora i obsługi stanu. HTTP Solcast i usługi HA są atrapami; nie potwierdzają wykonania polecenia przez sprzęt.

## Kreator Solcast

Sprawdzono natywny options flow, menu, formularze i ograniczenia schematów selectorów. Panel korzysta z POST/DELETE kreatora HA, a zapis konfiguracji pozostaje w options flow integracji.

Scenariusze obejmują:

- Otwarcie i anulowanie bez przełączenia źródła; usunięcie niezakończonego flow po anulowaniu, odłączeniu panelu i spóźnionej odpowiedzi.
- Zapis ręczny włączający klienta API oraz osobne potwierdzenie jego wyłączenia.
- Zachowanie szkicu po błędzie walidacji, kompletność pól i obsługę importu kalibracji.
- Brak zapisanego klucza w formularzu i publicznym statusie; prywatną, nietrwałą pamięć nowego klucza oraz czyszczenie jej po zakończeniu lub zamknięciu.
- Brak klucza w HTML `value`, planie, cache i diagnostyce.
- Blokadę anulowania podczas końcowego zapisu i brak automatycznego włączenia sterowania. Stary poprawny plan sprzed zapisu nie odblokowuje przycisku wznowienia.
- Utrwalanie wykorzystania API przed HTTP, rozliczanie doby UTC, błędy API i zachowanie wykorzystania po restarcie lub zmianie konfiguracji.
- Import 24/48 współczynników, wartości zerowych, wykluczeń i pierwszeństwa tabeli globalnej; odrzucanie niepełnej kalibracji.
- Snapshot kalibracji bez migracji dalszego samouczenia i bez automatycznego zatrzymywania innego klienta. Korekty dotyczą tylko surowych odpowiedzi API EMS.

Kontrakt interfejsów porównano z [HA Core 2026.11 — config entries](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/config/config_entries.py) i [data entry flow](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/helpers/data_entry_flow.py). Zasady zewnętrznego API opisuje [dokumentacja Solcast](https://docs.solcast.com.au/docs/section/rooftop-sites-hobbyist).

## Silnik i regulator

Testy obejmują bilans energii, cele sezonowe, datowany cache, profil LOAD, liczniki slotów, warunki fallbacku oraz ograniczenia baterii i falownika. Sprawdzają świeżość i jednostki pomiarów, BMS, faktyczne limity GRID, rozdzielenie limitów importu od mocy konwersji i wybór modelu fazowego na podstawie potwierdzonych ustawień.

Regresje bezpiecznej redukcji obejmują opóźniony odczyt, zmianę limitu podczas zapisu, nieudaną usługę lub zapis, brak dowodu przyjęcia, nieodnawialny limit 30 s, wzrost odczytu, utratę wymaganej flagi, BMS, GRID, stare pomiary, konflikt właściciela i okno chronione. Rejestr próby, przyjęcie usługi i odczyt urządzenia mają osobne znaczenie.

Sprawdzono również, że opóźnione pobieranie prognozy nie blokuje bieżącej regulacji, a wynik planowania nie jest przyjmowany po zmianie jego konfiguracji.

## Odbiorniki, panel i instalacja

Testy dodatkowych zużyć obejmują tworzenie, edycję, usuwanie, trwałe ON/OFF, zachowanie identyfikatorów, walidację jednostek, konflikt wersji listy oraz blokadę zmian w active. Kanały są używane wyłącznie w prognozie SoC i nie podwajają bieżącego LOAD.

Testy panelu obejmują zachowanie szkiców, wyścigi odpowiedzi, zmiany trybu podczas edycji, obsługę błędów, brak fikcyjnych zer i ochronę przed wstawieniem kodu HTML. Podgląd przeglądarki obejmuje kreator Solcast, kalibrację, jawne przejście do obserwacji, osobne wznowienie i potwierdzenie wyłączenia. Pastelowa kolorystyka wykorzystuje zmienne motywu HA; sprawdzono również ciemny podgląd.

Sprawdzenia struktury obejmują platformy integracji, manifest, zgodność wersji panelu, konfigurację WebSocket z autoryzacją administratora oraz strukturę paczki. Specyfikacja silnika pozostaje **1.0.0**; wydanie 1.0.4 dotyczy kreatora i wyglądu panelu.

## Powtórzenie testów

```shell
python -m unittest discover -s tests -q
node tests/test_frontend.cjs
python build_release.py
```

Pełne warunki działania opisuje [SPECIFICATION.md](SPECIFICATION.md), instalację [INSTALL.md](INSTALL.md), a zasady przejścia i powrotu [MIGRATION.md](MIGRATION.md). Wynik testów syntetycznych nie zastępuje sprawdzenia własnych mapowań, pomiarów i reakcji urządzenia.
