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

const RANGES = [["24h", "24 h"], ["7d", "7 dni"], ["30d", "30 dni"], ["all", "Od początku pomiarów"]];
const COLORS = { accent: "#5aa9ff", up: "#4ec98a", down: "#f0685f", muted: "#8b95a3", line: "#2a313b", text: "#e6e9ee", event: "#f0a23b" };

let charts = [];
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
    el("span", { class: status.gaps_24h ? "" : "muted", title: "Przerwy dłuższe niż 45 minut między pomiarami" },
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

const CATEGORY = {
  content_release: "Nowa zawartość",
  patch: "Aktualizacja",
  announcement: "Zapowiedź i nadchodzące premiery",
  sale: "Promocja",
  free_weekend: "Darmowy dostęp",
  in_game_event: "Wydarzenie w grze",
  store_item: "Sklep w grze",
  community: "Społeczność",
  other: "Inne",
};

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

function badge(item) {
  return el("span", {
    class: `badge${item.priority >= 2 ? " notable" : ""}${item.priority >= 3 ? " strong" : ""}`,
    title: !item.official ? "" : item.source === "model" ? "Etykieta nadana przez model" : "Etykieta z prostej reguły po tytule; model jeszcze nie czytał tego newsa",
  }, item.official ? (CATEGORY[item.category] || "Inne") + (item.source === "model" ? "" : " ?") : "Zewnętrzny");
}

/** Main type plus the smaller secondary tags. */
function badges(item) {
  return el("span", { class: "badges" }, badge(item),
    (item.secondary || []).map((type) => el("span", { class: "badge tag", title: "Tag dodatkowy: news dotyczy też tego" }, CATEGORY[type] || type)));
}

function openDrawer(...nodes) {
  drawer.hidden = false;
  drawerBody.replaceChildren(...nodes.filter((node) => node != null));
}

async function openNews(appid, gid, back) {
  openDrawer(el("p", { class: "muted" }, "Wczytywanie…"));
  try {
    const item = await api(`/api/games/${appid}/news/${encodeURIComponent(gid)}`);
    const link = safeUrl(item.url);
    openDrawer(
      back ? el("button", { class: "link", onclick: back }, "← Wróć do listy wydarzeń") : null,
      el("h3", {}, item.title || "(bez tytułu)"),
      el("div", { class: "meta" },
        `${dateTimeFmt.format(item.date_ms)} · ${item.feedlabel || ""}`,
        link ? [" · ", el("a", { href: link, target: "_blank", rel: "noopener noreferrer" }, "źródło")] : null),
      el("div", { class: "labelbox" },
        el("div", {}, badges(item),
          item.effective_date ? el("span", { class: "muted" }, ` Data wydarzenia: ${dateFmt.format(new Date(item.effective_date + "T12:00:00Z"))}`) : null),
        item.summary ? el("div", {}, item.summary) : null,
        el("div", { class: "muted fine" }, !item.official ? "News spoza studia; nie jest klasyfikowany."
          : item.source === "model" ? "Typ, datę i streszczenie nadał lokalny model. Mogą być błędne."
          : "Typ z prostej reguły po tytule. Model jeszcze nie czytał tego newsa.")),
      el("div", { class: "body" }, plainText(item.contents) || "Brak treści."),
    );
  } catch (error) {
    openDrawer(el("p", { class: "muted" }, "Nie udało się wczytać newsa."));
  }
}

function openDay(appid, marker, period) {
  const reopen = () => openDay(appid, marker, period);
  openDrawer(
    el("h3", {}, `Wydarzenia: ${period || dateFmt.format(marker.at_ms)}`),
    el("div", { class: "meta" }, marker.count === 1 ? "1 oficjalny news" : `${marker.count} oficjalnych newsów`),
    el("ul", { class: "events" }, marker.items.map((item) =>
      el("li", {}, el("button", { onclick: () => openNews(appid, item.gid, reopen) },
        el("span", { class: "title" }, item.title || "(bez tytułu)"),
        el("span", { class: "sub" }, badges(item), period ? dateFmt.format(item.date_ms) : timeFmt.format(item.date_ms)))))),
    marker.count > marker.items.length
      ? el("p", { class: "muted" }, `Pokazano ${marker.items.length} najważniejszych z ${marker.count}.`) : null,
  );
}

function baseAxis(extra = {}) {
  return {
    type: "time",
    axisLine: { lineStyle: { color: COLORS.line } },
    axisLabel: { color: COLORS.muted, hideOverlap: true },
    splitLine: { show: false },
    ...extra,
  };
}

function valueAxis(extra = {}) {
  return {
    type: "value",
    axisLabel: { color: COLORS.muted, formatter: (v) => nf.format(Math.abs(v)) },
    splitLine: { lineStyle: { color: COLORS.line, type: "dashed" } },
    ...extra,
  };
}

const TOOLTIP = { backgroundColor: "#1e242c", borderColor: COLORS.line, textStyle: { color: COLORS.text, fontSize: 13 } };

function tipBox(header, ...lines) {
  const box = document.createElement("div");
  box.style.maxWidth = "320px";
  box.style.whiteSpace = "normal";
  const head = document.createElement("div");
  head.style.color = COLORS.muted;
  head.textContent = header;
  box.append(head);
  for (const line of lines) {
    const row = document.createElement("div");
    row.textContent = line;
    box.append(row);
  }
  return box;
}

/** Break the line wherever two neighbouring points are too far apart. */
function withGaps(points, bucketMs) {
  const limit = bucketMs ? bucketMs * 2.5 : 45 * 60000;
  const out = [];
  points.forEach((point, index) => {
    if (index && point[0] - points[index - 1][0] > limit) out.push([points[index - 1][0] + 1, null]);
    out.push(point);
  });
  return out;
}

function drawPlayers(container, data, appid, showMarkers, fromZero) {
  const instance = echarts.init(container);
  const { from, to } = data.range;
  const span = to - from;
  const label = (value) => (span <= 2 * 86400000 ? timeFmt.format(value) : dayMonthFmt.format(value));
  const line = withGaps(data.ccu, data.ccu_bucket_ms);
  const values = data.ccu.map((p) => p[1]);
  const reach = data.ccu_bucket_ms ? data.ccu_bucket_ms * 3 : 45 * 60000;
  // A marker sits on the line when there is a measurement close to it,
  // otherwise at the bottom of the chart.
  const markers = (showMarkers ? data.markers : []).map((marker) => {
    let best = null;
    for (const [t, v] of data.ccu) {
      if (best === null || Math.abs(t - marker.at_ms) < Math.abs(best[0] - marker.at_ms)) best = [t, v];
    }
    const onLine = best && Math.abs(best[0] - marker.at_ms) <= reach;
    return { value: [marker.at_ms, onLine ? best[1] : null], marker, onLine };
  });
  const important = (m) => m.marker.priority >= 2;
  const markerSeries = (name, items, yAxisIndex) => ({
    name,
    type: "scatter",
    yAxisIndex,
    data: items.map((m) => ({
      value: yAxisIndex === 0 ? m.value : [m.value[0], 0.04],
      marker: m.marker,
      symbolSize: important(m) ? 13 : 9,
      itemStyle: { color: important(m) ? COLORS.event : COLORS.muted, borderColor: "#0f1216", borderWidth: 2 },
    })),
    z: 5,
    cursor: "pointer",
    tooltip: {
      trigger: "item",
      formatter: (p) => tipBox(
        dateFmt.format(p.data.marker.at_ms),
        ...p.data.marker.items.slice(0, 3).map((i) => `• ${i.title || "(bez tytułu)"}`),
        p.data.marker.count > 3 ? `i ${p.data.marker.count - 3} więcej` : "Kliknij, żeby przeczytać"),
    },
  });

  instance.setOption({
    backgroundColor: "transparent",
    textStyle: { color: COLORS.text, fontFamily: "system-ui, sans-serif" },
    animation: false,
    grid: { left: 70, right: 24, top: 16, bottom: 34 },
    xAxis: baseAxis({ min: from, max: to, axisLabel: { color: COLORS.muted, hideOverlap: true, formatter: label } }),
    yAxis: [valueAxis(fromZero ? { min: 0 } : { scale: true }), { type: "value", min: 0, max: 1, show: false }],
    dataZoom: [{ type: "inside", filterMode: "none" }],
    tooltip: {
      ...TOOLTIP,
      trigger: "axis",
      axisPointer: { lineStyle: { color: COLORS.muted } },
      formatter(params) {
        const point = (Array.isArray(params) ? params : [params]).find((p) => p.seriesName === "Gracze" && p.value[1] !== null);
        return point ? tipBox(dateTimeFmt.format(point.value[0]), `Gracze: ${nf.format(point.value[1])}`) : "";
      },
    },
    graphic: values.length < 2 ? [{
      type: "text", left: "center", top: "middle",
      style: { text: values.length ? "Za mało pomiarów w tym okresie, żeby narysować wykres" : "Brak pomiarów w tym okresie", fill: COLORS.muted, fontSize: 14 },
    }] : [],
    series: [
      {
        name: "Gracze",
        type: "line",
        data: line,
        showSymbol: values.length < 3,
        symbolSize: 5,
        lineStyle: { color: COLORS.accent, width: 2 },
        itemStyle: { color: COLORS.accent },
        areaStyle: { color: "rgba(90,169,255,0.10)" },
        connectNulls: false,
      },
      markerSeries("Wydarzenia", markers.filter((m) => m.onLine), 0),
      markerSeries("Wydarzenia poza pomiarami", markers.filter((m) => !m.onLine), 1),
    ],
  });
  instance.on("click", (params) => { if (params.data && params.data.marker) openDay(appid, params.data.marker); });
  return instance;
}

const MIN_REVIEWS = 10;

function drawReviews(container, points, granularity, mode, markers, appid, anomalies = []) {
  const instance = echarts.init(container);
  const label = granularity === "day" ? dayMonthFmt : monthYearFmt;
  const byTime = new Map(points.map(([t, u, d]) => [t, [u, d]]));
  // Vertical lines at events; a dot on top makes them clickable.
  const lines = markers.map((m) => ({ xAxis: granularity === "day" ? m.day_ms : m.day_ms }));
  const dots = markers.map((m) => ({ value: [m.day_ms, 1], marker: m }));
  const series = mode === "pct"
    ? [{
        name: "Pozytywne %",
        type: "line",
        // Too few reviews make the percentage meaningless, so those periods are left out.
        data: points.map(([t, u, d]) => [t, u + d >= MIN_REVIEWS ? Math.round((1000 * u) / (u + d)) / 10 : null]),
        connectNulls: false,
        showSymbol: granularity === "day",
        symbolSize: 5,
        lineStyle: { color: COLORS.up, width: 2 },
        itemStyle: { color: COLORS.up },
      }]
    : [
        { name: "Pozytywne", type: "bar", stack: "r", data: points.map(([t, u]) => [t, u]), barMaxWidth: 18, itemStyle: { color: COLORS.up } },
        { name: "Negatywne", type: "bar", stack: "r", data: points.map(([t, , d]) => [t, -d]), barMaxWidth: 18, itemStyle: { color: COLORS.down } },
      ];
  series[0].markLine = {
    silent: true,
    symbol: "none",
    label: { show: false },
    lineStyle: { color: COLORS.event, type: "dashed", width: 1, opacity: 0.55 },
    data: lines,
  };
  // Episodes as one shaded band from their first period to their last.
  series[0].markArea = {
    silent: true,
    data: anomalies.map((e) => {
      const half = (e.parts.length ? e.parts[0].end_ms - e.parts[0].start_ms : 0) / 2;
      return [{ xAxis: e.start_ms - half, itemStyle: { color: EPISODE_COLOR[e.direction], opacity: 0.16 } }, { xAxis: e.end_ms - half }];
    }),
  };
  series.push({
    name: "Wydarzenia",
    type: "scatter",
    yAxisIndex: 1,
    data: dots,
    symbolSize: 10,
    itemStyle: { color: COLORS.event, borderColor: "#0f1216", borderWidth: 2 },
    cursor: "pointer",
    z: 5,
    tooltip: {
      trigger: "item",
      formatter: (p) => tipBox(label.format(p.data.marker.day_ms),
        ...p.data.marker.items.slice(0, 3).map((i) => `• ${i.title || "(bez tytułu)"}`),
        p.data.marker.count > 3 ? `i ${p.data.marker.count - 3} więcej` : "Kliknij, żeby przeczytać"),
    },
  });

  instance.setOption({
    backgroundColor: "transparent",
    textStyle: { color: COLORS.text, fontFamily: "system-ui, sans-serif" },
    animation: false,
    grid: { left: 70, right: 24, top: 22, bottom: 34 },
    xAxis: baseAxis({ axisLabel: { color: COLORS.muted, hideOverlap: true, formatter: (v) => label.format(v) } }),
    yAxis: [
      mode === "pct"
        ? valueAxis({ min: 0, max: 100, axisLabel: { color: COLORS.muted, formatter: "{value}%" } })
        : valueAxis(),
      { type: "value", min: 0, max: 1, show: false },
    ],
    dataZoom: [{ type: "inside", filterMode: "none" }],
    tooltip: {
      ...TOOLTIP,
      trigger: "axis",
      axisPointer: { type: mode === "pct" ? "line" : "shadow" },
      formatter(params) {
        const item = (Array.isArray(params) ? params : [params]).find((p) => p.seriesName !== "Wydarzenia");
        if (!item) return "";
        const [up, down] = byTime.get(item.value[0]) || [0, 0];
        const total = up + down;
        return tipBox(label.format(item.value[0]),
          `Pozytywne: ${nf.format(up)}`, `Negatywne: ${nf.format(down)}`,
          total >= MIN_REVIEWS ? `Odsetek pozytywnych: ${Math.round((100 * up) / total)}%`
            : total ? `Za mało recenzji na wiarygodny odsetek (${total})` : "Brak recenzji");
      },
    },
    graphic: points.length ? [] : [{ type: "text", left: "center", top: "middle", style: { text: "Brak danych o recenzjach", fill: COLORS.muted, fontSize: 14 } }],
    series,
  });
  instance.on("click", (params) => {
    if (params.data && params.data.marker) {
      openDay(appid, params.data.marker, granularity === "day" ? null : monthYearFmt.format(params.data.marker.day_ms));
    }
  });
  return instance;
}

function newsRow(appid, item) {
  return el("li", {}, el("button", { onclick: () => openNews(appid, item.gid) },
    el("span", { class: "date" }, dateFmt.format(item.date_ms)),
    el("span", { class: "title" }, item.title || "(bez tytułu)",
      item.summary ? el("span", { class: "summary" }, item.summary) : null),
    badges(item)));
}

/** The full archive: search, kind filter and paging, loaded only on demand. */
function newsArchive(appid, totals) {
  const state = { kind: "official", q: "", items: [], total: 0, loading: false };
  const list = el("ul", { class: "news-list" });
  const count = el("span", { class: "muted" });
  const more = el("button", { class: "chip", onclick: () => load(false) }, "Pokaż więcej");
  const chips = el("div", { class: "chips" });
  const search = el("input", { class: "search", type: "search", placeholder: "Szukaj w tytułach", "aria-label": "Szukaj w tytułach newsów" });
  let timer = null;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.q = search.value; load(true); }, 250);
  });

  function paint() {
    chips.replaceChildren(...[["official", `Oficjalne (${nf.format(totals.official)})`], ["external", `Zewnętrzne (${nf.format(totals.external)})`], ["all", "Wszystkie"]].map(([key, label]) =>
      el("button", { class: `chip ${state.kind === key ? "active" : ""}`, onclick: () => { state.kind = key; load(true); } }, label)));
    count.textContent = `${nf.format(state.items.length)} z ${nf.format(state.total)}`;
    list.replaceChildren(...(state.items.length ? state.items.map((n) => newsRow(appid, n)) : [el("li", { class: "empty" }, state.loading ? "Wczytywanie…" : "Nic nie znaleziono.")]));
    more.hidden = state.items.length >= state.total;
  }

  async function load(reset) {
    if (reset) { state.items = []; state.total = 0; }
    state.loading = true;
    paint();
    const params = new URLSearchParams({ kind: state.kind, q: state.q, offset: state.items.length, limit: 50 });
    try {
      const page = await api(`/api/games/${appid}/news?${params}`);
      state.items = state.items.concat(page.items);
      state.total = page.total;
    } catch (error) {
      console.error(error);
    }
    state.loading = false;
    paint();
  }

  load(true);
  return el("div", { class: "archive" },
    el("div", { class: "panel-head" }, search, chips, count),
    list,
    el("div", { class: "more" }, more));
}

