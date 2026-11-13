# Podgląd panelu Deye EMS

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
