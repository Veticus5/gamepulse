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
uv run gamepulse review-texts   # treść recenzji z językiem i czasem gry (Steam)
uv run gamepulse prices         # cena i przecena każdej gry w sklepie Steam
uv run gamepulse fivem          # łączna liczba graczy FiveM (poza Steamem)
uv run gamepulse meta           # metadane gier ze sklepu Steam (studio, premiera, gatunki)
uv run gamepulse pull-remote    # pomiary liczby graczy zebrane przez GitHub Actions
uv run gamepulse model          # modele dbt i wykrywanie anomalii w recenzjach
uv run gamepulse explain        # agent: możliwe przyczyny epizodów w recenzjach (lokalny model)
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
- strona gry: metadane, wykres graczy tylko na okresie z pomiarami (jeden
  znacznik na dzień z oficjalnymi newsami), pięć najważniejszych wydarzeń
  z 90 dni, archiwum newsów z wyszukiwarką oraz osobny wykres historii recenzji.

Kategorie i ważność newsów nadają na razie proste reguły po tytule
(`src/gamepulse/web/events.py`). To rozwiązanie tymczasowe do czasu
klasyfikatora i nie jest dowodem dla agenta.

Dane czyta DuckDB wprost z plików w `data/raw/` i odświeża je, gdy pliki się
zmienią. Okładki i biblioteka wykresów ECharts ładują się z internetu.
Metadane nie mają timera: po dodaniu gry uruchom `uv run gamepulse meta`.

## Klasyfikator newsów

`uv run gamepulse classify` czyta oficjalne newsy lokalnym modelem przez Ollamę
(domyślnie `qwen3.8:27b`, ostatnie 90 dni, najnowsze najpierw) i zapisuje dla
każdego typ główny, do trzech tagów dodatkowych (jeden news często dotyczy kilku
rzeczy), datę wejścia w życie, jednozdaniowe streszczenie, ważność i pewność. Jedno wywołanie na news, bez narzędzi, wymuszony JSON.

- Wyniki: `data/derived/news_events/<appid>.jsonl`, raz na news, model i wersję promptu.
- Każde wywołanie (także nieudane) trafia do `data/derived/agent_runs/RRRR-MM-DD.jsonl`
  z liczbą tokenów i czasem.
- Odpowiedź modelu sprawdza kod: nieznany typ odrzuca cały wynik, a data
  odległa od publikacji o więcej niż 45 dni wstecz lub 400 dni w przód jest pomijana.
- `--since-days 3650` obejmie całą historię (około 12 tys. newsów, kilka godzin GPU),
  `--limit N` ogranicza liczbę newsów, `--model` zmienia model.
- Interfejs pokazuje etykiety modelu, a dla newsów jeszcze nieprzeczytanych
  etykietę z reguły po tytule, oznaczoną znakiem zapytania.

### Pomiar trafności

1. `uv run gamepulse eval-sample` losuje 100 oficjalnych newsów z ostatniego roku
   do `eval/news_sample.jsonl` (plik jest w repozytorium i nie jest nadpisywany).
2. Na stronie `#/label` interfejsu oznaczasz je ręcznie: opcjonalne tagi dodatkowe,
   potem typ główny. Odpowiedź modelu jest ukryta.
   Etykiety trafiają do `eval/news_labels.jsonl`.
3. `uv run gamepulse eval-classifier` porównuje model z etykietami: trafność,
   precyzja i czułość per typ, zgodność tagów dodatkowych oraz lista rozbieżności. Uruchamiaj po każdej
   zmianie promptu lub modelu.

## Liczba graczy całą dobę (GitHub Actions)

Steam nie udostępnia historii liczby graczy, więc pomiar, którego nie było, przepada.
Dlatego liczbę graczy (Steam i FiveM) zbiera workflow
`.github/workflows/player-counts.yml`, niezależnie od tego, czy komputer jest
włączony. Newsy i recenzje da się pobrać wstecz, więc zostają lokalnie.

