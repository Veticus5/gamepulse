# GamePulse: wersja demo

Statyczna strona pokazowa. Nie wymaga serwera, Pythona ani bazy danych.

## Jak otworzyć

Otwórz plik `index.html` w przeglądarce (dwuklik albo przeciągnięcie do okna).

Bez internetu wszystko działa, tylko zamiast okładek gier widać kolorowe pola,
bo obrazki pochodzą z serwerów Steama.

## Co pokazuje

- listę sześciu gier z liczbą graczy i odsetkiem pozytywnych ocen,
- stronę gry: wykres ocen z zaznaczonymi nietypowymi okresami, opis każdego
  takiego okresu z przyczyną i dowodami, wykres liczby graczy i ostatnie
  ogłoszenia twórców.

Dane to prawdziwy zrzut z projektu, zapisany w `data.js`. Przyczyny wskazał
lokalny model na podstawie recenzji, ogłoszeń i cen; mogą być błędne.

## Jak odświeżyć dane

Na komputerze z pełnym projektem, z katalogu głównego:

    uv run gamepulse model
    uv run python demo/build_data.py

Listę gier ustawia się w `build_data.py` (stała `GAMES`).

## Pliki

- `index.html`, `style.css`, `app.js`: strona, bez zewnętrznych bibliotek,
- `data.js`: dane,
- `build_data.py`: eksport danych z tabel projektu.
