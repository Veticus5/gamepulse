# Kolektory Steam — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trzy kolektory (CCU, newsy, histogram recenzji) zapisujące surowe dane Steam do plików JSONL, uruchamiane z timera systemd na workstation.

**Architecture:** Jeden pakiet Pythona `gamepulse` z poleceniem `gamepulse ccu|news|reviews`. Każde polecenie czyta listę gier z `games.toml`, odpytuje publiczny endpoint Steam i dopisuje linie do plików w `data/raw/`. Bez bazy danych: DuckDB przeczyta te pliki w następnym etapie.

**Tech Stack:** Python 3.15 (uv), httpx, pytest. systemd (timery użytkownika).

**Spec:** uzgodniony w rozmowie 14 listopada 2026 r., streszczony poniżej.

## Spec (skrót)

- Zakres: etap 0 z `gamepulse-agenci-architektura.md`, tylko zbieranie danych. Bez DuckDB, dbt, anomalii, modelu i serwera.
- Zapis: pliki JSONL (wybrane zamiast SQLite i zamiast zapisu wprost do DuckDB, który dopuszcza jeden proces piszący).
- Kolektor działa tylko przy włączonym komputerze; dziury w CCU są akceptowane.
- Endpointy sprawdzone 14 listopada 2026 r., wszystkie bez klucza API:
  - CCU: `GET https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=<id>` → `{"response":{"player_count":N,"result":1}}`; nieznana gra → HTTP 404 i `{"response":{"result":42}}`.
  - Newsy: `GET https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=<id>&count=100&maxlength=0[&enddate=<unix>]` → `{"appnews":{"appid":..,"newsitems":[..],"count":N}}`; pola wpisu: `gid, title, url, is_external_url, author, contents, feedlabel, date, feedname, feed_type, appid` (czasem `tags`).
  - Histogram recenzji: `GET https://store.steampowered.com/appreviewhistogram/<id>?l=english` → `{"success":1,"results":{"start_date","end_date","rollup_type","rollups":[{"date","recommendations_up","recommendations_down"}],"recent":[...],"weeks":[]}}`. Endpoint sklepu, nieoficjalny.
- Limity zapytań: niezweryfikowane w dokumentacji.

## Global Constraints

- Python `>=3.15`; jedyna zależność uruchomieniowa: `httpx`. Zależność deweloperska: `pytest`.
- Czasy zawsze w UTC, format `YYYY-MM-DDTHH:MM:SSZ`.
- `data/` nie trafia do Gita.
- Nagłówek `User-Agent: gamepulse-collector/0.1`; żadnych danych osobowych w zapytaniach.
- Timeout zapytania 20 s; przerwa 0,2 s między zapytaniami; bez ponowień.
- Błąd jednej gry nie przerywa pozostałych. Kod wyjścia 0, gdy udała się co najmniej jedna gra, inaczej 1.
- Kolektory tylko dopisują do plików; nigdy nie nadpisują ani nie usuwają.
- Testy nie łączą się z siecią (`httpx.MockTransport`).

## Układ plików

| Plik | Odpowiedzialność |
|---|---|
| `pyproject.toml` | Pakiet, zależności, skrypt `gamepulse` |
| `games.toml` | Lista gier: `[[games]]` z `appid` i `name` |
| `src/gamepulse/config.py` | `Game`, `load_games` |
| `src/gamepulse/storage.py` | `append_jsonl`, `read_jsonl`, `utc_now_iso` |
| `src/gamepulse/steam.py` | Trzy funkcje `fetch_*` i `SteamError` |
| `src/gamepulse/collect_ccu.py` | `run` dla CCU |
| `src/gamepulse/collect_news.py` | `run` dla newsów |
| `src/gamepulse/collect_reviews.py` | `run` dla histogramu |
| `src/gamepulse/cli.py` | Parsowanie argumentów, kod wyjścia |
| `deploy/systemd/` | Trzy pary `.service` + `.timer` |

## Review Focus

1. Steam zwraca HTML lub przekierowanie zamiast JSON (zaobserwowane dla `/appreviews/`) → `SteamError`, zapis błędu, brak wyjątku na zewnątrz. Test w zadaniu 2.
2. Proces przerwany w trakcie zapisu zostawia urwaną ostatnią linię → `read_jsonl` ją pomija, kolejny zapis zaczyna od nowej linii. Test w zadaniu 1.
3. Całkowity brak sieci → każda gra dostaje wpis `ok: false`, kod wyjścia 1. Test w zadaniu 3.
4. Przerwany backfill newsów → ponowne `news --full` dociąga resztę bez duplikatów. Test w zadaniu 4.
5. Ten sam `gid` zwrócony na dwóch stronach (granica `enddate`) → zapisany raz. Test w zadaniu 4.