const GRAIN_UNIT = { day: ["dzień", "dni"], week: ["tydzień", "tyg."], month: ["miesiąc", "mies."] };
const EPISODE_COLOR = { negative: COLORS.down, positive: COLORS.up, volume: COLORS.event };
const EPISODE_TITLE = {
  negative: "Wyjątkowo negatywny odbiór",
  positive: "Wyjątkowo pozytywny odbiór",
  volume: "Nietypowo dużo recenzji",
};
const pct1 = (share) => `${(Math.round(share * 1000) / 10).toLocaleString("pl-PL")}%`;

function episodeSpan(e) {
  const last = e.parts.length ? e.parts[e.parts.length - 1].start_ms : e.start_ms;
  if (e.grain === "month") {
    return e.periods === 1 ? monthYearFmt.format(e.start_ms) : `${monthYearFmt.format(e.start_ms)} – ${monthYearFmt.format(last)}`;
  }
  const lastDay = e.end_ms - 86400000;
  return e.start_ms === lastDay ? dateFmt.format(e.start_ms) : `${dayMonthFmt.format(e.start_ms)} – ${dateFmt.format(lastDay)}`;
}

function episodeLength(e) {
  const [one, many] = GRAIN_UNIT[e.grain];
  return e.periods === 1 ? `1 ${one}` : `${e.periods} ${many}`;
}

