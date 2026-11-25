# Podgląd panelu Deye EMS

Menu górne prowadzi do głównych widoków. Menu boczne zawiera odnośniki do sekcji, a na telefonie jest dostępne pod przyciskiem „Sekcje”.

Kafelki układu pod podsumowaniem pokazują moc i kierunek przepływu portu GRID, a w trybie CT także przyłącza. Odczyty faz są na tych samych kafelkach. Zielony oznacza poprawny stan, czerwony błąd, żółty informację, a niebieski grupuje odczyty odbiorów.

Podgląd dokumentuje wydanie **2.6.2** i ładuje panel z bieżącego drzewa kodu.

Podgląd dobiera identyfikator i wersję z załadowanego komponentu panelu, więc pokazuje interfejs z bieżącego drzewa kodu.

Podgląd uruchamia ten sam komponent interfejsu co integracja, z przykładowymi
danymi i symulowanymi odpowiedziami. Nie łączy się z Home Assistantem,
Solcastem ani falownikiem. Nie wpisuj prawdziwych kluczy API.

Uruchom w katalogu głównym integracji:

```console
python -m http.server 8786 --bind 127.0.0.1 --directory .
```

- Panel: <http://127.0.0.1:8786/preview/>
- Przykład w szerokości telefonu: <http://127.0.0.1:8786/preview/phone.html>

Przełączniki nad panelem pozwalają porównać motyw, LOAD/CT, różne liczby
przedziałów taryfy i brakujące prognozy. Są to przykłady do oceny interfejsu;
nie zastępują kalendarza operatora obliczanego przez integrację.

Koło oznacza **cel ładowania** w przedziale dopuszczającym doładowanie albo
**minimalny zapas** w przedziale chronionym. Aktualny SoC i prognoza mają
osobne opisy. Brak danych pozostaje pustym wskaźnikiem, a cele zachowawcze
mają oznaczenie. Przedziały dobiera silnik według wybranej taryfy; panel nie
zakłada stałej liczby sześciu slotów.

Otwarcie podglądu nie instaluje ani nie aktualizuje integracji w HA.

Górny pasek Home Assistant daje dostęp do natywnego menu bocznego oraz do przeglądu i ustawień HA. Odrębne menu EMS prowadzą do sekcji panelu.
