# GamePulse

PoC: kolektory, które zapisują surowe dane o grach do plików JSONL w `data/raw/`.
Bez bazy danych; pliki przeczyta później DuckDB.

## Polecenia

Uruchamiane z katalogu repozytorium:

```bash
uv run gamepulse ccu            # bieżąca liczba graczy każdej gry (Steam)
uv run gamepulse news           # nowe newsy (Steam)
uv run gamepulse news --full    # cała historia newsów
uv run gamepulse reviews        # histogram recenzji (Steam)
uv run gamepulse fivem          # łączna liczba graczy FiveM (poza Steamem)
uv run gamepulse meta           # metadane gier ze sklepu Steam (studio, premiera, gatunki)
uv run gamepulse web            # interfejs pod http://127.0.0.1:8765
uv run pytest -q                # testy, bez sieci
```

Kod wyjścia: 0, gdy udała się co najmniej jedna gra lub źródło; 1, gdy żadna
albo gdy nie da się wczytać listy gier; 2 przy błędnych argumentach.
Jeśli ten sam kolektor już działa, drugie uruchomienie nic nie robi i kończy się kodem 0.

## Interfejs

`uv run gamepulse web` uruchamia lokalną stronę (tylko z tego komputera):

- strona główna: kafelki gier od największej liczby graczy, z wykresem z 24 h,
  odsetkiem pozytywnych recenzji z 30 dni i wiekiem ostatniego oficjalnego newsa;
- strona gry: metadane, wykres graczy, newsy na tej samej osi czasu, recenzje
  pozytywne i negatywne oraz lista newsów z treścią.

Dane czyta DuckDB wprost z plików w `data/raw/` i odświeża je, gdy pliki się
zmienią. Okładki i biblioteka wykresów ECharts ładują się z internetu.
Metadane nie mają timera: po dodaniu gry uruchom `uv run gamepulse meta`.

## Lista gier

`games.toml`. Dla nowej gry zwykłe `news` samo pobierze całą historię, bo jej
plik jest pusty. Dla gier, które już mają dane, `news` zatrzymuje się na
pierwszej stronie bez nowych wpisów.

Przerwane pobieranie newsów (błąd sieci, limit czasu) jest wznawiane przy
następnym uruchomieniu od miejsca przerwania; pozycję trzyma
`data/state/news/<appid>.json`. `news --full` przechodzi całą historię
niezależnie od tego i jako jedyne znajdzie wpis dodany ze starą datą.

## Dane

| Plik | Zawartość |
|---|---|
| `data/raw/ccu/RRRR-MM-DD.jsonl` | `ts, appid, player_count, ok, error`; jedna linia na grę i pomiar |
| `data/raw/news/<appid>.jsonl` | surowy wpis Steam plus `fetched_at`; kolektor nie zapisuje drugi raz tego samego `gid` |
| `data/raw/review_histogram/<appid>.jsonl` | `fetched_at, appid, results`; pełna migawka na każde pobranie |
| `data/raw/appdetails/<appid>.jsonl` | `fetched_at, appid, details`; wybrane pola ze sklepu Steam |
| `data/raw/fivem/RRRR-MM-DD.jsonl` | `ts, url, counts, ok, error`; jedna linia na źródło i pomiar |

- Czasy są w UTC. Pliki są tylko dopisywane.
- W plikach CCU i FiveM linia z `ok: false` oznacza, że kolektor działał, ale
  źródło nie odpowiedziało. Brak linii oznacza, że kolektor nie działał
  (np. wyłączony komputer). Newsy i recenzje błędów nie zapisują; są w dzienniku.
- Kolektor FiveM kończy się kodem 0, dopóki odpowiada choć jedno z dwóch źródeł,
  także to zwracające stałą wartość. Awarię żywego źródła widać po `ok: false`.
- Steam liczy tylko graczy ze Steama (bez Rockstar Launchera, Epic, launchera Tarkova).

## Źródła (sprawdzone 14 listopada 2026 r., bez klucza API)

- CCU: `api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/`
- Newsy: `api.steampowered.com/ISteamNews/GetNewsForApp/v2/`
- Histogram recenzji: `store.steampowered.com/appreviewhistogram/<appid>` (endpoint sklepu, nieoficjalny)
- FiveM: `static.cfx.re/runtime/counts.json` i `runtime.fivem.net/counts.json`.
  Oba nieudokumentowane, znaczenie trzech liczb niepotwierdzone. 14 listopada
  pierwszy zmieniał się między pomiarami, drugi zwracał stałą wartość.

Limity zapytań nie zostały sprawdzone w dokumentacji.

## Timery systemd (użytkownika)

Pliki są w `deploy/systemd/`: CCU i FiveM co 5 minut, newsy co godzinę,
recenzje raz dziennie o 12:00. Zakładają repozytorium w `~/projects/gamepulse`.

- Usługi uruchamiają `.venv/bin/gamepulse`, czyli kod z bieżącego stanu
  katalogu repozytorium. Przełączenie gałęzi zmienia to, co działa w tle.
- Newsy i recenzje nadrabiają pominięte uruchomienie po włączeniu komputera.
  Jeśli sieć jeszcze nie działa, próbują ponownie co 2 minuty, do 4 razy.
- CCU i FiveM nie ponawiają; kolejny pomiar jest za 5 minut.

Instalacja:

```bash
uv sync
```

```bash
mkdir -p ~/.config/systemd/user
```

```bash
cp deploy/systemd/gamepulse-* ~/.config/systemd/user/
```

```bash
systemctl --user daemon-reload
```

```bash
systemctl --user enable --now gamepulse-ccu.timer gamepulse-fivem.timer gamepulse-news.timer gamepulse-reviews.timer
```

Podgląd:

```bash
systemctl --user list-timers 'gamepulse-*'
journalctl --user -u gamepulse-ccu.service -n 20
```

Cofnięcie:

```bash
systemctl --user disable --now gamepulse-ccu.timer gamepulse-fivem.timer gamepulse-news.timer gamepulse-reviews.timer
rm ~/.config/systemd/user/gamepulse-*
systemctl --user daemon-reload
```

Timery użytkownika działają tylko wtedy, gdy jesteś zalogowany, chyba że
włączysz `loginctl enable-linger`.