- Workflow rusza dwa razy na godzinę (7 i 37 minut po pełnej godzinie) i dopisuje
  pomiary do gałęzi `data` w plikach `raw/ccu/`, `raw/fivem/` i `raw/prices/`.
  Ceny (sklep USA, jedno zapytanie na wszystkie gry) też nie mają historii w Steamie.
- GitHub nie gwarantuje punktualności: przebieg bywa opóźniony o kilka–kilkanaście
  minut, a czasem wypada. Każdy pomiar ma zapisany rzeczywisty czas.
- Przebieg nie instaluje projektu, tylko `httpx`, żeby zmieścić się w minucie.
  W prywatnym repozytorium darmowy plan daje 2000 minut miesięcznie, a każdy
  przebieg liczy się jako co najmniej jedna minuta (około 1440 minut miesięcznie).
- Harmonogram działa tylko z domyślnej gałęzi repozytorium (`main`). GitHub wyłącza
  zaplanowane workflow po 60 dniach bez aktywności w repozytorium.
- `uv run gamepulse pull-remote` pobiera gałąź `data` i kopiuje pliki do
  `data/raw/ccu/gh-*.jsonl` i `data/raw/fivem/gh-*.jsonl`. Robi to timer
  `gamepulse-pull.timer`: minutę po zalogowaniu, potem co 30 minut.
- Po przeniesieniu lokalne timery `gamepulse-ccu.timer` i `gamepulse-fivem.timer`
  są wyłączone, żeby ten sam pomiar nie był robiony dwa razy.

## Treść recenzji

`uv run gamepulse review-texts` pobiera recenzje od najnowszych wstecz.
Pierwsze uruchomienie sięga 30 dni (`--days`), kolejne dociągają tylko nowe.

- Limit to 300 stron po 100 recenzji na grę i uruchomienie (`--max-pages`), z
  sekundą przerwy między stronami. Czego nie zdąży, dokończy następne
  uruchomienie; pozycja jest w `data/state/review_texts/`.
- Przerwane pobieranie (limit, błąd Steama, wyłączenie komputera) jest
  wznawiane bez dziur i bez duplikatów.
- Nie są zapisywane: identyfikator Steam, nazwa, profil, awatar ani lokalizacja
  recenzenta. Zostają czas gry i liczba recenzji autora.
- Recenzja edytowana po pobraniu nie jest pobierana ponownie.
- Źródło to `store.steampowered.com/ajaxappreviews/<appid>`, poza oficjalnym API.
  Oficjalne `IUserReviewsService/GetAppReviews` nie zwraca recenzji w kolejności
  od najnowszych (sprawdzone 15 listopada 2026 r.), więc nie da się nim iść wstecz.

Timer `gamepulse-review-texts.timer` uruchamia pobieranie raz dziennie: przy
pierwszym logowaniu danego dnia albo o północy, gdy sesja jest otwarta.

## Kto wystawia oceny

Na stronie gry panel „Kto wystawia oceny" pokazuje odsetek pozytywnych recenzji
w podziale na czas gry w chwili recenzji, język recenzji i sposób zdobycia gry,
dla ostatnich 7 lub 30 dni albo wszystkich zebranych recenzji. W panelu epizodu
tabela „Które grupy graczy zmieniły zdanie" porównuje te same grupy w epizodzie
i w 14 dniach przed nim (albo w okresie tak długim jak epizod, jeśli jest dłuższy).

- Liczy kod z zebranych recenzji (`data/raw/reviews/`), bez modelu.
- Grupa z mniej niż 30 recenzjami nie dostaje odsetka.
- Dla gier darmowych podział według sposobu zdobycia jest ukryty.
- Język recenzji to nie kraj gracza. Gracze z długim stażem to ci, którzy nie
  odeszli, więc ich oceny są z natury wyższe.

## Anomalie w recenzjach

`uv run gamepulse model` uruchamia modele dbt (`src/gamepulse/warehouse/`) na
DuckDB i zapisuje tabelę `anomalies`. Trwa kilka sekund. Liczy wyłącznie kod,
model językowy nie bierze w tym udziału.

