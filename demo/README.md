# GamePulse: wersja demo

Statyczna strona pokazowa. Nie wymaga serwera, Pythona ani bazy danych.

## Jak otworzyć

Otwórz plik `index.html` w przeglądarce (dwuklik albo przeciągnięcie do okna).

Bez internetu wszystko działa, tylko zamiast okładek gier widać kolorowe pola,
bo obrazki pochodzą z serwerów Steama.

## Co pokazuje

- **Lista gier** z liczbą graczy i odsetkiem pozytywnych ocen oraz panel
  „Co się zmieniło od Twojej ostatniej wizyty".
- **Strona gry, zakładka Przegląd:** krótkie „Co się dzieje z grą?", wykres
  ocen z zaznaczonymi nietypowymi okresami, opis każdego okresu z przyczyną
  i dowodami, wykres liczby graczy.
- **Zakładka Wiadomości:** ogłoszenia twórców i artykuły prasowe z filtrami
  (aktualizacje, nowa zawartość, problemy techniczne, biznes i ceny, mody,
  opinie).
- **Zakładka O grze:** tryby gry, systemy, języki, funkcje, powiązane
  wydania, cena z historią przecen, recenzje redakcji.
- **Porównaj:** dwie gry obok siebie w liczbach i na wspólnych wykresach.

## Co jest prawdziwe, a co nie

Prawdziwe: liczby graczy, oceny, nietypowe okresy, wyjaśnienia (pisze je
lokalny model, więc mogą być błędne), wiadomości, ceny w USD, dane o grze ze
sklepu Steam.

Na pokaz:

- **Recenzje redakcji.** Tych danych jeszcze nie zbieramy. Redakcje i oceny
  są zmyślone i tak oznaczone na stronie. Wyjątek: wynik Metacritic, gdy
  podaje go Steam.
- **„Ostatnia wizyta".** Zrzut danych jest nieruchomy, więc datę ostatniej
  wizyty wybiera się z listy.
- **Opisy powiązanych wydań** są wpisane ręcznie w `build_data.py`.
- **Kategorie wiadomości** bez etykiety modelu wynikają z prostych reguł na
  tytule i bywają nietrafione.

## Jak odświeżyć dane

Na komputerze z pełnym projektem, z katalogu głównego:

    uv run gamepulse model
    uv run python demo/build_data.py

Listę gier ustawia się w `build_data.py` (stała `GAMES`). Dane o grze ze
sklepu leżą w `store_details.json`; pobrano je raz z publicznego API sklepu
Steam i trzeba je uzupełnić ręcznie przy dodaniu nowej gry.

## Pliki

- `index.html`, `style.css`, `app.js`: strona, bez zewnętrznych bibliotek,
- `data.js`: dane,
- `store_details.json`: tryby gry, systemy i języki ze sklepu Steam,
- `build_data.py`: eksport danych z tabel projektu.