const VERDICT = {
  likely: ["Prawdopodobna przyczyna", ""],
  possible: ["Możliwa przyczyna", ""],
  unknown: ["Przyczyna nieznana", "muted"],
};
const EXPLAINS_LABEL = {
  start: "może tłumaczyć początek epizodu",
  continuation: "może tłumaczyć tylko ciąg dalszy, nie początek",
  reviews: "oparte na tym, co pisali gracze",
};
const CONFIDENCE_LABEL = { high: "pewność wysoka", medium: "pewność średnia", low: "pewność niska" };

function verdictLine(explanation) {
  if (!explanation) return el("span", { class: "muted small" }, "Agent jeszcze nie analizował tego epizodu.");
  const [label, tone] = VERDICT[explanation.verdict] || VERDICT.unknown;
  return el("span", { class: "verdict" }, el("b", { class: tone }, label),
    explanation.summary ? el("span", { class: "muted" }, ` ${explanation.summary}`) : null);
}

function explanationBlock(appid, e, explanation, reopen) {
  if (!explanation) {
    return [el("h4", {}, "Wyjaśnienie agenta"),
      el("p", { class: "muted" }, "Agent jeszcze nie analizował tego epizodu. Uruchom: gamepulse explain")];
  }
  const [label, tone] = VERDICT[explanation.verdict] || VERDICT.unknown;
  // Explanations made before press and reviews were added carry no breakdown.
  const shown = explanation.shown || { news: explanation.evidence_count, press: 0, review: 0 };
  return [
    el("h4", {}, "Wyjaśnienie agenta"),
    el("div", { class: "labelbox" },
      el("div", {}, el("b", { class: tone }, label)),
      explanation.summary ? el("div", {}, explanation.summary) : null,
      explanation.hypotheses.length ? el("ol", { class: "hypotheses" }, explanation.hypotheses.map((h) =>
        el("li", {},
          el("div", {}, h.claim),
          el("div", { class: "muted fine" },
            `${CONFIDENCE_LABEL[h.confidence] || ""} · ${EXPLAINS_LABEL[h.explains] || ""}`),
          el("div", { class: "cites" }, h.evidence.map((c) => c.kind === "review"
            ? el("blockquote", { class: "quote" },
                el("span", { class: "muted fine" }, `${c.id} · recenzja ${c.voted_up ? "pozytywna" : "negatywna"} · ${nf.format(c.playtime_hours || 0)} godz. gry · ${c.language || ""}`),
                el("span", {}, c.text || ""))
            : c.kind === "discount"
            ? el("span", { class: "fine" }, `${c.id}: przecena ${c.percent}% w sklepie Steam, ${c.published} – ${c.until}`)
            : el("button", { class: "link", onclick: () => openNews(appid, c.gid, reopen) },
                `${c.id}${c.kind === "press" ? " (prasa)" : ""}: ${c.title || "(bez tytułu)"}`)))))) : null,
      explanation.missing ? el("div", { class: "muted" }, `Czego brakuje do pewności: ${explanation.missing}`) : null,
      el("div", { class: "muted fine" }, explanation.source === "code"
        ? "Odpowiedź z kodu: bez newsów w oknie model nie był pytany."
        : `Lokalny model (${explanation.model}) dostał liczby epizodu, ${shown.news} oficjalnych newsów i ${shown.press} artykułów prasowych. ${shown.review
            ? `Przeczytał też próbkę ${shown.review} z ${nf.format(explanation.reviews_collected)} zebranych recenzji z tego czasu.`
            : "Nie miał treści recenzji z tego czasu, więc nie wie, co pisali gracze; to hipotezy oparte na zbieżności w czasie."} Kod odrzucił twierdzenia bez dowodu lub z liczbami spoza danych${explanation.dropped ? ` (${explanation.dropped})` : ""}.`)),
  ];
}

