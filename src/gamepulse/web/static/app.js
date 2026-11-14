"use strict";

const view = document.getElementById("view");
const statusEl = document.getElementById("status");
const drawer = document.getElementById("drawer");
const drawerBody = document.getElementById("drawer-body");

const nf = new Intl.NumberFormat("pl-PL");
const rtf = new Intl.RelativeTimeFormat("pl", { numeric: "auto" });
const dateFmt = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const dayMonthFmt = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short" });
const monthYearFmt = new Intl.DateTimeFormat("pl-PL", { month: "short", year: "numeric" });
const timeFmt = new Intl.DateTimeFormat("pl-PL", { hour: "2-digit", minute: "2-digit" });

const RANGES = [["24h", "24 h"], ["7d", "7 dni"], ["30d", "30 dni"], ["1y", "Rok"], ["all", "Całość"]];
const COLORS = { accent: "#5aa9ff", up: "#4ec98a", down: "#f0685f", muted: "#8b95a3", line: "#2a313b", text: "#e6e9ee" };

let chart = null;
let refreshTimer = null;
let renderToken = 0;

// ---------------------------------------------------------------- helpers

/** Build an element; children are appended as nodes or as plain text. */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

function ago(ms) {
  const diff = ms - Date.now();
  const minutes = Math.round(diff / 60000);
  if (Math.abs(minutes) < 60) return rtf.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 48) return rtf.format(hours, "hour");
  const days = Math.round(hours / 24);
  if (Math.abs(days) < 60) return rtf.format(days, "day");
  const months = Math.round(days / 30.4);
  if (Math.abs(months) < 24) return rtf.format(months, "month");
  return rtf.format(Math.round(days / 365), "year");
}

function pctText(value) {
  return value === null || value === undefined ? "—" : `${String(value).replace(".", ",")}%`;
}

function changeNode(change) {
  if (change === null || change === undefined) return null;
  const cls = change > 0 ? "up" : change < 0 ? "down" : "muted";
  const arrow = change > 0 ? "▲" : change < 0 ? "▼" : "•";
  return el("span", { class: cls, title: "Zmiana względem tej samej pory wczoraj" },
    `${arrow} ${String(Math.abs(change)).replace(".", ",")}%`);
}

function safeUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function sparkline(points) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "spark");
  svg.setAttribute("viewBox", "0 0 100 30");
  svg.setAttribute("preserveAspectRatio", "none");
  if (points.length >= 2) {
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
    const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
    const line = document.createElementNS(ns, "polyline");
    line.setAttribute("points", points.map(([x, y]) => {
      const px = x1 === x0 ? 50 : ((x - x0) / (x1 - x0)) * 100;
      const py = y1 === y0 ? 15 : 28 - ((y - y0) / (y1 - y0)) * 26;
      return `${px.toFixed(2)},${py.toFixed(2)}`;
    }).join(" "));
    svg.append(line);
  }
  return svg;
}

/** News bodies are HTML or BBCode from outside; reduce them to plain text. */
function plainText(raw) {
  let text = String(raw || "")
    .replace(/\{STEAM_CLAN_IMAGE\}\S*/g, "")
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\/\s*(p|div|h[1-6]|li|ul|ol|tr)\s*>/gi, "\n")
    .replace(/<\s*li[^>]*>/gi, "• ")
    .replace(/\[\*\]/g, "• ")
    .replace(/\[\/?(h[1-6]|p|list|olist|table|tr)\]/gi, "\n")
    .replace(/\[img[^\]]*\][^\[]*\[\/img\]/gi, "")
    .replace(/\[previewyoutube[^\]]*\]\s*\[\/previewyoutube\]/gi, "")
    .replace(/\[\/?[a-z*][^\]\n]{0,200}\]/gi, "");
  // Parsed into an inert document and read back as text: nothing is executed.
  text = new DOMParser().parseFromString(text, "text/html").body.textContent || "";
  return text.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

function closeDrawer() {
  drawer.hidden = true;
  drawerBody.replaceChildren();
}

document.getElementById("drawer-close").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });

// ---------------------------------------------------------------- status bar