| Model dbt | Zawartość |
|---|---|
| `stg_review_snapshots` | jedna linia na migawkę histogramu recenzji |
| `review_periods` | recenzje na grę i okres: miesiąc lub tydzień dla całej historii (jak podaje Steam), dzień dla ostatnich 30 dni i dalej |
| `review_baselines` | zakończony okres obok mediany z poprzedzających okresów (12 miesięcy, 12 tygodni, 14 dni) |
| `anomalies` | okresy wyraźnie odbiegające od tego, co zwykłe dla danej gry |
| `anomaly_episodes` | epizody: kolejne nietypowe okresy po tej samej stronie (negatywne, pozytywne, sam skok liczby) połączone w jeden wiersz |

Rodzaje anomalii (`kind`):

- `review_score_drop`, `review_score_rise`: odsetek pozytywnych odbiega od mediany
  o co najmniej 5 punktów procentowych i o co najmniej 3,5 odchylenia
  (odporne odchylenie z historii gry albo losowy rozrzut przy tej liczbie
  recenzji, większe z nich); okres ma co najmniej 30 recenzji.
- `review_volume_spike`: co najmniej 3 razy więcej recenzji niż zwykle i co najmniej 100.

Progi są w `src/gamepulse/warehouse/dbt_project.yml` (`vars`). Ograniczenia:

- Okres bez co najmniej 6 wcześniejszych zakończonych okresów nie jest oceniany,
  więc pierwsze miesiące gry po premierze nie dają anomalii.
- Trwający miesiąc, tydzień i dzień są pomijane, bo mają niepełne liczby.
- Epizod łączy tylko okresy bezpośrednio po sobie; jeden zwykły dzień w środku dzieli go na dwa.
- Epizod dzienny i tygodniowy lub miesięczny tego samego zdarzenia są osobnymi wierszami.

Interfejs pokazuje epizody. Kliknięcie epizodu otwiera jego przebieg i oficjalne
newsy opublikowane lub wchodzące w życie od 7 dni (dla dni) albo 14 dni (dla
tygodni i miesięcy) przed początkiem do końca epizodu. To zestawienie w czasie,
nie wyjaśnienie przyczyn.

## Agent wyjaśniający epizody

`uv run gamepulse explain` prosi lokalny model (Ollama, domyślnie `qwen3.8:27b`)
o możliwe przyczyny epizodów zakończonych w ostatnich 90 dniach
(`--since-days`, `--limit`, `--model`). Jedno wywołanie na epizod, około 7 sekund,
bez narzędzi. Epizod jest analizowany ponownie tylko wtedy, gdy zmieniły się jego
liczby, newsy wokół niego, prompt albo model.

1. Kod składa paczkę dowodów z identyfikatorami:
   - **N**: do 12 oficjalnych newsów z okna wokół epizodu;
   - **P**: do 6 artykułów prasowych, które Steam podaje dla gry (PC Gamer, PCGamesN,
     Rock Paper Shotgun i inne), najbliższych początkowi epizodu;
   - **D**: przeceny w sklepie Steam zapisane przez kolektor cen (dopiero od
     15 listopada 2026 r.; brak danych o cenie nie jest zgłaszany jako brak przeceny);
   - **R**: próbka 30 recenzji graczy napisanych w trakcie epizodu, jeśli są zebrane.
     Większość z tej strony, po której jest epizod; połowa to recenzje najczęściej
     oznaczane jako pomocne, połowa losowa (zawsze ta sama). Recenzje krótsze niż
     40 znaków są pomijane.
2. Model zwraca werdykt (`likely`, `possible`, `unknown`), podsumowanie i do 3 hipotez.
   Każda hipoteza musi wskazać identyfikatory dowodów, na których się opiera.