function episodeCard(appid, e) {
  return el("button", { class: `episode ${e.direction}`, onclick: () => openEpisode(appid, e) },
    el("span", { class: "episode-head" },
      el("strong", {}, EPISODE_TITLE[e.direction]),
      e.is_open ? el("span", { class: "tag", title: "Kończy się na ostatnim zakończonym okresie w danych, więc może jeszcze trwać" }, "może trwać") : null),
    el("span", { class: "muted small" }, `${episodeSpan(e)} · ${episodeLength(e)}`),
    el("span", { class: "episode-figures" },
      el("span", {}, el("b", {}, pct1(e.share)), el("i", {}, `pozytywnych, zwykle ${Math.round(100 * e.baseline_share)}%`)),
      el("span", {}, el("b", {}, nf.format(e.reviews)),
        el("i", {}, e.volume_spike ? `recenzji, w szczycie ${Math.round(e.peak_volume_ratio)}× więcej niż zwykle` : "recenzji"))),
    verdictLine(e.explanation));
}

async function openEpisode(appid, e) {
  const reopen = () => openEpisode(appid, e);
  const head = [
    el("h3", {}, EPISODE_TITLE[e.direction]),
    el("div", { class: "meta" }, `${episodeSpan(e)} · ${episodeLength(e)} · ${nf.format(e.reviews)} recenzji, ${pct1(e.share)} pozytywnych (zwykle ${Math.round(100 * e.baseline_share)}%)`),
    el("table", { class: "parts" },
      el("thead", {}, el("tr", {}, ["Okres", "Pozytywne", "Zwykle", "Recenzje"].map((h) => el("th", {}, h)))),
      el("tbody", {}, e.parts.map((p) => el("tr", {},
        el("td", {}, e.grain === "month" ? monthYearFmt.format(p.start_ms) : dateFmt.format(p.start_ms)),
        el("td", {}, pct1(p.share)),
        el("td", {}, `${Math.round(100 * p.baseline_share)}%`),
        el("td", {}, nf.format(p.reviews), p.volume_spike ? el("span", { class: "muted" }, ` (${nf.format(p.volume_ratio)}×)`) : null))))),
  ];
  openDrawer(...head, el("p", { class: "muted" }, "Wczytywanie newsów…"));
  try {
    const [detail, shift] = await Promise.all([
      api(`/api/games/${appid}/episodes/${encodeURIComponent(e.id)}`),
      episodeShift(appid, e).catch(() => null),
    ]);
    openDrawer(...head,
      ...explanationBlock(appid, e, detail.explanation, reopen),
      shift ? el("h4", {}, "Które grupy graczy zmieniły zdanie") : null,
      shift,
      el("h4", {}, "Oficjalne newsy w pobliżu"),
      el("div", { class: "meta" }, `Od ${dateFmt.format(detail.news_from_ms)} do końca epizodu: ${detail.news_total}`),
      detail.news.length
        ? el("ul", { class: "events" }, detail.news.map((item) =>
            el("li", {}, el("button", { onclick: () => openNews(appid, item.gid, reopen) },
              el("span", { class: "title" }, item.title || "(bez tytułu)"),
              el("span", { class: "sub" }, badges(item), `opublikowano ${dateFmt.format(item.date_ms)}`,
                item.date_ms < e.start_ms ? " (przed epizodem)" : " (w trakcie)",
                item.effective_date ? ` · dotyczy ${dateFmt.format(item.event_ms)}` : "")))))
        : el("p", { class: "muted" }, "Brak oficjalnych newsów w tym oknie."),
      detail.news_total > detail.news.length
        ? el("p", { class: "muted" }, `Pokazano ${detail.news.length} najważniejszych z ${detail.news_total}.`) : null,
      el("p", { class: "muted fine" }, "To zestawienie w czasie. News obok epizodu nie dowodzi, że go spowodował."));
  } catch (error) {
    openDrawer(...head, el("p", { class: "muted" }, "Nie udało się wczytać newsów."));
  }
}

// Unusual review episodes found by code. Explaining them is the agent's job.
function episodePanel(appid, episodes) {
  const SHOWN = 4;
  const grid = el("div", { class: "episodes" });
  let all = false;
  const more = el("button", { class: "chip", onclick: () => { all = !all; paint(); } });
  function paint() {
    grid.replaceChildren(...(all ? episodes : episodes.slice(0, SHOWN)).map((e) => episodeCard(appid, e)));
    more.textContent = all ? "Pokaż najnowsze" : `Pokaż wszystkie (${episodes.length})`;
  }
  paint();
  return el("div", { class: "panel" },
    el("div", { class: "panel-head" },
      el("h2", {}, "Nietypowe epizody w recenzjach"),
      el("span", { class: "muted" }, episodes.length ? `wykryto ${episodes.length}, od najnowszych` : ""),
      episodes.length > SHOWN ? more : null),
    episodes.length ? grid : el("p", { class: "muted" }, "Nie wykryto nietypowych epizodów albo analiza jeszcze nie była uruchomiona."),
    el("div", { class: "chart-note" },
      "Epizod to jeden lub kilka kolejnych okresów, w których odsetek pozytywnych recenzji wyraźnie odbiega od zwykłego dla tej gry albo recenzji jest co najmniej trzy razy więcej niż zwykle. Epizody wykrywa kod, bez udziału modelu. Przyczynę proponuje lokalny model na podstawie oficjalnych newsów; „przyczyna nieznana” to pełnoprawna odpowiedź. Kliknij epizod, żeby zobaczyć przebieg, hipotezy z dowodami i newsy z tego czasu."));
}

// ---------------------------------------------------------------- who reviews

const SEGMENT_MIN = 30; // below this a percentage is noise
const PLAYTIME_LABEL = {
  under_2h: "poniżej 2 godz.", "2_10h": "2–10 godz.", "10_50h": "10–50 godz.", "50_200h": "50–200 godz.",
  "200_1000h": "200–1000 godz.", over_1000h: "ponad 1000 godz.", unknown: "nieznany",
};
const LANGUAGE_LABEL = {
  english: "angielski", schinese: "chiński uproszczony", tchinese: "chiński tradycyjny", russian: "rosyjski",
  polish: "polski", german: "niemiecki", french: "francuski", spanish: "hiszpański", latam: "hiszpański (Am. Łac.)",
  brazilian: "portugalski (Brazylia)", portuguese: "portugalski", koreana: "koreański", japanese: "japoński",
  turkish: "turecki", italian: "włoski", thai: "tajski", ukrainian: "ukraiński", czech: "czeski",
  hungarian: "węgierski", dutch: "niderlandzki", swedish: "szwedzki", vietnamese: "wietnamski",
  indonesian: "indonezyjski", other: "pozostałe", unknown: "nieznany",
};
const PURCHASE_LABEL = { steam: "kupiona na Steamie", key: "klucz lub zakup poza Steamem", free: "otrzymana za darmo" };