---

### Task 1: Szkielet projektu, konfiguracja, zapis JSONL

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`, `games.toml`, `src/gamepulse/__init__.py`, `src/gamepulse/config.py`, `src/gamepulse/storage.py`
- Test: `tests/test_config.py`, `tests/test_storage.py`

**Interfaces:**
- Produces:
  - `config.Game` — `@dataclass(frozen=True)` z polami `appid: int`, `name: str`
  - `config.load_games(path: Path) -> list[Game]` — `ValueError` przy pustej liście lub powtórzonym `appid`
  - `storage.utc_now_iso() -> str`
  - `storage.append_jsonl(path: Path, records: Iterable[dict]) -> int` — tworzy katalogi, zwraca liczbę linii; jeśli plik nie kończy się `\n`, najpierw dopisuje `\n`; całość jednym `write` w trybie `ab`
  - `storage.read_jsonl(path: Path) -> list[dict]` — brak pliku → `[]`; linie niebędące poprawnym JSON są pomijane

`games.toml` (identyfikatory sprawdzone w Steamie 14 listopada 2026 r.): 730 Counter-Strike 2, 570 Dota 2, 578080 PUBG: BATTLEGROUNDS, 1172470 Apex Legends, 553850 HELLDIVERS 2, 1086940 Baldur's Gate 3, 1091500 Cyberpunk 2077, 1245620 ELDEN RING, 413150 Stardew Valley, 2694490 Path of Exile 2, 1623730 Palworld, 252490 Rust, 275850 No Man's Sky, 548430 Deep Rock Galactic, 2379780 Balatro.

- [ ] **Step 1:** `uv init --package --python 3.15`, dodać `httpx` i `pytest` (dev), skrypt `gamepulse = "gamepulse.cli:main"`, `.gitignore` z `data/`, `.venv/`, `__pycache__/`.
- [ ] **Step 2:** Testy (najpierw czerwone):
  - `test_load_games_reads_appid_and_name` — dwa wpisy → `[Game(730, "Counter-Strike 2"), Game(570, "Dota 2")]`
  - `test_load_games_rejects_duplicate_appid` — `pytest.raises(ValueError)`
  - `test_load_games_rejects_empty_file` — `pytest.raises(ValueError)`
  - `test_repo_games_toml_loads` — `len(load_games(Path("games.toml"))) == 15`
  - `test_append_creates_parents_and_roundtrips` — zapis 2 rekordów do `tmp/a/b/x.jsonl`, `read_jsonl` zwraca te same
  - `test_append_twice_appends` — 1 + 1 rekord → 2 linie
  - `test_read_missing_file_returns_empty`
  - `test_read_skips_truncated_last_line` — plik `{"a":1}\n{"a":` → `[{"a": 1}]`
  - `test_append_after_truncated_line_starts_new_line` — po urwanej linii `append_jsonl` rekordu `{"a":2}` → `read_jsonl == [{"a":1},{"a":2}]`
  - `test_utc_now_iso_format` — pasuje do `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$`
- [ ] **Step 3:** Implementacja `config.py`, `storage.py`.
- [ ] **Step 4:** `uv run pytest -q` → wszystkie zielone.
- [ ] **Step 5:** Commit `feat: project skeleton, game list, JSONL storage`.

### Task 2: Klient Steam

**Files:**
- Create: `src/gamepulse/steam.py`
- Test: `tests/test_steam.py`

**Interfaces:**
- Produces:
  - `steam.SteamError(Exception)`
  - `steam.make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client` — timeout 20 s, User-Agent ze stałych, `follow_redirects=False`
  - `steam.fetch_ccu(client, appid: int) -> int`
  - `steam.fetch_news_page(client, appid: int, *, count: int = 100, enddate: int | None = None) -> list[dict]` — zawsze `maxlength=0`
  - `steam.fetch_review_histogram(client, appid: int) -> dict` — zwraca zawartość `results`
- Każda funkcja zamienia na `SteamError`: błąd transportu (`httpx.HTTPError`), status inny niż 200, treść niebędącą JSON, brak oczekiwanych pól (`result != 1`, brak `appnews.newsitems`, `success != 1`).

- [ ] **Step 1:** Testy z `httpx.MockTransport`:
  - `test_fetch_ccu_returns_player_count` — odpowiedź `{"response":{"player_count":1285590,"result":1}}` → `1285590`; zapytanie ma `appid=730`
  - `test_fetch_ccu_unknown_app_raises` — 404 + `{"response":{"result":42}}` → `SteamError`
  - `test_fetch_ccu_html_body_raises` — 200 + `<!DOCTYPE html>` → `SteamError`
  - `test_fetch_ccu_redirect_raises` — 302 → `SteamError`
  - `test_fetch_ccu_network_error_raises` — transport rzuca `httpx.ConnectError` → `SteamError`
  - `test_fetch_news_page_sends_params` — parametry `count=100`, `maxlength=0`, bez `enddate`; z `enddate=1700000000` parametr obecny; zwraca listę `newsitems`
  - `test_fetch_news_page_missing_appnews_raises`
  - `test_fetch_review_histogram_returns_results` — ścieżka `/appreviewhistogram/413150`, zwraca słownik z `rollups`
  - `test_fetch_review_histogram_success_zero_raises`
- [ ] **Step 2:** Implementacja.
- [ ] **Step 3:** `uv run pytest -q` → zielone. Commit `feat: Steam HTTP client`.

### Task 3: Kolektor CCU i CLI

**Files:**
- Create: `src/gamepulse/collect_ccu.py`, `src/gamepulse/cli.py`
- Test: `tests/test_collect_ccu.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Game`, `load_games`, `append_jsonl`, `utc_now_iso`, `fetch_ccu`, `SteamError`, `make_client`
- Produces:
  - `collect_ccu.run(client, games: list[Game], data_dir: Path, *, pause: float = 0.2) -> int` — zwraca liczbę udanych gier
  - `cli.main(argv: list[str] | None = None) -> int` — `gamepulse {ccu,news,reviews} [--games games.toml] [--data-dir data] [--full]` (`--full` tylko dla `news`); zwraca 0, gdy `run` > 0, inaczej 1
- Plik: `<data_dir>/raw/ccu/<YYYY-MM-DD>.jsonl` według daty UTC pomiaru.
- Rekord: `{"ts": str, "appid": int, "player_count": int | None, "ok": bool, "error": str | None}`. Wpis `ok: false` odróżnia „Steam nie odpowiedział" od „komputer był wyłączony".

- [ ] **Step 1:** Testy:
  - `test_run_writes_one_record_per_game` — 2 gry → 2 linie z `ok: true` i liczbami, wynik 2
  - `test_run_records_failure_and_continues` — pierwsza gra 404 → linia `ok: false`, `player_count: None`, niepusty `error`; druga zapisana poprawnie; wynik 1
  - `test_run_all_fail_returns_zero` — transport rzuca `ConnectError` → 2 linie `ok: false`, wynik 0
  - `test_file_named_by_utc_date` — istnieje dokładnie jeden plik `raw/ccu/*.jsonl` o nazwie równej `ts[:10]`
  - `test_cli_ccu_exit_codes` — `main(["ccu", ...])` z podmienionym `make_client` → 0 przy sukcesie, 1 przy samych błędach
- [ ] **Step 2:** Implementacja.
- [ ] **Step 3:** `uv run pytest -q` → zielone. Commit `feat: CCU collector and CLI`.

### Task 4: Kolektor newsów

**Files:**
- Create: `src/gamepulse/collect_news.py`
- Modify: `src/gamepulse/cli.py` (podpięcie `news`)
- Test: `tests/test_collect_news.py`

**Interfaces:**
- Consumes: `fetch_news_page`, `read_jsonl`, `append_jsonl`, `utc_now_iso`
- Produces: `collect_news.run(client, games, data_dir, *, full: bool = False, pause: float = 0.2, page_size: int = 100) -> int`
- Plik: `<data_dir>/raw/news/<appid>.jsonl`. Rekord: surowy wpis Steam plus `fetched_at`.

Algorytm dla jednej gry (sygnatura i testy go nie wyznaczają):

```
seen = {r["gid"] for r in read_jsonl(plik)}
enddate = None
pętla:
    page = fetch_news_page(appid, count=page_size, enddate=enddate)
    jeśli page puste: koniec
    new = wpisy z page o gid spoza seen (bez powtórzeń wewnątrz strony)
    dopisz new do pliku (od razu, strona po stronie); seen |= gid-y new
    jeśli new puste i nie full: koniec          # dogoniliśmy to, co już mamy
    next_end = min(date w page)
    jeśli next_end == enddate: next_end -= 1    # strona nie posunęła się w czasie
    enddate = next_end
    jeśli len(page) < page_size: koniec
```

- [ ] **Step 1:** Testy (fałszywy transport trzyma listę wpisów posortowaną malejąco po `date` i honoruje `count` oraz `enddate` włącznie):
  - `test_backfill_walks_all_pages` — 250 wpisów, `page_size=100` → 250 linii, unikalne `gid`
  - `test_second_run_adds_nothing` — ponowne `run` → nadal 250 linii, 1 zapytanie na grę
  - `test_incremental_fetches_only_new` — po backfillu dochodzą 3 nowe → 253 linie
  - `test_boundary_gid_not_duplicated` — `enddate` włącznie zwraca wpis graniczny drugi raz → zapisany raz
  - `test_full_resumes_interrupted_backfill` — plik ma tylko 100 najnowszych; `run(full=False)` nic nie dodaje, `run(full=True)` → 250
  - `test_same_timestamp_page_terminates` — 150 wpisów o identycznym `date`, `page_size=100` → pętla kończy się (bez nieskończonej pętli), zapisane 100
  - `test_error_on_one_game_continues` — pierwsza gra `SteamError` → druga zapisana, wynik 1
  - `test_records_have_fetched_at`
- [ ] **Step 2:** Implementacja.
- [ ] **Step 3:** `uv run pytest -q` → zielone. Commit `feat: news collector with backfill`.

### Task 5: Kolektor histogramu recenzji

**Files:**
- Create: `src/gamepulse/collect_reviews.py`
- Modify: `src/gamepulse/cli.py` (podpięcie `reviews`)
- Test: `tests/test_collect_reviews.py`

**Interfaces:**
- Consumes: `fetch_review_histogram`, `append_jsonl`, `utc_now_iso`
- Produces: `collect_reviews.run(client, games, data_dir, *, pause: float = 0.2) -> int`
- Plik: `<data_dir>/raw/review_histogram/<appid>.jsonl`. Jedna linia na pobranie: `{"fetched_at": str, "appid": int, "results": dict}` (pełna migawka; deduplikacja dni należy do dbt).

- [ ] **Step 1:** Testy:
  - `test_run_appends_snapshot_per_game` — 2 gry → po 1 linii z `results.rollups`
  - `test_second_run_appends_second_snapshot` — 2 linie w pliku gry
  - `test_error_on_one_game_continues` — wynik 1, brak pliku dla gry z błędem
- [ ] **Step 2:** Implementacja.
- [ ] **Step 3:** `uv run pytest -q` → zielone. Commit `feat: review histogram collector`.

### Task 6: Uruchomienie na prawdziwych danych i timery

**Files:**
- Create: `deploy/systemd/gamepulse-ccu.service`, `gamepulse-ccu.timer`, `gamepulse-news.service`, `gamepulse-news.timer`, `gamepulse-reviews.service`, `gamepulse-reviews.timer`
- Modify: `README.md` (uruchamianie, instalacja i cofnięcie timerów)

- Usługi: `Type=oneshot`, `WorkingDirectory=%h/projects/gamepulse`, `ExecStart=%h/.local/bin/uv run --frozen gamepulse <polecenie>`.
- Timery: CCU `OnCalendar=*:0/5`; newsy `OnCalendar=hourly`; recenzje `OnCalendar=daily`. Newsy i recenzje z `Persistent=true`, wszystkie z `RandomizedDelaySec=30`.

- [ ] **Step 1:** `uv run gamepulse ccu` → 15 linii `ok: true` w dzisiejszym pliku.
- [ ] **Step 2:** `uv run gamepulse news --full` → pliki dla 15 gier; liczba linii dla 413150 bliska polu `count` z API; brak powtórzonych `gid`.
- [ ] **Step 3:** `uv run gamepulse reviews` → 15 plików po 1 linii.
- [ ] **Step 4:** `systemd-analyze verify --user deploy/systemd/*` bez błędów.
- [ ] **Step 5:** Commit `feat: systemd units and run instructions`.
- [ ] **Step 6:** Instalacja i włączenie timerów dopiero po osobnej zgodzie użytkownika.