function renderStatus(status) {
  if (!status || status.last_ts === null) {
    statusEl.replaceChildren(el("span", {}, el("span", { class: "dot" }), "Brak pomiarów"));
    return;
  }
  const fresh = Date.now() - status.last_ts < 12 * 60000;
  statusEl.replaceChildren(
    el("span", { title: dateTimeFmt.format(status.last_ts) },
      el("span", { class: `dot ${fresh ? "ok" : "stale"}` }), `Ostatni pomiar ${ago(status.last_ts)}`),
    el("span", {}, `Pomiary w 24 h: ${nf.format(status.runs_24h)}`),
    el("span", { class: status.gaps_24h ? "" : "muted", title: "Przerwy dłuższe niż 15 minut między pomiarami" },
      `Przerwy: ${status.gaps_24h}`),
    el("span", { class: "muted" }, `Zbierane od ${dateTimeFmt.format(status.first_ts)}`),
  );
}

// ---------------------------------------------------------------- overview

function coverNode(game) {
  const image = safeUrl(game.image);
  if (!image) return el("div", { class: "cover" }, game.name);
  const img = el("img", { src: image, alt: "", loading: "lazy" });
  img.addEventListener("error", () => img.replaceWith(el("div", { class: "cover" }, game.name)));
  return img;
}

function gameTile(game) {
  const recent = game.reviews.recent;
  return el("a", { class: "tile", href: `#/game/${game.appid}` },
    coverNode(game),
    el("div", { class: "tile-body" },
      el("div", { class: "tile-name", title: game.name }, game.name),
      el("div", { class: "tile-players" },
        el("strong", {}, game.players === null ? "—" : nf.format(game.players)),
        el("span", { class: "muted" }, "graczy"),
        changeNode(game.change_24h)),
      sparkline(game.spark),
      el("div", { class: "tile-meta" },
        el("span", { title: `Recenzje z 30 dni: ${nf.format(recent.up)} pozytywnych, ${nf.format(recent.down)} negatywnych` },
          `Recenzje 30 dni: ${pctText(recent.pct)}`),
        el("span", { title: game.last_news ? game.last_news.title : "" },
          game.last_news ? `News ${ago(game.last_news.date_ms)}` : "Brak newsów")),
    ));
}

function fivemTile(fivem) {
  return el("div", { class: "tile", title: "Dane z serwerów FiveM, nie ze Steama" },
    el("div", { class: "cover" }, "FiveM"),
    el("div", { class: "tile-body" },
      el("div", { class: "tile-name" }, "FiveM (poza Steamem)"),
      el("div", { class: "tile-players" },
        el("strong", {}, fivem.players === null ? "—" : nf.format(fivem.players)),
        el("span", { class: "muted" }, "graczy")),
      sparkline(fivem.spark),
      el("div", { class: "tile-meta" },
        el("span", {}, "Mod do GTA V"),
        el("span", {}, fivem.players_ts ? ago(fivem.players_ts) : ""))),
  );
}

async function renderOverview(token) {
  const data = await api("/api/overview");
  if (token !== renderToken) return;
  renderStatus(data.status);
  const tiles = data.games.map(gameTile);
  if (data.fivem.players !== null) {
    // Slot the FiveM tile where its player count belongs in the ranking.
    const index = data.games.findIndex((g) => g.players === null || g.players < data.fivem.players);
    tiles.splice(index === -1 ? tiles.length : index, 0, fivemTile(data.fivem));
  }
  view.replaceChildren(el("div", { class: "tiles" }, tiles));
}

// ---------------------------------------------------------------- game page

function statCard(label, value, sub) {
  return el("div", { class: "stat" },
    el("div", { class: "label" }, label),
    el("div", { class: "value" }, value),
    sub ? el("div", { class: "sub" }, sub) : null);
}

function reviewSub(summary) {
  return summary.up + summary.down
    ? `${nf.format(summary.up)} pozytywnych, ${nf.format(summary.down)} negatywnych`
    : "brak recenzji";
}

async function openNews(appid, gid) {
  drawer.hidden = false;
  drawerBody.replaceChildren(el("p", { class: "muted" }, "Wczytywanie…"));
  try {
    const item = await api(`/api/games/${appid}/news/${encodeURIComponent(gid)}`);
    const link = safeUrl(item.url);
    drawerBody.replaceChildren(
      el("h3", {}, item.title || "(bez tytułu)"),
      el("div", { class: "meta" },
        `${dateTimeFmt.format(item.date_ms)} · ${item.official ? "oficjalny" : "zewnętrzny"} · ${item.feedlabel || ""}`,
        link ? [" · ", el("a", { href: link, target: "_blank", rel: "noopener noreferrer" }, "źródło")] : null),
      el("div", { class: "body" }, plainText(item.contents) || "Brak treści."),
    );
  } catch (error) {
    drawerBody.replaceChildren(el("p", { class: "muted" }, "Nie udało się wczytać newsa."));
  }
}