function segmentRow(label, group) {
  const enough = group.n >= SEGMENT_MIN;
  const share = group.n ? group.positive / group.n : 0;
  return el("div", { class: "segment" },
    el("span", { class: "segment-label" }, label),
    el("span", { class: `segment-bar ${enough ? "" : "thin"}`, title: `${nf.format(group.positive)} pozytywnych, ${nf.format(group.n - group.positive)} negatywnych` },
      enough ? el("i", { style: `width:${(100 * share).toFixed(1)}%` }) : null),
    el("span", { class: "segment-value" }, enough ? `${Math.round(100 * share)}%` : "za mało"),
    el("span", { class: "segment-n muted" }, nf.format(group.n)));
}

function segmentBlock(title, groups, labels, note) {
  return el("div", { class: "segment-block" },
    el("h3", {}, title),
    groups.length ? groups.map((g) => segmentRow(labels[g.key] || g.key, g)) : el("p", { class: "muted small" }, "Brak danych."),
    note ? el("p", { class: "muted fine" }, note) : null);
}

// Who wrote the reviews and how each group voted. Counted by code from collected reviews.
function segmentsPanel(appid) {
  const body = el("div", {}, el("p", { class: "muted" }, "Wczytywanie…"));
  const chips = el("div", { class: "chips" });
  let days = 30;
  async function load() {
    chips.replaceChildren(...[[7, "7 dni"], [30, "30 dni"], [null, "Wszystko zebrane"]].map(([value, label]) =>
      el("button", { class: `chip ${value === days ? "active" : ""}`, onclick: () => { days = value; load(); } }, label)));
    try {
      const query = days ? `?from_ms=${Date.now() - days * 86400000}` : "";
      const data = await api(`/api/games/${appid}/review-segments${query}`);
      if (!data.collected) {
        body.replaceChildren(el("p", { class: "muted" }, "Treść recenzji tej gry nie została jeszcze pobrana."));
        return;
      }
      body.replaceChildren(
        el("div", { class: "segments" },
          segmentBlock("Czas gry w chwili recenzji", data.playtime, PLAYTIME_LABEL),
          segmentBlock("Język recenzji", data.language, LANGUAGE_LABEL),
          data.is_free
            ? segmentBlock("Sposób zdobycia gry", [], PURCHASE_LABEL, "Gra jest darmowa, więc ten podział nic nie mówi.")
            : segmentBlock("Sposób zdobycia gry", data.purchase, PURCHASE_LABEL)),
        el("div", { class: "chart-note" },
          `W tym okresie: ${nf.format(data.total)} recenzji, ${data.total ? Math.round((100 * data.positive) / data.total) : 0}% pozytywnych. `,
          `Zebrane recenzje sięgają od ${dateFmt.format(data.collected.first_ms)} do ${dateFmt.format(data.collected.last_ms)} (${nf.format(data.collected.count)}). `,
          `Pasek pokazuje odsetek pozytywnych, liczba obok to liczba recenzji w grupie; poniżej ${SEGMENT_MIN} recenzji odsetek nie jest pokazywany. `,
          "Język recenzji to nie kraj gracza. Gracze z długim stażem to ci, którzy nie odeszli, więc ich oceny są z natury wyższe."));
    } catch (error) {
      body.replaceChildren(el("p", { class: "muted" }, "Nie udało się wczytać podziału recenzji."));
    }
  }
  load();
  return el("div", { class: "panel" },
    el("div", { class: "panel-head" }, el("h2", {}, "Kto wystawia oceny"), chips),
    body);
}

