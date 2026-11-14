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
uv run pytest -q                # testy, bez sieci
```

Kod wyjścia to 0, gdy udała się co najmniej jedna gra lub źródło, inaczej 1.

## Lista gier

`games.toml`. Po dodaniu gry uruchom raz `uv run gamepulse news --full`,
żeby pobrać jej historię newsów; zwykłe `news` zatrzymuje się na pierwszej
stronie bez nowych wpisów.

## Dane

| Plik | Zawartość |
|---|---|
| `data/raw/ccu/RRRR-MM-DD.jsonl` | `ts, appid, player_count, ok, error`; jedna linia na grę i pomiar |
| `data/raw/news/<appid>.jsonl` | surowy wpis Steam plus `fetched_at`; bez powtórzeń `gid` |
| `data/raw/review_histogram/<appid>.jsonl` | `fetched_at, appid, results`; pełna migawka na każde pobranie |
| `data/raw/fivem/RRRR-MM-DD.jsonl` | `ts, url, counts, ok, error`; jedna linia na źródło i pomiar |

- Czasy są w UTC. Pliki są tylko dopisywane.
- Linia z `ok: false` oznacza, że kolektor działał, ale źródło nie odpowiedziało.
  Brak linii oznacza, że kolektor nie działał (np. wyłączony komputer).
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
recenzje raz dziennie. Zakładają repozytorium w `~/projects/gamepulse`
i `uv` w `~/.local/bin`.

Instalacja:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/gamepulse-* ~/.config/systemd/user/
systemctl --user daemon-reload
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
