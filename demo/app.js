// GamePulse demo: a static page over the snapshot in data.js. No libraries.
(function () {
  "use strict";

  const DATA = window.GAMEPULSE_DEMO || { games: [], generated: Date.now() };
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
      else node.setAttribute(key, value);
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

  function period(from, to) {
    const last = to - DAY; // the end is the first day after the period
    if (last <= from) return fullDate.format(from);
    const sameYear = new Date(from).getUTCFullYear() === new Date(last).getUTCFullYear();
    return `${(sameYear ? dayMonth : fullDate).format(from)} – ${fullDate.format(last)}`;
  }

  const KIND = {
    negative: { tone: "bad", title: "Oceny wyraźnie gorsze niż zwykle" },
    positive: { tone: "good", title: "Oceny wyraźnie lepsze niż zwykle" },
    volume: { tone: "warn", title: "Dużo więcej ocen niż zwykle" },
  };
  const VERDICT = {
    likely: { tone: "good", label: "Prawdopodobna przyczyna" },
    possible: { tone: "warn", label: "Możliwa przyczyna" },
    unknown: { tone: "quiet", label: "Przyczyna nieznana" },
  };
  const LANGUAGE = { english: "po angielsku", polish: "po polsku", schinese: "po chińsku", russian: "po rosyjsku",
    german: "po niemiecku", french: "po francusku", spanish: "po hiszpańsku", koreana: "po koreańsku",
    japanese: "po japońsku", brazilian: "po portugalsku", turkish: "po turecku" };

  function chip(tone, text) {
    return el("span", { class: `chip ${tone}` }, text);
  }

  function cover(game) {
    const image = el("img", { class: "cover", src: game.image, alt: "", loading: "lazy" });
    // Without a network the picture is missing; the coloured block behind it stays.
    image.addEventListener("error", () => image.removeAttribute("src"));
    return image;
  }

  function recentEpisode(game) {
    return game.episodes.find((episode) => episode.to >= DATA.generated - 21 * DAY) || null;
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

  // points: [[time, value, label]]; bands: [{from, to, tone, label, onclick}]
  function lineChart(host, points, options) {
    const draw = () => {
      host.replaceChildren();
      if (points.length < 2) {
        host.append(el("p", { class: "empty" }, "Za mało danych, żeby narysować wykres."));
        return;
      }
      const width = Math.max(300, host.clientWidth);
      const height = Math.round(Math.min(280, Math.max(190, width * 0.3)));
      const pad = { left: 44, right: 12, top: 10, bottom: 26 };
      const t0 = points[0][0], t1 = points[points.length - 1][0];
      const [y0, y1] = options.range(points.map((p) => p[1]));
      const x = (t) => pad.left + ((t - t0) / (t1 - t0 || 1)) * (width - pad.left - pad.right);
      const y = (v) => pad.top + (1 - (v - y0) / (y1 - y0 || 1)) * (height - pad.top - pad.bottom);
      const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": options.label });

      for (const band of options.bands || []) {
        const from = Math.max(t0, band.from), to = Math.min(t1, band.to);
        if (to < t0 || from > t1) continue;
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
      const path = points.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
      if (options.area) {
        root.append(svg("path", { class: "area",
          d: `${path}L${x(t1).toFixed(1)},${y(y0)}L${x(t0).toFixed(1)},${y(y0)}Z` }));
      }
      root.append(svg("path", { class: "line", d: path }));
      const dot = svg("circle", { class: "dot", r: 4.5, visibility: "hidden" });
      root.append(dot);
      const nearest = (event) => {
        const box = root.getBoundingClientRect();
        const at = ((event.clientX - box.left) / box.width) * width;
        return points.reduce((best, p) => (Math.abs(x(p[0]) - at) < Math.abs(x(best[0]) - at) ? p : best));
      };
      root.addEventListener("mousemove", (event) => {
        if (event.target.classList.contains("band")) { dot.setAttribute("visibility", "hidden"); return; }
        const point = nearest(event);
        dot.setAttribute("cx", x(point[0]));
        dot.setAttribute("cy", y(point[1]));
        dot.setAttribute("visibility", "visible");
        showTip(event, point[2]);
      });
      root.addEventListener("mouseleave", () => { dot.setAttribute("visibility", "hidden"); hideTip(); });
      host.append(root);
    };
    draw();
    return draw;
  }

  // ------------------------------------------------------------------ pages

  let redraw = [];

  function home() {
    document.title = "GamePulse — demo";
    return [
      el("div", { class: "hero" },
        el("h1", {}, "Co się dzieje z grami i dlaczego"),
        el("p", {}, "Śledzimy oceny i liczbę graczy na Steamie. Gdy coś się nagle zmienia, szukamy przyczyny.")),
      el("div", { class: "grid" }, DATA.games.map((game) => {
        const rate = share(game.reviews_30d.positive, game.reviews_30d.negative);
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
      })),
    ];
  }

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

  function gamePage(game) {
    document.title = `${game.name} — GamePulse`;
    const rate = share(game.reviews_30d.positive, game.reviews_30d.negative);
    const reviewChart = el("div", { class: "chart" });
    const playerChart = el("div", { class: "chart" });
    const reviewPoints = game.reviews
      .filter((row) => row[1] + row[2] > 0)
      .map((row) => {
        const value = share(row[1], row[2]);
        const when = game.reviews_grain === "week" ? `tydzień od ${fullDate.format(row[0])}` : monthYear.format(row[0]);
        return [row[0], value, `${when}: ${percent(value)} pozytywnych (${whole.format(row[1] + row[2])} ocen)`];
      });
    const playerPoints = game.players.map((row) => [row[0], row[1], `${dayHour.format(row[0])}: ${whole.format(row[1])} graczy`]);
    const bands = game.episodes.map((episode) => ({
      from: episode.from, to: episode.to, tone: KIND[episode.direction].tone,
      label: `${KIND[episode.direction].title}. Kliknij, żeby zobaczyć szczegóły.`,
      onclick: () => {
        const card = document.getElementById(`e-${episode.id}`);
        card.scrollIntoView({ behavior: "smooth", block: "start" });
        card.classList.remove("flash");
        requestAnimationFrame(() => card.classList.add("flash"));
      },
    }));
    const page = [
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
      game.news.length ? el("section", {},
        el("div", { class: "section-head" }, el("h2", {}, "Ostatnie ogłoszenia twórców")),
        el("div", { class: "panel news" }, game.news.map((item) => el("div", { class: "news-item" },
          el("small", {}, fullDate.format(item.date)),
          item.url ? el("a", { href: item.url, target: "_blank", rel: "noopener noreferrer" }, item.title) : el("span", {}, item.title),
          item.summary ? el("p", {}, item.summary) : null)))) : null,
    ];
    // Charts need the page in the document to know their width.
    queueMicrotask(() => {
      redraw = [
        lineChart(reviewChart, reviewPoints, {
          label: "Odsetek pozytywnych ocen w czasie", bands,
          range: () => [0, 100], axis: (v) => `${Math.round(v)}%`, tick: (t) => monthYear.format(t),
        }),
        lineChart(playerChart, playerPoints, {
          label: "Liczba graczy w czasie", area: true,
          range: (values) => [0, Math.max(...values) * 1.1], axis: (v) => short.format(v), tick: (t) => dayMonth.format(t),
        }),
      ];
    });
    return page;
  }

  function route() {
    hideTip();
    redraw = [];
    const match = location.hash.match(/^#\/gra\/(\d+)/);
    const game = match && DATA.games.find((g) => String(g.appid) === match[1]);
    app.replaceChildren(...(game ? gamePage(game) : home()).filter(Boolean));
    window.scrollTo(0, 0);
  }

  document.getElementById("foot").textContent =
    `Wersja demonstracyjna. Stan danych: ${fullDate.format(DATA.generated)}. Źródła: Steam, historia cen z IsThereAnyDeal. `
    + "Przyczyny wskazuje automat na podstawie recenzji i ogłoszeń, więc mogą być błędne.";
  window.addEventListener("hashchange", route);
  let resizing;
  window.addEventListener("resize", () => {
    clearTimeout(resizing);
    resizing = setTimeout(() => redraw.forEach((draw) => draw()), 120);
  });
  route();
})();