// Which groups voted differently during an episode than just before it.
async function episodeShift(appid, e) {
  const span = Math.max(e.end_ms - e.start_ms, 14 * 86400000);
  const [during, before] = await Promise.all([
    api(`/api/games/${appid}/review-segments?from_ms=${e.start_ms}&to_ms=${e.end_ms}`),
    api(`/api/games/${appid}/review-segments?from_ms=${e.start_ms - span}&to_ms=${e.start_ms}`),
  ]);
  if (during.total < SEGMENT_MIN) return null;
  if (before.total < SEGMENT_MIN) {
    return el("p", { class: "muted fine" }, "Za mało zebranych recenzji sprzed epizodu, żeby porównać grupy graczy.");
  }
  const rows = [];
  for (const [kind, labels] of [["playtime", PLAYTIME_LABEL], ["language", LANGUAGE_LABEL]]) {
    const earlier = new Map(before[kind].map((g) => [g.key, g]));
    for (const g of during[kind]) {
      const b = earlier.get(g.key);
      if (!b || g.n < SEGMENT_MIN || b.n < SEGMENT_MIN || g.key === "unknown" || g.key === "other") continue;
      const now = g.positive / g.n;
      const then = b.positive / b.n;
      rows.push({ label: `${kind === "playtime" ? "Czas gry" : "Język"}: ${labels[g.key] || g.key}`, now, then, n: g.n, shift: now - then });
    }
  }
  if (!rows.length) return el("p", { class: "muted fine" }, "Żadna grupa graczy nie ma dość recenzji w obu okresach, żeby ją porównać.");
  rows.sort((a, b) => Math.abs(b.shift) - Math.abs(a.shift));
  const points = (shift) => `${shift > 0 ? "+" : "−"}${Math.abs(Math.round(100 * shift))} pp`;
  return el("div", {},
    el("table", { class: "parts" },
      el("thead", {}, el("tr", {}, ["Grupa", "W epizodzie", "Wcześniej", "Zmiana"].map((h) => el("th", {}, h)))),
      el("tbody", {}, rows.map((r) => el("tr", {},
        el("td", {}, r.label, el("span", { class: "muted" }, ` (${nf.format(r.n)})`)),
        el("td", {}, `${Math.round(100 * r.now)}%`),
        el("td", {}, `${Math.round(100 * r.then)}%`),
        el("td", { class: r.shift >= 0 ? "up" : "down" }, points(r.shift)))))),
    el("p", { class: "muted fine" },
      `Odsetek pozytywnych recenzji w epizodzie i w ${Math.round(span / 86400000)} dniach przed nim, tylko dla grup z co najmniej ${SEGMENT_MIN} recenzjami w obu okresach. Liczy kod, od największej zmiany.`));
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
  const image = safeUrl(meta.image);
  const facts = [
    meta.developers.length ? `Studio: ${meta.developers.join(", ")}` : null,
    meta.publishers.length && meta.publishers.join() !== meta.developers.join() ? `Wydawca: ${meta.publishers.join(", ")}` : null,
    meta.release_date ? `Premiera: ${meta.release_date}` : null,
    meta.genres.length ? meta.genres.join(" · ") : null,
  ].filter(Boolean);

  // --- description, two lines unless expanded
  let desc = null;
  if (meta.description) {
    const text = el("div", { class: "desc clamp" }, meta.description);
    const toggle = el("button", { class: "link", onclick: () => {
      const open = text.classList.toggle("clamp") === false;
      toggle.textContent = open ? "Zwiń opis" : "Pokaż cały opis";
    } }, "Pokaż cały opis");
    desc = el("div", {}, text, toggle);
  }

  // --- players chart
  const playersBox = el("div", { class: "chart players" });
  let showMarkers = true;
  let fromZero = false;
  const redrawPlayers = () => {
    charts[0].dispose();
    charts[0] = drawPlayers(playersBox, data, appid, showMarkers, fromZero);
  };
  const markerToggle = el("button", { class: "chip active", onclick: () => {
    showMarkers = !showMarkers;
    markerToggle.classList.toggle("active", showMarkers);
    redrawPlayers();
  } }, "Znaczniki wydarzeń");
  const scaleToggle = el("button", { class: "chip", title: "Dopasowana skala uwypukla drobne ruchy; skala od zera pokazuje je w proporcji", onclick: () => {
    fromZero = !fromZero;
    scaleToggle.classList.toggle("active", fromZero);
    redrawPlayers();
  } }, "Skala od zera");
  const firstPoint = data.ccu[0];
  const lastPoint = data.ccu[data.ccu.length - 1];
  // Over less than a day the first and last point mostly differ by the time
  // of day, so the change is only shown once a full day is covered.
  const covered = data.ccu.length >= 2 ? lastPoint[0] - firstPoint[0] : 0;
  const rangeChange = covered >= 86400000 && firstPoint[1]
    ? Math.round((1000 * (lastPoint[1] - firstPoint[1])) / firstPoint[1]) / 10 : null;
  const collected = data.ccu_first_ts
    ? `Pomiary co 30 minut od ${dateTimeFmt.format(data.ccu_first_ts)}. Steam nie udostępnia wcześniejszej historii. Przerwa w linii oznacza, że kolektor nie działał.`
    : "Dla tej gry nie ma jeszcze żadnego pomiaru.";

  // --- reviews chart
  const reviewsBox = el("div", { class: "chart reviews" });
  let granularity = "month";
  let reviewMode = "count";
  // When rules mark most months as a "launch", the lines say nothing; start with them off.
  const crowded = data.review_markers.monthly.length > data.reviews.monthly.length / 3;
  let reviewMarkers = !crowded;
  const reviewChips = el("div", { class: "chips" });
  function paintReviews() {
    const chip = (active, label, onclick) => el("button", { class: `chip ${active ? "active" : ""}`, onclick }, label);
    reviewChips.replaceChildren(
      chip(reviewMarkers, "Znaczniki wydarzeń", () => { reviewMarkers = !reviewMarkers; paintReviews(); }),
      el("span", { class: "sep" }),
      chip(reviewMode === "count", "Liczba", () => { reviewMode = "count"; paintReviews(); }),
      chip(reviewMode === "pct", "% pozytywnych", () => { reviewMode = "pct"; paintReviews(); }),
      el("span", { class: "sep" }),
      chip(granularity === "month", "Cała historia", () => { granularity = "month"; paintReviews(); }),
      chip(granularity === "day", "Ostatnie 30 dni", () => { granularity = "day"; paintReviews(); }));
    if (charts[1]) charts[1].dispose();
    const daily = granularity === "day";
    charts[1] = drawReviews(reviewsBox, daily ? data.reviews.daily : data.reviews.monthly, granularity, reviewMode,
      reviewMarkers ? (daily ? data.review_markers.daily : data.review_markers.monthly) : [], appid,
      data.episodes.filter((e) => (e.grain === "day") === daily));
  }

  // --- events
  const archiveSlot = el("div", {});
  const totalNews = data.news_totals.official + data.news_totals.external;
  const archiveButton = el("button", { class: "chip", onclick: () => {
    if (archiveSlot.hasChildNodes()) {
      archiveSlot.replaceChildren();
      archiveButton.textContent = `Wszystkie newsy (${nf.format(totalNews)})`;
    } else {
      archiveSlot.replaceChildren(newsArchive(appid, data.news_totals));
      archiveButton.textContent = "Ukryj archiwum";
    }
  } }, `Wszystkie newsy (${nf.format(totalNews)})`);

  const change = changeNode(tile.change_24h);
  view.replaceChildren(
    el("a", { class: "back", href: "#/" }, "← Wszystkie gry"),
    el("div", { class: "game-head" },
      image ? el("img", { src: image, alt: "" }) : null,
      el("div", {},
        el("h1", {}, meta.name),
        el("div", { class: "facts" }, facts.map((f) => el("span", {}, f)),
          el("a", { href: meta.store_url, target: "_blank", rel: "noopener noreferrer" }, "Strona w Steamie ↗")),
        desc)),
    el("div", { class: "stats" },
      statCard("Graczy teraz (Steam)", tile.players == null ? "—" : nf.format(tile.players), tile.players_ts ? ago(tile.players_ts) : "brak pomiaru"),
      statCard("Zmiana 24 h", change || el("span", { class: "muted small" }, "Za mało danych"),
        change ? "względem tej samej pory wczoraj" : "pojawi się po dobie zbierania"),
      statCard("Szczyt 24 h", data.peak_24h == null ? "—" : nf.format(data.peak_24h), "najwyższy pomiar z ostatniej doby"),
      statCard("Recenzje, 30 dni", pctText(summary.recent.pct), reviewSub(summary.recent))),
    el("div", { class: "panel" },
      el("div", { class: "panel-head" },
        el("h2", {}, "Aktywność graczy"),
        rangeChange === null
          ? (data.ccu.length ? el("span", { class: "muted small", title: "Przy krótszym okresie różnica pokazuje głównie porę dnia, a nie trend" },
              `Pomiary obejmują ${covered < 3600000 ? "mniej niż godzinę" : `${Math.floor(covered / 3600000)} godz.`}; zmiana pojawi się po dobie`) : null)
          : el("span", { class: "muted", title: "Ostatni pomiar względem pierwszego pomiaru widocznego na wykresie" },
              `Od ${dateTimeFmt.format(firstPoint[0])}: `, changeNode(rangeChange) || "bez zmian"),
        el("div", { class: "chips" }, markerToggle, scaleToggle, el("span", { class: "sep" }), RANGES.map(([key, label]) =>
          el("a", { class: `chip ${key === rangeKey ? "active" : ""}`, href: `#/game/${appid}/${key}` }, label)))),
      playersBox,
      el("div", { class: "chart-note" },
        el("span", { class: "legend" },
          el("span", {}, el("i", { style: `background:${COLORS.event}` }), "dzień z ważnym wydarzeniem"),
          el("span", {}, el("i", { style: `background:${COLORS.muted}` }), "dzień z innymi newsami")),
        collected)),
    episodePanel(appid, data.episodes),
    el("div", { class: "panel" },
      el("div", { class: "panel-head" },
        el("h2", {}, "Najważniejsze wydarzenia"),
        el("span", { class: "muted" }, "oficjalne, z ostatnich 90 dni"),
        archiveButton),
      el("ul", { class: "news-list" }, data.highlights.length
        ? data.highlights.map((n) => newsRow(appid, n))
        : [el("li", { class: "empty" }, "Brak oficjalnych newsów z ostatnich 90 dni.")]),
      el("div", { class: "chart-note" },
        `Lokalny model przeczytał ${nf.format(data.news_totals.classified)} z ${nf.format(data.news_totals.official)} oficjalnych newsów tej gry. Pozostałe mają etykietę z prostej reguły po tytule, oznaczoną znakiem zapytania.`),
      archiveSlot),
    el("div", { class: "panel" },
      el("div", { class: "panel-head" },
        el("h2", {}, "Recenzje"),
        el("span", { class: "muted" }, `Cała historia: ${pctText(summary.all.pct)} pozytywnych (${reviewSub(summary.all)})`),
        reviewChips),
      reviewsBox,
      el("div", { class: "chart-note" },
        crowded ? "Znaczniki są domyślnie wyłączone: reguły po tytule oznaczają dla tej gry zbyt wiele miesięcy jako premierę. Zmieni się to, gdy model przeczyta starsze newsy. " : "",
        `Linie przerywane to wydarzenia: w całej historii tylko premiery i nowa zawartość, w ostatnich 30 dniach także aktualizacje i zapowiedzi. W widoku procentowym pominięto okresy z mniej niż ${MIN_REVIEWS} recenzjami.`)),
    segmentsPanel(appid),
  );
  charts = [drawPlayers(playersBox, data, appid, showMarkers, fromZero), null];
  paintReviews();
}

