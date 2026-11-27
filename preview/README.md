# Podgląd panelu Deye EMS

Menu boczne EMS zawiera odnośniki do sekcji. Na telefonie jest dostępne pod przyciskiem „Sekcje”.

Kafelki układu pod podsumowaniem pokazują moc i kierunek przepływu portu GRID, a w trybie CT także przyłącza. Odczyty faz są na tych samych kafelkach. Zielony oznacza poprawny stan, czerwony błąd, żółty informację, a niebieski grupuje odczyty odbiorów.

Podgląd dokumentuje wydanie **2.7.1** i ładuje panel z bieżącego drzewa kodu. Boczne menu przewija do sekcji, a karty znikają pod paskiem sterowania z zachowaniem odstępu również podczas ręcznego przewijania.

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

Widok Lovelace korzysta z natywnego paska i menu Home Assistant. W panelu EMS jego boczne menu prowadzi do sekcji. Pasek przycisków sterowania pozostaje widoczny przy przewijaniu.

Prognozę i licznik zapytań pokazuje wspólna sekcja Solcast. Podsumowanie i cele SoC używają kolorowych kafelków w stylu sekcji LOAD/CT.

Kafelki limitów i bieżącego prądu ładowania są pod układem LOAD/CT. Prąd jest wyliczany z mocy i napięcia DC baterii.
