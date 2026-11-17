// GamePulse demo: a static page over the snapshot in data.js. No libraries.
(function () {
  "use strict";

  const DATA = window.GAMEPULSE_DEMO || { games: [], generated: Date.now() };
  const NOW = DATA.generated; // the snapshot's moment stands in for "now"
  const DAY = 86400000;
  const app = document.getElementById("app");
  const tip = document.getElementById("tip");

  // ---------------------------------------------------------------- helpers

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function svg(tag, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    return node;
  }

  const whole = new Intl.NumberFormat("pl-PL");
  const short = new Intl.NumberFormat("pl-PL", { notation: "compact", maximumFractionDigits: 1 });
  const dayMonth = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short", timeZone: "UTC" });
  const fullDate = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const monthYear = new Intl.DateTimeFormat("pl-PL", { month: "short", year: "numeric", timeZone: "UTC" });
  const dayHour = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

  const percent = (value) => `${String(Math.round(value))}%`;
  const share = (up, down) => (up + down ? (100 * up) / (up + down) : null);
  const rate30 = (game) => share(game.reviews_30d.positive, game.reviews_30d.negative);
  const rateAll = (game) => share(game.reviews_all.positive, game.reviews_all.negative);

  // Polish plural: 1 okres, 2 okresy, 5 okresów.
  function plural(count, one, few, many) {
    const tens = count % 100, ones = count % 10;
    const word = count === 1 ? one : ones >= 2 && ones <= 4 && !(tens >= 12 && tens <= 14) ? few : many;
    return `${whole.format(count)} ${word}`;
  }

  function money(cents, currency) {
    if (cents === null || cents === undefined) return null;
    return new Intl.NumberFormat("pl-PL", { style: "currency", currency: currency || "USD" }).format(cents / 100);
  }

  function period(from, to) {
    const last = to - DAY; // the end is the first day after the period
    if (last <= from) return fullDate.format(from);
    const sameYear = new Date(from).getUTCFullYear() === new Date(last).getUTCFullYear();
    return `${(sameYear ? dayMonth : fullDate).format(from)} – ${fullDate.format(last)}`;
  }

  function remember(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch (error) { return fallback; }
  }
  function store(key, value) {
    try { localStorage.setItem(key, value); } catch (error) { /* private window: the choice lasts for this view */ }
  }

  const KIND = {
    negative: { tone: "bad", title: "Oceny wyraźnie gorsze niż zwykle", brief: "oceny wyraźnie gorsze niż zwykle" },
    positive: { tone: "good", title: "Oceny wyraźnie lepsze niż zwykle", brief: "oceny wyraźnie lepsze niż zwykle" },
    volume: { tone: "warn", title: "Dużo więcej ocen niż zwykle", brief: "dużo więcej ocen niż zwykle" },
  };
  const VERDICT = {
    likely: { tone: "good", label: "Prawdopodobna przyczyna" },
    possible: { tone: "warn", label: "Możliwa przyczyna" },
    unknown: { tone: "quiet", label: "Przyczyna nieznana" },
  };
  const LANGUAGE = { english: "po angielsku", polish: "po polsku", schinese: "po chińsku", russian: "po rosyjsku",
    german: "po niemiecku", french: "po francusku", spanish: "po hiszpańsku", koreana: "po koreańsku",
    japanese: "po japońsku", brazilian: "po portugalsku", turkish: "po turecku" };
  const NEWS_GROUPS = [
    ["all", "Wszystko"], ["update", "Aktualizacje"], ["content", "Nowa zawartość"], ["tech", "Problemy techniczne"],
    ["business", "Biznes i ceny"], ["mods", "Mody"], ["opinion", "Opinie"], ["other", "Pozostałe"],
  ];
  const GROUP_NAME = Object.fromEntries(NEWS_GROUPS);

  function chip(tone, text) {
    return el("span", { class: `chip ${tone}` }, text);
  }

  function cover(game) {
    const image = el("img", { class: "cover", src: game.image, alt: "", loading: "lazy" });
    // Without a network the picture is missing; the coloured block behind it stays.
    image.addEventListener("error", () => image.removeAttribute("src"));
    return image;
  }

  const recentEpisode = (game) => game.episodes.find((episode) => episode.to >= NOW - 21 * DAY) || null;

  // Players now against the same hour a day earlier; null without a full day of data.
  function playerChange(game) {
    const points = game.players;
    if (points.length < 2) return null;
    const last = points[points.length - 1];
    const before = points.reduce((best, p) =>
      (Math.abs(p[0] - (last[0] - DAY)) < Math.abs(best[0] - (last[0] - DAY)) ? p : best));
    if (Math.abs(before[0] - (last[0] - DAY)) > 2 * 3600000 || !before[1]) return null;
    return (100 * (last[1] - before[1])) / before[1];
  }

  // ------------------------------------------------------- "since my last visit"

  // A static snapshot has no real visits, so the demo lets you pick how long ago the last one was.
  const SINCE_OPTIONS = [[3, "3 dni temu"], [7, "tydzień temu"], [30, "miesiąc temu"]];
  const sinceDays = () => Number(remember("gamepulse-demo-since", "7")) || 7;
  const sinceMs = () => NOW - sinceDays() * DAY;

  function changesSince(game) {
    const since = sinceMs();
    return {
      episodes: game.episodes.filter((episode) => episode.to > since),
      posts: game.news.filter((item) => !item.press && item.date > since),
      sale: game.price.sales.find((sale) => sale.from > since) || null,
    };
  }

  function changeLine(changes) {
    return [
      changes.episodes.length ? plural(changes.episodes.length, "nietypowy okres", "nietypowe okresy", "nietypowych okresów") : null,
      changes.posts.length ? plural(changes.posts.length, "ogłoszenie twórców", "ogłoszenia twórców", "ogłoszeń twórców") : null,
      changes.sale ? `przecena ${changes.sale.percent}%` : null,
    ].filter(Boolean).join(" · ");
  }

  function sincePicker() {
    return el("label", { class: "picker" }, "Ostatnia wizyta: ",
      el("select", { id: "since", onchange: (event) => { store("gamepulse-demo-since", event.target.value); route(); } },
        SINCE_OPTIONS.map(([days, label]) => el("option", { value: days, selected: days === sinceDays() }, label))));
  }

  // ----------------------------------------------------------------- charts

  function showTip(event, text) {
    tip.textContent = text;
    tip.hidden = false;
    const width = tip.offsetWidth;
    tip.style.left = `${Math.max(8, Math.min(window.innerWidth - width - 8, event.clientX - width / 2))}px`;
    tip.style.top = `${Math.max(8, event.clientY - tip.offsetHeight - 14)}px`;
  }
  const hideTip = () => { tip.hidden = true; };

  // series: [{points: [[time, value, label]], tone: "a" | "b", area}]; bands: [{from, to, tone, label, onclick}]
  function lineChart(host, series, options) {
    const draw = () => {
      host.replaceChildren();
      const lines = series.filter((s) => s.points.length >= 2);
      if (!lines.length) {
        host.append(el("p", { class: "empty" }, "Za mało danych, żeby narysować wykres."));
        return;
      }
      const width = Math.max(300, host.clientWidth);
      const height = Math.round(Math.min(280, Math.max(190, width * 0.3)));
      const pad = { left: 44, right: 12, top: 10, bottom: 26 };
      const t0 = Math.min(...lines.map((s) => s.points[0][0]));
      const t1 = Math.max(...lines.map((s) => s.points[s.points.length - 1][0]));
      const [y0, y1] = options.range(lines.flatMap((s) => s.points.map((p) => p[1])));
      const x = (t) => pad.left + ((t - t0) / (t1 - t0 || 1)) * (width - pad.left - pad.right);
      const y = (v) => pad.top + (1 - (v - y0) / (y1 - y0 || 1)) * (height - pad.top - pad.bottom);
      const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": options.label });

      for (const band of options.bands || []) {
        const from = Math.max(t0, band.from), to = Math.min(t1, band.to);
        if (band.to < t0 || band.from > t1) continue;
        const rect = svg("rect", { class: `band ${band.tone}`, x: x(from) - 2, y: pad.top,
          width: Math.max(8, x(to) - x(from) + 4), height: height - pad.top - pad.bottom, rx: 3 });
        rect.addEventListener("mousemove", (event) => showTip(event, band.label));
        rect.addEventListener("mouseleave", hideTip);
        rect.addEventListener("click", band.onclick);
        root.append(rect);
      }
      for (let step = 0; step <= 2; step++) {
        const value = y0 + ((y1 - y0) * step) / 2;
        root.append(svg("line", { class: "grid-line", x1: pad.left, x2: width - pad.right, y1: y(value), y2: y(value) }));
        const text = svg("text", { class: "axis", x: pad.left - 8, y: y(value) + 4, "text-anchor": "end" });
        text.textContent = options.axis(value);
        root.append(text);
      }
      const ticks = Math.max(2, Math.min(6, Math.floor(width / 150)));
      for (let step = 0; step <= ticks; step++) {
        const time = t0 + ((t1 - t0) * step) / ticks;
        const text = svg("text", { class: "axis", x: x(time), y: height - 6,
          "text-anchor": step === 0 ? "start" : step === ticks ? "end" : "middle" });
        text.textContent = options.tick(time);
        root.append(text);
      }
      const dots = [];
      for (const line of lines) {
        const tone = line.tone || "a";
        const path = line.points.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
        if (line.area) {
          const first = line.points[0][0], last = line.points[line.points.length - 1][0];
          root.append(svg("path", { class: `area ${tone}`, d: `${path}L${x(last).toFixed(1)},${y(y0)}L${x(first).toFixed(1)},${y(y0)}Z` }));
        }
        root.append(svg("path", { class: `line ${tone}`, d: path }));
        const dot = svg("circle", { class: `dot ${tone}`, r: 4.5, visibility: "hidden" });
        root.append(dot);
        dots.push(dot);
      }
      const hideDots = () => dots.forEach((dot) => dot.setAttribute("visibility", "hidden"));
      root.addEventListener("mousemove", (event) => {
        if (event.target.classList.contains("band")) { hideDots(); return; }
        const box = root.getBoundingClientRect();
        const at = ((event.clientX - box.left) / box.width) * width;
        const labels = lines.map((line, index) => {
          const point = line.points.reduce((best, p) => (Math.abs(x(p[0]) - at) < Math.abs(x(best[0]) - at) ? p : best));
          dots[index].setAttribute("cx", x(point[0]));
          dots[index].setAttribute("cy", y(point[1]));
          dots[index].setAttribute("visibility", "visible");
          return point[2];
        });
        showTip(event, labels.join("\n"));
      });
      root.addEventListener("mouseleave", () => { hideDots(); hideTip(); });
      host.append(root);
    };
    draw();
    return draw;
  }

  const reviewPoints = (game, prefix) => game.reviews
    .filter((row) => row[1] + row[2] > 0)
    .map((row) => {
      const value = share(row[1], row[2]);
      const when = game.reviews_grain === "week" ? `tydzień od ${fullDate.format(row[0])}` : monthYear.format(row[0]);
      return [row[0], value, `${prefix || ""}${when}: ${percent(value)} pozytywnych (${whole.format(row[1] + row[2])} ocen)`];
    });

  // ------------------------------------------------------------------- home

  let redraw = [];

  function home() {
    document.title = "GamePulse — demo";
    const changed = DATA.games
      .map((game) => ({ game, line: changeLine(changesSince(game)) }))
      .filter((row) => row.line);
    return [
      el("div", { class: "hero" },
        el("h1", {}, "Co się dzieje z grami i dlaczego"),
        el("p", {}, "Śledzimy oceny i liczbę graczy na Steamie. Gdy coś się nagle zmienia, szukamy przyczyny.")),
      el("section", {},
        el("div", { class: "section-row" },
          el("h2", {}, "Co się zmieniło od Twojej ostatniej wizyty"), sincePicker()),
        el("div", { class: "panel list" },
          changed.length
            ? changed.map((row) => el("a", { class: "list-row", href: `#/gra/${row.game.appid}` },
                el("b", {}, row.game.name), el("span", { class: "muted" }, row.line)))
            : el("p", { class: "empty" }, "Nic nowego od ostatniej wizyty."))),
      el("section", {},
        el("h2", {}, "Gry"),
        el("div", { class: "grid" }, DATA.games.map((game) => {
          const rate = rate30(game);
          const episode = recentEpisode(game);
          return el("a", { class: "card", href: `#/gra/${game.appid}` },
            cover(game),
            el("div", { class: "card-body" },
              el("h3", {}, game.name),
              el("div", { class: "card-facts" },
                el("div", { class: "fact" },
                  el("b", { class: "num" }, game.players_now ? short.format(game.players_now) : "—"),
                  el("span", {}, "graczy teraz")),
                el("div", { class: "fact right" },
                  el("b", { class: "num" }, rate === null ? "—" : percent(rate)),
                  el("span", {}, "pozytywnych ocen, 30 dni"))),
              episode ? chip(KIND[episode.direction].tone, "Nietypowe oceny w ostatnich dniach")
                      : chip("quiet", "Bez niespodzianek")));
        }))),
    ];
  }

  // -------------------------------------------------------------- game page

  function eventCard(episode) {
    const kind = KIND[episode.direction];
    const verdict = VERDICT[episode.verdict] || VERDICT.unknown;
    const causes = episode.causes.filter((cause) => cause.claim);
    return el("article", { class: `event ${kind.tone}`, id: `e-${episode.id}` },
      el("div", { class: "event-top" },
        el("h3", {}, kind.title),
        el("span", { class: "event-when" }, period(episode.from, episode.to))),
      el("div", { class: "event-numbers num" },
        el("div", {}, el("b", {}, percent(episode.share)), el("span", {}, "pozytywnych ocen")),
        el("div", {}, el("b", {}, percent(episode.usual)), el("span", {}, "zwykle")),
        el("div", {}, el("b", {}, whole.format(episode.reviews)), el("span", {}, "ocen w tym czasie"))),
      el("div", { class: "why" },
        chip(verdict.tone, verdict.label),
        el("p", {}, episode.summary || "To wydarzenie nie zostało jeszcze przeanalizowane.")),
      causes.length ? el("details", {},
        el("summary", {}, "Skąd to wiemy"),
        el("div", { class: "causes" }, causes.map((cause) => el("div", { class: "cause" },
          el("p", {}, cause.claim),
          cause.quotes.map((quote) => el("div", { class: "quote" },
            `„${quote.text}”`,
            el("small", {}, [
              quote.positive ? "ocena pozytywna" : "ocena negatywna",
              quote.hours ? `${whole.format(quote.hours)} godz. gry` : null,
              LANGUAGE[quote.language] || null,
            ].filter(Boolean).join(" · ")))),
          el("div", { class: "sources" },
            cause.reviews_cited > cause.quotes.length
              ? el("span", { class: "muted" }, `To samo pisze jeszcze ${cause.reviews_cited - cause.quotes.length} sprawdzonych recenzji.`)
              : null,
            cause.posts.map((post) => el("span", {},
              post.press ? `Prasa${post.source ? ` (${post.source})` : ""}: ` : "Ogłoszenie twórców: ",
              post.url ? el("a", { href: post.url, target: "_blank", rel: "noopener noreferrer" }, post.title) : post.title)),
            cause.discounts.map((sale) => el("span", {}, `Przecena ${sale.percent}% w sklepie, ${sale.from} – ${sale.to}`)))))))
        : null);
  }

  function jumpToEvent(id) {
    const card = document.getElementById(`e-${id}`);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "start" });
    card.classList.remove("flash");
    requestAnimationFrame(() => card.classList.add("flash"));
  }

  // "What is going on with the game?": three short lines, each from numbers on this page.
  function summaryPanel(game) {
    const change = playerChange(game);
    const recent = rate30(game), usual = rateAll(game);
    const gap = recent !== null && usual !== null ? recent - usual : null;
    const latest = game.episodes.find((episode) => episode.to >= NOW - 60 * DAY);
    const news = game.news.find((item) => !item.press && (item.group === "content" || item.group === "update"));
    const changes = changesSince(game);
    const fresh = changeLine(changes);
    return el("section", {},
      el("h2", {}, "Co się dzieje z grą?"),
      el("div", { class: "panel facts" },
        el("div", { class: "fact-row" },
          el("span", { class: "fact-label" }, "Gracze"),
          el("p", {}, game.players_now
            ? [`${whole.format(game.players_now)} teraz`,
               change === null ? "." : Math.abs(change) < 1.5 ? ", tyle co dobę temu."
                 : `, o ${percent(Math.abs(change))} ${change > 0 ? "więcej" : "mniej"} niż dobę temu.`]
            : "Brak pomiaru.")),
        el("div", { class: "fact-row" },
          el("span", { class: "fact-label" }, "Oceny"),
          el("p", {}, recent === null ? "Brak ocen z ostatnich 30 dni."
            : [`${percent(recent)} pozytywnych w ostatnich 30 dniach. `,
               gap === null ? "" : Math.abs(gap) < 5 ? "To poziom typowy dla tej gry."
                 : `To wyraźnie ${gap > 0 ? "lepiej" : "gorzej"} niż zwykle (${percent(usual)}).`])),
        el("div", { class: "fact-row" },
          el("span", { class: "fact-label" }, "Ostatnio"),
          latest
            ? el("p", {}, `${period(latest.from, latest.to)}: ${KIND[latest.direction].brief}. `,
                el("a", { href: "#", onclick: (event) => { event.preventDefault(); jumpToEvent(latest.id); } }, "Zobacz przyczynę i dowody"))
            : news
              ? el("p", {}, `${fullDate.format(news.date)}: `,
                  el("a", { href: news.url, target: "_blank", rel: "noopener noreferrer" }, news.title))
              : el("p", {}, "Nic nietypowego w ostatnich tygodniach.")),
        el("div", { class: "fact-row" },
          el("span", { class: "fact-label" }, "Od wizyty"),
          el("p", {}, fresh ? `Nowe od Twojej ostatniej wizyty: ${fresh}.` : "Nic nowego od Twojej ostatniej wizyty."))));
  }

  function overviewTab(game) {
    const reviewChart = el("div", { class: "chart" });
    const playerChart = el("div", { class: "chart" });
    const playerPoints = game.players.map((row) => [row[0], row[1], `${dayHour.format(row[0])}: ${whole.format(row[1])} graczy`]);
    const bands = game.episodes.map((episode) => ({
      from: episode.from, to: episode.to, tone: KIND[episode.direction].tone,
      label: `${KIND[episode.direction].title}. Kliknij, żeby zobaczyć szczegóły.`,
      onclick: () => jumpToEvent(episode.id),
    }));
    queueMicrotask(() => {
      redraw = [
        lineChart(reviewChart, [{ points: reviewPoints(game) }], {
          label: "Odsetek pozytywnych ocen w czasie", bands,
          range: () => [0, 100], axis: (v) => `${Math.round(v)}%`, tick: (t) => monthYear.format(t),
        }),
        lineChart(playerChart, [{ points: playerPoints, area: true }], {
          label: "Liczba graczy w czasie",
          range: (values) => [0, Math.max(...values) * 1.1], axis: (v) => short.format(v), tick: (t) => dayMonth.format(t),
        }),
      ];
    });
    return [
      summaryPanel(game),
      el("section", {},
        el("div", { class: "section-head" },
          el("h2", {}, "Oceny graczy"),
          el("span", { class: "muted" }, "Jaka część ocen była pozytywna. Kolorowe pola to nietypowe okresy.")),
        el("div", { class: "panel" }, reviewChart,
          el("div", { class: "legend" },
            el("span", {}, el("i", { class: "bad" }), "oceny gorsze niż zwykle"),
            el("span", {}, el("i", { class: "good" }), "oceny lepsze niż zwykle"),
            el("span", {}, el("i", { class: "warn" }), "dużo więcej ocen")))),
      el("section", {},
        el("div", { class: "section-head" },
          el("h2", {}, "Co się wydarzyło"),
          el("span", { class: "muted" }, "Nietypowe okresy z ostatniego roku i to, co udało się o nich ustalić.")),
        game.episodes.length
          ? el("div", { class: "events" }, game.episodes.map(eventCard))
          : el("p", { class: "empty" }, "W ostatnim roku nie było nic nietypowego.")),
      el("section", {},
        el("div", { class: "section-head" },
          el("h2", {}, "Gracze w grze"),
          el("span", { class: "muted" }, "Ilu ludzi grało jednocześnie w ostatnich dniach.")),
        el("div", { class: "panel" }, playerChart)),
    ];
  }

  function newsTab(game) {
    const list = el("div", { class: "panel news" });
    const filters = el("div", { class: "filters", role: "group", "aria-label": "Rodzaj wiadomości" });
    const counts = {};
    for (const item of game.news) counts[item.group] = (counts[item.group] || 0) + 1;
    const since = sinceMs();
    const show = (group) => {
      const items = game.news.filter((item) => group === "all" || item.group === group).slice(0, 30);
      list.replaceChildren(...(items.length ? items.map((item) => el("div", { class: "news-item" },
        el("small", {},
          [item.source, fullDate.format(item.date), `dotyczy: ${game.name}`, GROUP_NAME[item.group]].filter(Boolean).join(" · "),
          item.date > since ? el("span", { class: "new" }, "nowe") : null),
        item.url ? el("a", { href: item.url, target: "_blank", rel: "noopener noreferrer" }, item.title) : el("span", {}, item.title),
        item.summary ? el("p", {}, item.summary) : null))
        : [el("p", { class: "empty" }, "Brak wiadomości tego rodzaju.")]));
      for (const button of filters.children) button.setAttribute("aria-pressed", String(button.dataset.group === group));
    };
    for (const [group, label] of NEWS_GROUPS) {
      const count = group === "all" ? game.news.length : counts[group] || 0;
      if (!count) continue;
      const button = el("button", { class: "filter", type: "button", onclick: () => show(group) },
        label, el("span", { class: "count num" }, count));
      button.dataset.group = group;
      filters.append(button);
    }
    show("all");
    return [el("section", {},
      el("div", { class: "section-head" },
        el("h2", {}, "Wiadomości"),
        el("span", { class: "muted" }, "Ogłoszenia twórców i artykuły prasowe, od najnowszych.")),
      filters, list)];
  }

  function aboutTab(game) {
    const about = game.about, price = game.price, critics = game.critics;
    const row = (label, value) => (value ? el("div", { class: "spec" }, el("dt", {}, label), el("dd", {}, value)) : null);
    const languages = about.languages.length
      ? `${about.languages.slice(0, 6).join(", ")}${about.languages.length > 6 ? ` i ${about.languages.length - 6} innych` : ""}`
      : null;
    const critic = (item) => el("div", { class: "critic" },
      el("b", { class: "score num" }, item.score),
      el("div", {}, el("span", {}, item.outlet), el("small", {}, item.covers)));
    const group = (when, title) => {
      const items = critics.rows.filter((item) => item.when === when);
      return items.length ? el("div", { class: "critic-group" }, el("h3", {}, title), items.map(critic)) : null;
    };
    const lastSales = price.sales.slice(-3).reverse();
    return [
      el("section", {},
        el("h2", {}, "O grze"),
        about.scope ? el("p", { class: "note" }, about.scope) : null,
        el("dl", { class: "panel specs" },
          row("Twórcy", about.developers.join(", ")),
          row("Wydawca", about.publishers.join(", ")),
          row("Premiera na Steamie", about.release),
          row("Tryby gry", about.modes.join(", ")),
          row("Systemy", about.systems.join(", ")),
          row("Języki", languages ? `${languages}${about.polish ? "" : " (bez polskiego)"}` : null),
          row("Funkcje", about.features.length
            ? `${about.features.join(", ")}${about.features_more ? ` i ${about.features_more} innych` : ""}` : null),
          row("Dodatki", about.dlc ? plural(about.dlc, "dodatek", "dodatki", "dodatków") : null),
          row("Powiązane wydania", about.related.length
            ? about.related.map((item) => el("div", {}, el("b", {}, item.name), `: ${item.note}`)) : null))),
      el("section", {},
        el("div", { class: "section-row" }, el("h2", {}, "Cena i dostępność"), el("span", { class: "muted" }, "Region: USA")),
        el("div", { class: "panel price" },
          price.free || price.final === 0
            ? el("div", { class: "price-now" }, el("b", {}, "Gra darmowa"))
            : price.final === null || price.final === undefined
              ? el("p", { class: "empty" }, "Brak ceny w danych.")
              : el("div", { class: "price-now" },
                  el("b", { class: "num" }, money(price.final, price.currency)),
                  price.discount ? el("s", { class: "num muted" }, money(price.regular, price.currency)) : null,
                  price.discount ? chip("good", `przecena ${price.discount}%`) : el("span", { class: "muted" }, "cena zwykła, bez przeceny")),
          el("div", { class: "price-meta muted" },
            el("span", {}, `Wydanie: ${game.name}`),
            price.checked ? el("span", {}, `Sprawdzono: ${fullDate.format(price.checked)}`) : null,
            price.known_from ? el("span", {}, `Historia cen od: ${fullDate.format(price.known_from)}`) : null),
          lastSales.length ? el("div", { class: "sales" },
            el("h3", {}, "Ostatnie przeceny"),
            lastSales.map((sale) => el("div", { class: "sale num" },
              el("b", {}, `−${sale.percent}%`),
              el("span", {}, sale.from === sale.to ? fullDate.format(sale.from) : `${dayMonth.format(sale.from)} – ${fullDate.format(sale.to)}`))))
            : null)),
      el("section", {},
        el("div", { class: "section-row" }, el("h2", {}, "Recenzje redakcji"), chip("warn", "dane przykładowe")),
        el("p", { class: "muted" }, "Tej sekcji jeszcze nie zasilamy. Redakcje i oceny poniżej są zmyślone i pokazują tylko układ."),
        el("div", { class: "panel critics" },
          critics.metacritic
            ? el("div", { class: "critic real" },
                el("b", { class: "score num" }, critics.metacritic.score),
                el("div", {},
                  el("a", { href: critics.metacritic.url, target: "_blank", rel: "noopener noreferrer" }, "Metacritic"),
                  el("small", {}, "średnia ocen redakcji, skala do 100, prawdziwa wartość ze Steama")))
            : null,
          group("launch", "Recenzje premierowe"),
          group("later", "Późniejsze oceny stanu gry"))),
    ];
  }

  const TABS = [["przeglad", "Przegląd", overviewTab], ["wiadomosci", "Wiadomości", newsTab], ["o-grze", "O grze", aboutTab]];

  function gamePage(game, tabKey) {
    document.title = `${game.name} — GamePulse`;
    const tab = TABS.find((item) => item[0] === tabKey) || TABS[0];
    const rate = rate30(game);
    return [
      el("a", { class: "back", href: "#/" }, "← Wszystkie gry"),
      el("div", { class: "game-head" },
        cover(game),
        el("div", { class: "game-title" },
          el("h1", {}, game.name),
          el("span", { class: "muted" }, [game.developers.join(", "), game.genres.join(", ")].filter(Boolean).join(" · ")),
          el("div", { class: "stats num" },
            el("div", { class: "stat" }, el("b", {}, game.players_now ? whole.format(game.players_now) : "—"), el("span", {}, "graczy teraz")),
            el("div", { class: "stat" }, el("b", {}, game.players_peak ? whole.format(game.players_peak) : "—"), el("span", {}, "najwięcej w ciągu doby")),
            el("div", { class: "stat" }, el("b", {}, rate === null ? "—" : percent(rate)), el("span", {}, "pozytywnych ocen, 30 dni"))))),
      el("nav", { class: "tabs", "aria-label": "Sekcje strony gry" },
        TABS.map(([key, label]) => el("a", { class: "tab", href: `#/gra/${game.appid}/${key}`,
          "aria-current": key === tab[0] ? "page" : null }, label)),
        el("a", { class: "tab side", href: `#/porownaj/${game.appid}` }, "Porównaj z inną grą")),
      ...tab[2](game),
    ];
  }

  // ---------------------------------------------------------------- compare

  function comparePage(firstId, secondId) {
    document.title = "Porównanie gier — GamePulse";
    const a = DATA.games.find((g) => String(g.appid) === firstId) || DATA.games[0];
    const b = DATA.games.find((g) => String(g.appid) === secondId && g !== a) || DATA.games.find((g) => g !== a);
    const pick = (current, other, position) => el("select", { "aria-label": `Gra ${position}`,
      onchange: (event) => {
        location.hash = position === 1 ? `#/porownaj/${event.target.value}/${b.appid}` : `#/porownaj/${a.appid}/${event.target.value}`;
      } },
      DATA.games.filter((g) => g !== other).map((g) => el("option", { value: g.appid, selected: g === current }, g.name)));

    const year = NOW - 365 * DAY;
    const episodes = (game, direction) => game.episodes.filter((e) => e.to > year && (!direction || e.direction === direction)).length;
    const posts = (game) => game.news.filter((item) => !item.press && item.date > NOW - 30 * DAY).length;
    const priceText = (game) => (game.price.free || game.price.final === 0 ? "darmowa" : money(game.price.final, game.price.currency) || "—");
    // [label, value of a game, how to print it, which side is "better": 1 higher, -1 lower, 0 none]
    const metrics = [
      ["Graczy teraz", (g) => g.players_now, (v) => whole.format(v), 1],
      ["Najwięcej w ciągu doby", (g) => g.players_peak, (v) => whole.format(v), 1],
      ["Pozytywne oceny, 30 dni", rate30, percent, 1],
      ["Pozytywne oceny, cała historia", rateAll, percent, 1],
      ["Nietypowe okresy w ostatnim roku", (g) => episodes(g), (v) => whole.format(v), 0],
      ["W tym z gorszymi ocenami", (g) => episodes(g, "negative"), (v) => whole.format(v), -1],
      ["Ogłoszenia twórców, 30 dni", posts, (v) => whole.format(v), 0],
    ];
    const metricRow = ([label, value, print, better]) => {
      const left = value(a), right = value(b);
      const top = Math.max(left || 0, right || 0) || 1;
      const lead = better && left !== null && right !== null && left !== right
        ? ((left > right) === (better > 0) ? "a" : "b") : null;
      const side = (amount, tone) => el("div", { class: `side ${tone}${lead === tone ? " lead" : ""}` },
        el("b", { class: "num" }, amount === null || amount === undefined ? "—" : print(amount)),
        el("i", { style: `width:${Math.max(2, (100 * (amount || 0)) / top)}%` }));
      return el("div", { class: "metric" }, el("span", { class: "metric-label" }, label), side(left, "a"), side(right, "b"));
    };

    const reviewChart = el("div", { class: "chart" });
    const playerChart = el("div", { class: "chart" });
    // Each game's player count as a share of its own highest value, so a small game can be read next to a big one.
    const shape = (game) => {
      const top = Math.max(...game.players.map((row) => row[1]), 1);
      return game.players.map((row) => [row[0], (100 * row[1]) / top,
        `${game.name}, ${dayHour.format(row[0])}: ${whole.format(row[1])} graczy`]);
    };
    queueMicrotask(() => {
      redraw = [
        lineChart(reviewChart, [{ points: reviewPoints(a, `${a.name}, `), tone: "a" }, { points: reviewPoints(b, `${b.name}, `), tone: "b" }], {
          label: "Odsetek pozytywnych ocen obu gier", range: () => [0, 100],
          axis: (v) => `${Math.round(v)}%`, tick: (t) => monthYear.format(t),
        }),
        lineChart(playerChart, [{ points: shape(a), tone: "a" }, { points: shape(b), tone: "b" }], {
          label: "Liczba graczy obu gier względem własnego szczytu", range: () => [0, 100],
          axis: (v) => `${Math.round(v)}%`, tick: (t) => dayMonth.format(t),
        }),
      ];
    });
    const legend = () => el("div", { class: "legend" },
      el("span", {}, el("i", { class: "a" }), a.name), el("span", {}, el("i", { class: "b" }), b.name));

    return [
      el("div", { class: "hero" },
        el("h1", {}, "Porównaj dwie gry"),
        el("p", {}, "Te same liczby obok siebie: gracze, oceny i to, jak często dzieje się coś nietypowego.")),
      el("div", { class: "versus" },
        el("div", { class: "versus-side a" }, cover(a), pick(a, b, 1)),
        el("span", { class: "versus-mid" }, "i"),
        el("div", { class: "versus-side b" }, cover(b), pick(b, a, 2))),
      el("section", {},
        el("h2", {}, "W liczbach"),
        el("div", { class: "panel metrics" },
          metrics.map(metricRow),
          el("div", { class: "metric" }, el("span", { class: "metric-label" }, "Cena"),
            el("div", { class: "side a" }, el("b", { class: "num" }, priceText(a))),
            el("div", { class: "side b" }, el("b", { class: "num" }, priceText(b)))))),
      el("section", {},
        el("div", { class: "section-head" },
          el("h2", {}, "Oceny w czasie"),
          el("span", { class: "muted" }, "Jaka część ocen była pozytywna.")),
        el("div", { class: "panel" }, reviewChart, legend())),
      el("section", {},
        el("div", { class: "section-head" },
          el("h2", {}, "Rytm doby"),
          el("span", { class: "muted" }, "Liczba graczy jako część własnego szczytu, żeby dało się zestawić małą grę z dużą.")),
        el("div", { class: "panel" }, playerChart, legend())),
    ];
  }

  // ------------------------------------------------------------------ router

  function route() {
    hideTip();
    redraw = [];
    const parts = location.hash.replace(/^#\/?/, "").split("/");
    let page;
    if (parts[0] === "gra") {
      const game = DATA.games.find((g) => String(g.appid) === parts[1]);
      page = game ? gamePage(game, parts[2]) : home();
    } else if (parts[0] === "porownaj") {
      page = comparePage(parts[1], parts[2]);
    } else {
      page = home();
    }
    app.replaceChildren(...page.filter(Boolean));
    for (const link of document.querySelectorAll(".top-link")) {
      const active = link.getAttribute("href") === "#/porownaj" ? parts[0] === "porownaj" : parts[0] !== "porownaj";
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    }
    window.scrollTo(0, 0);
  }

  document.getElementById("foot").textContent =
    `Wersja demonstracyjna. Stan danych: ${fullDate.format(NOW)}. Źródła: Steam, historia cen z IsThereAnyDeal. `
    + "Przyczyny wskazuje automat na podstawie recenzji i ogłoszeń, więc mogą być błędne.";
  window.addEventListener("hashchange", route);
  let resizing;
  window.addEventListener("resize", () => {
    clearTimeout(resizing);
    resizing = setTimeout(() => redraw.forEach((draw) => draw()), 120);
  });
  route();
})();