// ---------------------------------------------------------------- labelling page

const TYPE_HINT = {
  content_release: "Nowa zawartość do gry, która już wyszła: dodatek, DLC, sezon, liga, mapa, postać, tryb. Dostępna teraz albo z podanym dniem. Liczy się treść, nie tytuł: „Patch Notes” wnoszące nowy sezon to też nowa zawartość.",
  patch: "Same poprawki i strojenie: balans, błędy, hotfix, przerwa techniczna, zmiany ekonomii, zaplanowane testy systemu. Bez istotnej nowej zawartości.",
  announcement: "Tylko dwie rzeczy: wszystko o premierze samej gry (data, przedsprzedaż, dzień premiery) oraz przyszła grywalna zawartość bez konkretnego dnia (zwiastun, roadmapa, „wkrótce”).",
  sale: "Obniżka ceny gry lub dodatków w sklepie, za prawdziwe pieniądze. Zniżki i bonusy wewnątrz gry to wydarzenie w grze.",
  free_weekend: "Cała gra czasowo za darmo albo przejście na free-to-play.",
  in_game_event: "Wydarzenie czasowe w grze: bonusy, podwójne XP, tygodniowe premie i zniżki w grze, event świąteczny, tryb na ograniczony czas, darmowy przedmiot do odebrania.",
  store_item: "Rzeczy do kupienia: skórki, paczki, kolekcje, przepustki premium, płatne edycje, mikrotransakcje. Jeśli płatna rzecz to głównie nowa grywalna zawartość, wybierz nową zawartość.",
  community: "O społeczności i dla niej: fan arty, konkursy, e-sport, turnieje, streamy i ich podsumowania, Twitch Drops, wywiady, odznaki dla graczy, gadżety, ankiety, regulaminy i kary.",
  other: "Wieści ze studia bez niczego do grania, kupienia czy obejrzenia: kamienie milowe sprzedaży i wishlist, rocznice, podziękowania. Oraz wszystko, co nie pasuje wyżej.",
};

let labelKeys = null;

async function renderLabel(token) {
  const data = await api("/api/label/next");
  if (token !== renderToken) return;
  if (labelKeys) document.removeEventListener("keydown", labelKeys);
  labelKeys = null;
  const undo = el("button", { class: "link", onclick: async () => {
    undo.disabled = true;
    try {
      const response = await fetch("/api/label/undo", { method: "POST" });
      if (!response.ok) throw new Error(String(response.status));
      await renderLabel(renderToken);
      window.scrollTo(0, 0);
    } catch (error) {
      undo.disabled = false;
      console.error(error);
    }
  } }, "← Cofnij poprzednią decyzję");
  const head = el("div", { class: "panel-head" },
    el("h2", {}, "Oznaczanie newsów do pomiaru trafności modelu"),
    data.done ? undo : null,
    el("span", { class: "muted" }, `${data.done} z ${data.total}`));
  if (!data.total) {
    view.replaceChildren(el("div", { class: "panel" }, head,
      el("p", { class: "muted" }, "Nie ma jeszcze próbki. Utwórz ją poleceniem: uv run gamepulse eval-sample")));
    return;
  }
  if (!data.item) {
    view.replaceChildren(el("div", { class: "panel" }, head,
      el("p", {}, "Wszystkie newsy z próbki są oznaczone."),
      el("p", { class: "muted" }, "Wynik porównania z modelem pokaże polecenie: uv run gamepulse eval-classifier")));
    return;
  }
  const item = data.item;
  let busy = false;
  const extra = new Set();
  const tagChips = el("div", { class: "chips" });
  function paintTags() {
    tagChips.replaceChildren(...data.event_types.filter((type) => type !== "other").map((type) =>
      el("button", { class: `chip ${extra.has(type) ? "active" : ""}`, onclick: () => {
        if (extra.has(type)) extra.delete(type); else extra.add(type);
        paintTags();
      } }, CATEGORY[type] || type)));
  }
  paintTags();
  // Picking a type only marks it; nothing is saved until it is confirmed.
  let chosen;  // undefined = nothing picked yet, null = skip
  const choiceButtons = new Map();
  const confirmButton = el("button", { class: "confirm", disabled: "", onclick: () => save(chosen) }, "Zatwierdź i przejdź dalej");
  function choose(eventType) {
    chosen = eventType;
    for (const [type, button] of choiceButtons) button.classList.toggle("active", type === eventType);
    confirmButton.disabled = false;
    confirmButton.textContent = eventType === null ? "Pomiń ten news i przejdź dalej" : `Zatwierdź: ${CATEGORY[eventType] || eventType}`;
  }
  async function save(eventType) {
    if (busy || eventType === undefined) return;
    busy = true;
    try {
      const response = await fetch("/api/label", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // A tag equal to the main type adds nothing, so it is left out.
        body: JSON.stringify({ gid: item.gid, event_type: eventType, secondary_types: eventType ? [...extra].filter((t) => t !== eventType) : [] }),
      });
      if (!response.ok) throw new Error(String(response.status));
      await renderLabel(renderToken);
      window.scrollTo(0, 0);
    } catch (error) {
      busy = false;
      console.error(error);
    }
  }
  labelKeys = (event) => {
    if (event.target instanceof HTMLInputElement || event.ctrlKey || event.metaKey || event.altKey) return;
    const index = "123456789".indexOf(event.key);
    if (index >= 0 && index < data.event_types.length) choose(data.event_types[index]);
    else if (event.key === "0") choose(null);
    else if (event.key === "Enter") { event.preventDefault(); save(chosen); }
  };
  document.addEventListener("keydown", labelKeys);
  const link = safeUrl(item.url);
  view.replaceChildren(
    el("a", { class: "back", href: "#/" }, "← Wszystkie gry"),
    el("div", { class: "panel", style: "margin-top:14px" }, head,
      el("p", { class: "muted" }, "Wybierz typ główny, czyli to, o czym news jest przede wszystkim, i ewentualne tagi dodatkowe. Wybór można zmieniać do woli; zapisuje go dopiero przycisk Zatwierdź. Odpowiedź modelu jest ukryta. Klawisze: 1–9 typ główny, 0 pomiń, Enter zatwierdza."),
      el("div", { class: "label-grid" },
        el("div", { class: "label-news" },
          el("div", { class: "muted" }, `${item.game} · ${dateFmt.format(item.date_ms)}`,
            link ? [" · ", el("a", { class: "link", href: link, target: "_blank", rel: "noopener noreferrer" }, "źródło")] : null),
          el("h3", {}, item.title || "(bez tytułu)"),
          el("div", { class: "body" }, plainText(item.contents) || "Brak treści.")),
        el("div", { class: "label-choices" },
          el("div", { class: "tagbox" },
            el("div", { class: "muted fine" }, "Tagi dodatkowe (opcjonalne): o czym jeszcze jest ten news?"),
            tagChips),
          el("div", { class: "muted fine" }, "Typ główny:"),
          data.event_types.map((type, index) => {
            const button = el("button", { onclick: () => choose(type) },
              el("span", { class: "key" }, String(index + 1)),
              el("span", {}, el("strong", {}, CATEGORY[type] || type), el("span", { class: "hint" }, TYPE_HINT[type] || "")));
            choiceButtons.set(type, button);
            return button;
          }),
          (() => {
            const button = el("button", { class: "skip", onclick: () => choose(null) },
              el("span", { class: "key" }, "0"), el("span", {}, el("strong", {}, "Pomiń"), el("span", { class: "hint" }, "Nie da się ocenić albo news jest nieczytelny.")));
            choiceButtons.set(null, button);
            return button;
          })(),
          confirmButton))),
  );
}