function drawChart(container, data, appid) {
  if (chart) chart.dispose();
  chart = echarts.init(container, null, { renderer: "canvas" });
  const { from, to } = data.range;
  const official = data.news.filter((n) => n.official).map((n) => [n.date_ms, 1, n.title, n.gid]);
  const external = data.news.filter((n) => !n.official).map((n) => [n.date_ms, 0, n.title, n.gid]);
  const up = data.reviews.points.map(([t, u]) => [t, u]);
  const down = data.reviews.points.map(([t, , d]) => [t, -d]);
  // The visible span decides the label: hours, days, or months and years.
  const axisDate = (value) => {
    const zoom = chart.getOption().dataZoom[0];
    const span = (to - from) * ((zoom.end - zoom.start) / 100);
    if (span <= 2 * 86400000) return timeFmt.format(value);
    if (span <= 120 * 86400000) return dayMonthFmt.format(value);
    return monthYearFmt.format(value);
  };
  const axis = (gridIndex, showLabels) => ({
    type: "time",
    gridIndex,
    min: from,
    max: to,
    axisLine: { lineStyle: { color: COLORS.line } },
    axisLabel: { show: showLabels, color: COLORS.muted, hideOverlap: true, formatter: axisDate },
    axisTick: { show: showLabels },
    splitLine: { show: false },
    axisPointer: { label: { show: gridIndex === 2 } },
  });
  const valueAxis = (gridIndex, name, extra = {}) => ({
    type: "value",
    gridIndex,
    name,
    nameTextStyle: { color: COLORS.muted, align: "left" },
    axisLabel: { color: COLORS.muted, formatter: (v) => nf.format(Math.abs(v)) },
    splitLine: { lineStyle: { color: COLORS.line, type: "dashed" } },
    ...extra,
  });
  const barWidth = data.reviews.granularity === "day" ? "55%" : "70%";

  chart.setOption({
    backgroundColor: "transparent",
    textStyle: { color: COLORS.text, fontFamily: "system-ui, sans-serif" },
    animation: false,
    grid: [
      { left: 64, right: 24, top: 30, height: "44%" },
      { left: 64, right: 24, top: "58%", height: 34 },
      { left: 64, right: 24, top: "71%", bottom: 34 },
    ],
    xAxis: [axis(0, false), axis(1, false), axis(2, true)],
    yAxis: [
      valueAxis(0, "Gracze", { scale: true }),
      { type: "value", gridIndex: 1, min: -0.6, max: 1.6, show: false },
      valueAxis(2, data.reviews.granularity === "day" ? "Recenzje dziennie" : "Recenzje miesięcznie"),
    ],
    axisPointer: { link: [{ xAxisIndex: "all" }], lineStyle: { color: COLORS.muted } },
    dataZoom: [{ type: "inside", xAxisIndex: [0, 1, 2], filterMode: "none" }],
    tooltip: {
      trigger: "axis",
      backgroundColor: "#1e242c",
      borderColor: COLORS.line,
      textStyle: { color: COLORS.text, fontSize: 13 },
      formatter(params) {
        const items = Array.isArray(params) ? params : [params];
        if (!items.length) return "";
        const box = document.createElement("div");
        const header = document.createElement("div");
        header.style.color = COLORS.muted;
        header.textContent = dateTimeFmt.format(items[0].value[0]);
        box.append(header);
        let upValue = null;
        let downValue = null;
        for (const item of items) {
          const row = document.createElement("div");
          if (item.seriesName === "Gracze") row.textContent = `Gracze: ${nf.format(item.value[1])}`;
          else if (item.seriesName === "Pozytywne") { upValue = item.value[1]; continue; }
          else if (item.seriesName === "Negatywne") { downValue = -item.value[1]; continue; }
          else continue;
          box.append(row);
        }
        if (upValue !== null || downValue !== null) {
          const u = upValue || 0;
          const d = downValue || 0;
          const row = document.createElement("div");
          row.textContent = `Recenzje: ${nf.format(u)} 👍 / ${nf.format(d)} 👎` + (u + d ? ` (${Math.round((100 * u) / (u + d))}%)` : "");
          box.append(row);
        }
        return box;
      },
    },
    series: [
      {
        name: "Gracze",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: data.ccu,
        showSymbol: data.ccu.length < 3,
        symbolSize: 5,
        lineStyle: { color: COLORS.accent, width: 1.6 },
        itemStyle: { color: COLORS.accent },
        areaStyle: { color: "rgba(90,169,255,0.10)" },
        // A missing stretch (computer off) must show as a gap, not a straight line.
        connectNulls: false,
      },
      {
        name: "Oficjalne",
        type: "scatter",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: official,
        symbolSize: 9,
        itemStyle: { color: COLORS.accent, opacity: 0.9 },
        tooltip: { trigger: "item", formatter: (p) => tooltipForNews(p) },
        cursor: "pointer",
      },
      {
        name: "Zewnętrzne",
        type: "scatter",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: external,
        symbolSize: 6,
        itemStyle: { color: COLORS.muted, opacity: 0.55 },
        tooltip: { trigger: "item", formatter: (p) => tooltipForNews(p) },
        cursor: "pointer",
      },
      { name: "Pozytywne", type: "bar", stack: "reviews", xAxisIndex: 2, yAxisIndex: 2, data: up, barWidth, itemStyle: { color: COLORS.up } },
      { name: "Negatywne", type: "bar", stack: "reviews", xAxisIndex: 2, yAxisIndex: 2, data: down, barWidth, itemStyle: { color: COLORS.down } },
    ],
  });
  chart.on("click", (params) => {
    if (params.seriesName === "Oficjalne" || params.seriesName === "Zewnętrzne") openNews(appid, params.value[3]);
  });
}