3. Kod sprawdza odpowiedź:
   - hipoteza bez istniejącego dowodu jest odrzucana;
   - tekst z liczbą, której nie ma w paczce, jest odrzucany (model nie liczy);
   - hipoteza oparta tylko na wpisach opublikowanych po pierwszym dniu epizodu
     dostaje oznaczenie „tłumaczy ciąg dalszy", a bez hipotezy o początku werdykt
     to najwyżej `possible`;
   - gdy model dostał co najmniej 10 recenzji, werdykt `likely` wymaga hipotezy
     wskazującej co najmniej 2 recenzje; inaczej jest obniżany do `possible`;
   - odpowiedź po angielsku jest odrzucana w całości;
   - bez żadnej hipotezy werdykt to `unknown`.
4. Gdy w oknie nie ma żadnych dowodów, odpowiada kod (`unknown`), a model nie jest pytany.

Ograniczenia: recenzje są zebrane tylko dla ostatnich tygodni, więc starsze epizody
opierają się na zbieżności w czasie i treści wpisów. Kod sprawdza, że wskazana
recenzja istnieje, ale nie sprawdza, czy naprawdę mówi to, co twierdzi model.
Trafności wyjaśnień nikt jeszcze nie zmierzył; nie ma do tego ręcznie oznaczonej próbki.

Wyniki: `data/derived/explanations/<appid>.jsonl` (ostatnia linia dla epizodu wygrywa,
razem z odrzuconymi twierdzeniami w polu `dropped`). Każde wywołanie modelu jest
w `data/derived/agent_runs/`.

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
| `data/raw/reviews/<appid>.jsonl` | jedna recenzja na linię: treść, ocena, język, czas gry, sposób zakupu, daty; bez danych recenzenta |
| `data/raw/prices/RRRR-MM-DD.jsonl` | `ts, appid, priced, currency, initial, final, discount_percent`; kwoty w centach |
| `data/raw/appdetails/<appid>.jsonl` | `fetched_at, appid, details`; wybrane pola ze sklepu Steam |
| `data/raw/fivem/RRRR-MM-DD.jsonl` | `ts, url, counts, ok, error`; jedna linia na źródło i pomiar |

| `data/derived/anomalies.parquet` | tabela `anomalies`; czyta ją interfejs, a później agent |
| `data/derived/anomaly_episodes.parquet` | tabela `anomaly_episodes`; jak wyżej |
| `data/warehouse/gamepulse.duckdb` | baza dbt z wszystkimi modelami; do własnych zapytań, gdy `gamepulse model` nie działa |

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

Pliki są w `deploy/systemd/`: CCU i FiveM co 30 minut, newsy co godzinę,
recenzje raz dziennie o 12:00,
analiza anomalii (`gamepulse model`) raz dziennie o 12:30. Zakładają repozytorium w `~/projects/gamepulse`.

- Usługi uruchamiają `.venv/bin/gamepulse`, czyli kod z bieżącego stanu
  katalogu repozytorium. Przełączenie gałęzi zmienia to, co działa w tle.
- Newsy i recenzje nadrabiają pominięte uruchomienie po włączeniu komputera.
  Jeśli sieć jeszcze nie działa, próbują ponownie co 2 minuty, do 4 razy.
- CCU i FiveM nie ponawiają; kolejny pomiar jest za 30 minut.

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
systemctl --user enable --now gamepulse-ccu.timer gamepulse-fivem.timer gamepulse-news.timer gamepulse-reviews.timer gamepulse-model.timer gamepulse-review-texts.timer
```

Podgląd:

```bash
systemctl --user list-timers 'gamepulse-*'
journalctl --user -u gamepulse-ccu.service -n 20
```

Cofnięcie:

```bash
systemctl --user disable --now gamepulse-ccu.timer gamepulse-fivem.timer gamepulse-news.timer gamepulse-reviews.timer gamepulse-model.timer gamepulse-review-texts.timer
rm ~/.config/systemd/user/gamepulse-*
systemctl --user daemon-reload
```

Timery użytkownika działają tylko wtedy, gdy jesteś zalogowany, chyba że
włączysz `loginctl enable-linger`.