// ---------------------------------------------------------------- router

// ---------------------------------------------------------------- rating explanations

const RATING_BUTTONS = [
  ["correct", "Trafne", "Wyjaśnienie zgadza się z dowodami i z tym, co wiesz o tej sytuacji"],
  ["partly", "Częściowo", "Główna przyczyna jest inna albo jest tylko jedną z kilku"],
  ["wrong", "Błędne", "Dowody tego nie potwierdzają albo przyczyna była inna"],
  ["cannot_tell", "Nie umiem ocenić", "Nie da się tego rozstrzygnąć z dowodów"],
];

async function renderRate(token) {
  const data = await api("/api/rate/next");
  if (token !== renderToken) return;
  if (labelKeys) document.removeEventListener("keydown", labelKeys);
  labelKeys = null;
  const undo = el("button", { class: "link", onclick: async () => {
    undo.disabled = true;
    try {
      const response = await fetch("/api/rate/undo", { method: "POST" });
      if (!response.ok) throw new Error(String(response.status));
      await renderRate(renderToken);
      window.scrollTo(0, 0);
    } catch (error) {
      undo.disabled = false;
      console.error(error);
    }
  } }, "← Cofnij poprzednią ocenę");
  const head = el("div", { class: "panel-head" },
    el("h2", {}, "Ocena wyjaśnień agenta"),
    data.done ? undo : null,
    el("span", { class: "muted" }, `${data.done} z ${data.total}`));
  if (!data.item) {
    const rows = Object.entries(data.summary.by_verdict);
    view.replaceChildren(el("div", { class: "panel" }, head,
      el("p", {}, data.total ? "Wszystkie wyjaśnienia są ocenione." : "Agent nie przygotował jeszcze żadnych wyjaśnień. Uruchom: uv run gamepulse explain"),
      rows.length ? el("table", { class: "parts" },
        el("thead", {}, el("tr", {}, ["Werdykt agenta", "Trafne", "Częściowo", "Błędne", "Nie umiem ocenić"].map((h) => el("th", {}, h)))),
        el("tbody", {}, rows.map(([verdict, r]) => el("tr", {},
          el("td", {}, (VERDICT[verdict] || VERDICT.unknown)[0]),
          el("td", {}, r.correct), el("td", {}, r.partly), el("td", {}, r.wrong), el("td", {}, r.cannot_tell))))) : null,
      el("p", { class: "muted" }, "Pełne zestawienie: uv run gamepulse eval-explanations")));
    return;
  }
  const { appid, game, episode: e } = data.item;
  const reopen = null;
  const note = el("textarea", { class: "note", rows: "2", placeholder: "Notatka (opcjonalnie): co było prawdziwą przyczyną, czego zabrakło" });
  let busy = false;
  async function save(rating) {
    if (busy) return;
    busy = true;
    try {
      const response = await fetch("/api/rate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ episode_id: e.id, rating, note: note.value }),
      });
      if (!response.ok) throw new Error(String(response.status));
      await renderRate(renderToken);
      window.scrollTo(0, 0);
    } catch (error) {
      busy = false;
      console.error(error);
    }
  }
  const shiftSlot = el("div", {});
  episodeShift(appid, e).then((node) => {
    if (node && token === renderToken) shiftSlot.replaceChildren(el("h4", {}, "Które grupy graczy zmieniły zdanie"), node);
  }).catch(() => {});
  view.replaceChildren(el("div", { class: "panel" }, head,
    el("h3", {}, `${game}: ${EPISODE_TITLE[e.direction]}`),
    el("div", { class: "meta" }, `${episodeSpan(e)} · ${episodeLength(e)} · ${nf.format(e.reviews)} recenzji, ${pct1(e.share)} pozytywnych (zwykle ${Math.round(100 * e.baseline_share)}%)`),
    ...explanationBlock(appid, e, e.explanation, reopen),
    shiftSlot,
    el("h4", {}, "Twoja ocena"),
    el("p", { class: "muted fine" }, "Oceń, czy wyjaśnienie wynika z pokazanych dowodów i zgadza się z tym, co wiesz. Kliknij tytuł newsa, żeby go przeczytać. Klawisze 1–4."),
    note,
    el("div", { class: "chips rate-buttons" }, RATING_BUTTONS.map(([key, label, title], index) =>
      el("button", { class: "chip", title, onclick: () => save(key) }, `${index + 1}. ${label}`)))));
  labelKeys = (event) => {
    if (event.target === note || event.ctrlKey || event.metaKey || event.altKey) return;
    const index = Number(event.key) - 1;
    if (index >= 0 && index < RATING_BUTTONS.length) save(RATING_BUTTONS[index][0]);
  };
  document.addEventListener("keydown", labelKeys);
}

async function route() {
  const token = ++renderToken;
  clearInterval(refreshTimer);
  if (labelKeys) { document.removeEventListener("keydown", labelKeys); labelKeys = null; }
  closeDrawer();
  charts.forEach((c) => c && c.dispose());
  charts = [];
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  try {
    if (parts[0] === "game" && /^\d+$/.test(parts[1] || "")) {
      const rangeKey = RANGES.some(([key]) => key === parts[2]) ? parts[2] : "7d";
      if (!view.hasChildNodes()) view.replaceChildren(el("div", { class: "empty" }, "Wczytywanie…"));
      await renderGame(Number(parts[1]), rangeKey, token);
      window.scrollTo(0, parts[2] ? window.scrollY : 0);
    } else if (parts[0] === "label") {
      await renderLabel(token);
    } else if (parts[0] === "rate") {
      await renderRate(token);
    } else {
      if (!view.hasChildNodes()) view.replaceChildren(el("div", { class: "empty" }, "Wczytywanie…"));
      await renderOverview(token);
      // Only the page still on screen may refresh itself; a render that was
      // overtaken by another navigation must not start repainting later.
      if (token === renderToken) {
        refreshTimer = setInterval(() => renderOverview(renderToken).catch(() => {}), 60000);
      }
    }
  } catch (error) {
    if (token !== renderToken) return;
    view.replaceChildren(el("div", { class: "empty" }, "Nie udało się wczytać danych. Sprawdź, czy serwer GamePulse działa."));
    console.error(error);
  }
}

window.addEventListener("hashchange", route);
window.addEventListener("resize", () => charts.forEach((c) => c && c.resize()));
route();