function tooltipForNews(params) {
  const box = document.createElement("div");
  box.style.maxWidth = "320px";
  box.style.whiteSpace = "normal";
  const date = document.createElement("div");
  date.style.color = COLORS.muted;
  date.textContent = `${dateTimeFmt.format(params.value[0])} · ${params.seriesName.toLowerCase()}`;
  const title = document.createElement("div");
  title.textContent = params.value[2] || "(bez tytułu)";
  box.append(date, title);
  return box;
}

/** Break the line wherever two neighbouring points are too far apart. */
function withGaps(points, bucketMs) {
  const limit = bucketMs ? bucketMs * 2.5 : 15 * 60000;
  const out = [];
  points.forEach((point, index) => {
    if (index && point[0] - points[index - 1][0] > limit) out.push([points[index - 1][0] + 1, null]);
    out.push(point);
  });
  return out;
}

async function renderGame(appid, rangeKey, token) {
  const [data, overview] = await Promise.all([
    api(`/api/games/${appid}?range=${rangeKey}`),
    api("/api/overview"),
  ]);
  if (token !== renderToken) return;
  renderStatus(overview.status);
  const tile = overview.games.find((g) => g.appid === appid) || {};
  const meta = data.meta;
  const summary = data.review_summary;
  data.ccu = withGaps(data.ccu, data.ccu_bucket_ms);

  const image = safeUrl(meta.image);
  const facts = [
    meta.developers.length ? `Studio: ${meta.developers.join(", ")}` : null,
    meta.publishers.length && meta.publishers.join() !== meta.developers.join() ? `Wydawca: ${meta.publishers.join(", ")}` : null,
    meta.release_date ? `Premiera: ${meta.release_date}` : null,
    meta.genres.length ? meta.genres.join(" · ") : null,
  ].filter(Boolean);

  let newsFilter = "official";
  const newsList = el("ul", { class: "news-list" });
  const newsCount = el("span", { class: "muted" });
  const filterChips = el("div", { class: "chips" });
  function renderNews() {
    const items = data.news.filter((n) => newsFilter === "all" || (newsFilter === "official") === n.official);
    newsCount.textContent = `${nf.format(items.length)} w wybranym okresie`;
    filterChips.replaceChildren(...[["official", "Oficjalne"], ["external", "Zewnętrzne"], ["all", "Wszystkie"]].map(([key, label]) =>
      el("button", { class: `chip ${newsFilter === key ? "active" : ""}`, onclick: () => { newsFilter = key; renderNews(); } }, label)));
    const shown = items.slice(0, 200);
    newsList.replaceChildren(...(shown.length ? shown.map((n) =>
      el("li", { class: n.official ? "official" : "" },
        el("button", { onclick: () => openNews(appid, n.gid) },
          el("span", { class: "date" }, dateFmt.format(n.date_ms)),
          el("span", { class: "title" }, n.title || "(bez tytułu)"),
          el("span", { class: "feed" }, n.feedlabel || "")))) : [el("li", { class: "empty" }, "Brak newsów w tym okresie.")]));
    if (items.length > shown.length) newsList.append(el("li", { class: "empty" }, `Pokazano 200 najnowszych z ${nf.format(items.length)}. Zawęź okres, żeby zobaczyć resztę.`));
  }

  const chartBox = el("div", { id: "chart" });
  const firstCcu = overview.status.first_ts;
  const note = firstCcu && data.range.from < firstCcu
    ? `Liczba graczy jest zbierana od ${dateTimeFmt.format(firstCcu)}. Steam nie udostępnia wcześniejszej historii, więc starsza część wykresu jest pusta.`
    : null;

  view.replaceChildren(
    el("a", { class: "back", href: "#/" }, "← Wszystkie gry"),
    el("div", { class: "game-head" },
      image ? el("img", { src: image, alt: "" }) : null,
      el("div", {},
        el("h1", {}, meta.name),
        el("div", { class: "facts" }, facts.map((f) => el("span", {}, f)),
          el("a", { href: meta.store_url, target: "_blank", rel: "noopener noreferrer" }, "Strona w Steamie ↗")),
        meta.description ? el("div", { class: "desc" }, meta.description) : null)),
    el("div", { class: "stats" },
      statCard("Graczy teraz (Steam)", tile.players == null ? "—" : nf.format(tile.players), tile.players_ts ? ago(tile.players_ts) : "brak pomiaru"),
      statCard("Zmiana 24 h", changeNode(tile.change_24h) || "—", "względem tej samej pory wczoraj"),
      statCard("Recenzje, 30 dni", pctText(summary.recent.pct), reviewSub(summary.recent)),
      statCard("Recenzje, całość", pctText(summary.all.pct), reviewSub(summary.all))),
    el("div", { class: "panel" },
      el("div", { class: "panel-head" },
        el("h2", {}, "Gracze, wydarzenia i recenzje"),
        el("div", { class: "chips" }, RANGES.map(([key, label]) =>
          el("a", { class: `chip ${key === rangeKey ? "active" : ""}`, href: `#/game/${appid}/${key}` }, label)))),
      el("div", { class: "legend" },
        el("span", {}, el("i", { style: `background:${COLORS.accent}` }), "gracze i oficjalne newsy"),
        el("span", {}, el("i", { style: `background:${COLORS.muted}` }), "newsy zewnętrzne"),
        el("span", {}, el("i", { style: `background:${COLORS.up}` }), "recenzje pozytywne"),
        el("span", {}, el("i", { style: `background:${COLORS.down}` }), "recenzje negatywne"),
        el("span", {}, "Kliknij kropkę, żeby przeczytać news. Kółkiem myszy przybliżasz.")),
      chartBox,
      note ? el("div", { class: "chart-note" }, note) : null),
    el("div", { class: "panel why" },
      el("h2", {}, "Dlaczego?"),
      el("p", {}, "Tu pojawią się wyjaśnienia nietypowych skoków i spadków, razem z dowodami. Ta część powstanie razem z agentem.")),
    el("div", { class: "panel" },
      el("div", { class: "panel-head" }, el("h2", {}, "Newsy"), newsCount, filterChips),
      newsList),
  );
  renderNews();
  drawChart(chartBox, data, appid);
}

// ---------------------------------------------------------------- router

async function route() {
  const token = ++renderToken;
  clearInterval(refreshTimer);
  closeDrawer();
  if (chart) { chart.dispose(); chart = null; }
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  try {
    if (parts[0] === "game" && /^\d+$/.test(parts[1] || "")) {
      const rangeKey = RANGES.some(([key]) => key === parts[2]) ? parts[2] : "30d";
      if (!view.hasChildNodes()) view.replaceChildren(el("div", { class: "empty" }, "Wczytywanie…"));
      await renderGame(Number(parts[1]), rangeKey, token);
      window.scrollTo(0, parts[2] ? window.scrollY : 0);
    } else {
      if (!view.hasChildNodes()) view.replaceChildren(el("div", { class: "empty" }, "Wczytywanie…"));
      await renderOverview(token);
      refreshTimer = setInterval(() => renderOverview(renderToken).catch(() => {}), 60000);
    }
  } catch (error) {
    if (token !== renderToken) return;
    view.replaceChildren(el("div", { class: "empty" }, "Nie udało się wczytać danych. Sprawdź, czy serwer GamePulse działa."));
    console.error(error);
  }
}

window.addEventListener("hashchange", route);
window.addEventListener("resize", () => chart && chart.resize());
route();
