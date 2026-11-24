# Walidacja i publikacja

[Validate integration](workflows/validate.yml) uruchamia kontrole repozytorium. [Test and release integration](workflows/release.yml) wykonuje także testy Pythona i panelu, buduje paczkę w `dist/` i publikuje ją jako załącznik nowego wydania na `main`. Notatki wydania powinny odpowiadać wersji w manifeście. Istniejące wydanie zachowuje swój tag i pliki.
