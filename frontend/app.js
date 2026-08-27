/* FinOps Copilot — console for infrastructure and AI-service cost governance. */

const state = {
  overview: null,
  infra: null,
  forecast: null,
  ai: null,
  result: null,
  decisions: [],
  filter: "all",
  view: "ask",
};

/* ── helpers ─────────────────────────────────────────────── */

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const money = (value) =>
  `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const moneyExact = (value) =>
  `$${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const compact = (value) =>
  Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(Number(value || 0));
const pct = (value) => `${Number(value || 0).toFixed(1)}%`;

const esc = (value) =>
  String(value ?? "").replace(/[&<>'"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[c]));

// Domain vocabulary that must survive title-casing ("ai finops" -> "AI FinOps").
const ACRONYMS = {
  ai: "AI", db: "DB", vm: "VM", cpu: "CPU", sku: "SKU", aws: "AWS", gcp: "GCP",
  finops: "FinOps", llm: "LLM", poc: "PoC", uat: "UAT", p95: "P95", id: "ID",
};
const titleCase = (value) =>
  String(value ?? "")
    .replace(/[_-]+/g, " ")
    .split(" ")
    .map((word) => ACRONYMS[word.toLowerCase()] ?? word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : detail;
    } catch { /* keep the status line */ }
    throw new Error(detail);
  }
  return response.json();
}

function setStatus(message, kind = "") {
  const node = $("#status");
  node.textContent = message;
  node.className = `status ${kind}`;
}

/* ── theme ───────────────────────────────────────────────── */

function initTheme() {
  const stored = localStorage.getItem("finops-theme");
  if (stored) document.documentElement.dataset.theme = stored;
  $("#theme-toggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("finops-theme", next);
  });
}

/* ── tooltip (hover layer for every chart mark) ──────────── */

function initTooltip() {
  const tip = $("#tooltip");
  document.addEventListener("mouseover", (event) => {
    const target = event.target.closest("[data-tip]");
    if (!target) return;
    tip.innerHTML = target.dataset.tip;
    tip.hidden = false;
  });
  document.addEventListener("mousemove", (event) => {
    if (tip.hidden) return;
    const pad = 14;
    const rect = tip.getBoundingClientRect();
    let x = event.clientX + pad;
    let y = event.clientY + pad;
    if (x + rect.width > window.innerWidth - 8) x = event.clientX - rect.width - pad;
    if (y + rect.height > window.innerHeight - 8) y = event.clientY - rect.height - pad;
    tip.style.left = `${Math.max(8, x)}px`;
    tip.style.top = `${Math.max(8, y)}px`;
  });
  document.addEventListener("mouseout", (event) => {
    if (event.target.closest("[data-tip]")) tip.hidden = true;
  });
}

/* ── chart primitives ────────────────────────────────────── */

/**
 * Horizontal bars comparing magnitude. One hue (sequential) — identity is
 * carried by the row label, never by colour.
 */
function barChart(rows, { format = money } = {}) {
  if (!rows.length) return `<p class="empty">No data.</p>`;
  const max = Math.max(...rows.map((row) => row.value), 1);
  return `<div class="bars">${rows.map((row) => `
    <div class="bar-row" data-tip="<b>${esc(row.label)}</b>${esc(row.tip || format(row.value))}">
      <span class="bar-name">${esc(row.label)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${Math.max(1.5, (row.value / max) * 100)}%"></span></span>
      <span class="bar-value">${esc(format(row.value))}</span>
    </div>`).join("")}</div>`;
}

/** A single ratio against its scale. Same-ramp track, value direct-labelled. */
function meter({ label, value, note }) {
  return `<div data-tip="<b>${esc(label)}</b>${pct(value)} average across the fleet">
    <div class="meter-label"><span>${esc(label)}</span><strong>${pct(value)}</strong></div>
    <div class="meter-track"><div class="meter-fill" style="width:${Math.min(100, Math.max(1.5, value))}%"></div></div>
    ${note ? `<p class="meter-note">${esc(note)}</p>` : ""}
  </div>`;
}

/** Trend over time for one series — 2px line over a faint area, no axes. */
function sparkline(values) {
  if (values.length < 2) return `<svg class="sparkline" role="img" aria-label="No history available"></svg>`;
  const width = 240;
  const height = 54;
  const pad = 3;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (width - pad * 2) / (values.length - 1);
  const points = values.map((value, index) => [
    pad + index * step,
    pad + (height - pad * 2) * (1 - (value - min) / span),
  ]);
  const line = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${points.at(-1)[0].toFixed(1)},${height - pad} L${pad},${height - pad} Z`;
  return `<svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img"
    aria-label="Trend from ${min.toFixed(1)} to ${values.at(-1).toFixed(1)} percent">
    <path class="spark-area" d="${area}" />
    <path class="spark-line" d="${line}" />
  </svg>`;
}

/**
 * Two lines on one axis: what happened, and what the model said would happen.
 * Two series means a legend is mandatory — colour alone must never be the only
 * thing telling them apart.
 */
function dualLine(actual, predicted, threshold) {
  if (actual.length < 2) return `<p class="empty">Not enough history to plot.</p>`;
  const w = 720, h = 200, padL = 34, padR = 10, padT = 12, padB = 16;
  const all = actual.concat(predicted, threshold != null ? [threshold] : []);
  const max = Math.max(...all) * 1.08;
  const min = Math.min(0, ...all);
  const span = max - min || 1;
  const x = (i) => padL + (i / (actual.length - 1)) * (w - padL - padR);
  const y = (v) => padT + (1 - (v - min) / span) * (h - padT - padB);
  const path = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  const ticks = [min, min + span / 2, max].map((v) => `
    <line x1="${padL}" y1="${y(v).toFixed(1)}" x2="${w - padR}" y2="${y(v).toFixed(1)}" class="grid" />
    <text x="${padL - 6}" y="${(y(v) + 3.5).toFixed(1)}" class="tick" text-anchor="end">${v.toFixed(0)}</text>`).join("");

  const alertLine = threshold == null ? "" : `
    <line x1="${padL}" y1="${y(threshold).toFixed(1)}" x2="${w - padR}" y2="${y(threshold).toFixed(1)}" class="threshold" />`;

  return `
    <svg class="linechart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img"
         aria-label="Predicted versus actual CPU across the held-out period">
      ${ticks}${alertLine}
      <path class="line-actual" d="${path(actual)}" />
      <path class="line-predicted" d="${path(predicted)}" />
    </svg>
    <div class="legend">
      <span><i style="background:var(--series-1)"></i>Actual CPU</span>
      <span><i style="background:var(--series-2)"></i>Predicted CPU</span>
      ${threshold == null ? "" : `<span><i class="legend-dash"></i>Alert threshold ${threshold}%</span>`}
    </div>`;
}

/* ── views ───────────────────────────────────────────────── */

function switchView(view) {
  state.view = view;
  $$(".viewtab").forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle("is-active", active);
    if (active) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  $$(".view").forEach((section) => section.classList.toggle("is-active", section.dataset.view === view));

  if (view === "infrastructure" && !state.infra) loadInfrastructure();
  if (view === "forecast" && !state.forecast) loadForecast();
  if (view === "ai" && !state.ai) loadAiServices();
  if (view === "activity") loadActivity();
}

function kpi(label, value, hint, hintClass = "") {
  return `<div class="kpi">
    <span class="kpi-label">${esc(label)}</span>
    <strong class="kpi-value">${esc(value)}</strong>
    <span class="kpi-hint ${hintClass}">${esc(hint)}</span>
  </div>`;
}

/* ── overview ────────────────────────────────────────────── */

async function loadOverview() {
  const overview = await api("/api/overview");
  state.overview = overview;

  const { estate, infrastructure, ai_services: ai } = overview;
  $("#estate-kpis").innerHTML = [
    kpi("Monthly cloud spend", money(estate.monthly_cost_usd), `${estate.resources} resources across ${estate.providers} providers`),
    kpi("Savings identified", money(estate.savings_usd), `${pct(estate.savings_pct)} of current spend`, "good"),
    kpi("Infrastructure", money(infrastructure.monthly_cost_usd), `${infrastructure.idle_resources} of ${infrastructure.resources} machines idle`),
    kpi("AI services", money(ai.monthly_cost_usd), `${compact(ai.requests)} requests over 30 days`),
  ].join("");

  const mode = overview.reasoning_mode;
  $("#reasoning-mode").textContent =
    mode.mode === "llm" ? `Explaining with ${mode.provider}` : "Evidence mode — no LLM key set";
  $("#reasoning-mode").title =
    mode.mode === "llm"
      ? `Final wording generated by ${mode.provider} (${mode.model}). Numbers always come from the evidence tools.`
      : "Answers are built from the evidence policy. Set an LLM key to generate the final wording.";
}

/* ── ask ─────────────────────────────────────────────────── */

function renderSuggestions(items) {
  $("#suggestions").innerHTML = items.slice(0, 8).map((item) => `
    <button class="chip" type="button" data-question="${esc(item.question)}">
      <span class="dot ${esc(item.domain)}"></span>${esc(item.label)}
    </button>`).join("");
}

async function runQuery(question) {
  const input = $("#question");
  const text = (question ?? input.value).trim();
  if (text.length < 3) {
    setStatus("Type a question first — for example, “which machines are idle?”", "error");
    input.focus();
    return;
  }
  input.value = text;
  $("#ask-button").disabled = true;
  setStatus("Reading telemetry, cost and quality evidence…", "loading");

  const body = { question: text, domain: $("#domain").value };
  const found = (result) =>
    `${result.totals.decisions} decision${result.totals.decisions === 1 ? "" : "s"} found in ${result.domain_label.toLowerCase()}.`;

  try {
    // Phase 1 — evidence only. Returns in milliseconds, so the decisions and
    // their numbers are on screen straight away.
    const fast = await api("/api/query", {
      method: "POST",
      body: JSON.stringify({ ...body, explain: false }),
    });
    state.result = fast;
    state.decisions = fast.decisions;
    state.filter = "all";
    renderAnswer(fast);
    setStatus(found(fast), "success");

    // Phase 2 — let the model write the summary, then swap it in. Only worth a
    // second round trip when an LLM is actually configured and reachable.
    if (fast.reasoning_mode.mode !== "llm") return;
    const model = fast.reasoning_mode.model;
    setStatus(`${found(fast)} Writing the summary with ${model}…`, "loading");
    $("#answer-card").classList.add("is-generating");

    const full = await api("/api/query", {
      method: "POST",
      body: JSON.stringify({ ...body, explain: true }),
    });
    // Ignore a stale response if the user has since asked something else.
    if (state.result !== fast) return;
    state.result = full;
    state.decisions = full.decisions;
    renderAnswer(full);
    setStatus(`${found(full)} Summary written by ${model}.`, "success");
  } catch (error) {
    setStatus(`The agent could not answer that: ${error.message}`, "error");
  } finally {
    $("#answer-card").classList.remove("is-generating");
    $("#ask-button").disabled = false;
  }
}

function renderAnswer(result) {
  $("#answer-card").hidden = false;
  $("#answer-domain").textContent = result.domain_label;
  $("#answer-routing").textContent = result.routing === "auto" ? "Domain auto-detected" : "Domain pinned by you";
  $("#answer-savings").textContent = moneyExact(result.totals.savings_usd);
  $("#answer-text").textContent = result.answer;
  $("#next-action").textContent = result.next_action || "—";

  // A single-domain answer already reads as one paragraph; only break it out
  // when two analysts each had something to say.
  $("#route-breakdown").innerHTML = result.routes.length > 1
    ? result.routes.map((route) => `
        <div class="route">
          <h3><span class="dot ${esc(route.domain)}"></span>${esc(route.domain_label)}
            <em>${esc(titleCase(route.intent))}</em></h3>
          <p>${esc(route.answer)}</p>
        </div>`).join("")
    : "";

  $("#tools").innerHTML = result.tools_used.map((tool) => `<span>${esc(tool)}</span>`).join("");
  $("#trace-summary").textContent =
    `How this was worked out — ${result.tools_used.length} tools, ${result.routes.length} analyst${result.routes.length === 1 ? "" : "s"}`;

  const seen = new Set();
  $("#requirements").innerHTML = result.requirement_check
    .filter((row) => !seen.has(row.Requirement) && seen.add(row.Requirement))
    .map((row) => {
      const status = String(row.Status).toLowerCase();
      const tone = status.startsWith("available") ? "ok" : status.includes("not required") ? "off" : "warn";
      return `<div><span>${esc(row.Requirement)}</span><strong class="${tone}">${esc(row.Status)}</strong></div>`;
    }).join("");

  renderFilters(result);
  renderDecisions();
}

function renderFilters(result) {
  const counts = {
    all: result.totals.decisions,
    infrastructure: result.totals.infrastructure_decisions,
    ai_services: result.totals.ai_decisions,
  };
  const labels = { all: "All", infrastructure: "Infrastructure", ai_services: "AI services" };
  // Only offer a filter when the answer actually spans both domains.
  const options = counts.infrastructure && counts.ai_services
    ? ["all", "infrastructure", "ai_services"]
    : [];
  $("#decision-filters").innerHTML = options.map((key) => `
    <button class="filter ${key === state.filter ? "is-active" : ""}" type="button" data-filter="${key}">
      ${labels[key]} (${counts[key]})
    </button>`).join("");
}

function renderDecisions() {
  const section = $("#decisions-section");
  const rows = state.filter === "all"
    ? state.decisions
    : state.decisions.filter((row) => row.domain === state.filter);

  section.hidden = false;
  if (!rows.length) {
    $("#decision-list").innerHTML = `<div class="empty">
      No decision matched that question. Try one of the suggested questions above.</div>`;
    return;
  }

  $("#decision-list").innerHTML = rows.map((row) => {
    const index = state.decisions.indexOf(row);
    const value = row.savings_usd > 0
      ? `<strong>${moneyExact(row.savings_usd)}</strong><small>per month</small>`
      : `<strong>—</strong><small>no direct saving</small>`;
    return `<button class="decision" type="button" data-index="${index}">
      <span class="decision-rail rail-${esc(row.tone)}"></span>
      <span class="decision-main">
        <span class="decision-title">
          <strong>${esc(row.resource)}</strong>
          <span class="domain-tag">${esc(row.resource_kind)}</span>
        </span>
        <span class="decision-reason">${esc(row.reason)}</span>
        <span class="decision-meta">${esc(row.application)} · ${esc(row.provider)} · ${esc(row.environment)}</span>
      </span>
      <span class="decision-action">
        <span class="action-name"><i class="status-dot tone-${esc(row.tone)}"></i>${esc(row.action_label)}</span>
        <span class="action-sub">${Math.round(row.confidence)}% confidence · ${esc(row.risk)} risk</span>
      </span>
      <span class="decision-value">${value}</span>
    </button>`;
  }).join("");
}

/* ── drawer ──────────────────────────────────────────────── */

let lastFocused = null;

function openDrawer(index) {
  const row = state.decisions[index];
  if (!row) return;
  lastFocused = document.activeElement;

  $("#drawer-action").innerHTML = `<i class="status-dot tone-${esc(row.tone)}"></i> ${esc(row.action_label)}`;
  $("#drawer-title").textContent = row.resource;
  $("#drawer-sub").textContent =
    `${row.resource_kind} · ${row.application} · ${row.provider} · ${row.environment}`;
  $("#drawer-savings").textContent = row.savings_usd > 0 ? moneyExact(row.savings_usd) : "—";
  $("#drawer-confidence").textContent = `${Math.round(row.confidence)}%`;
  $("#drawer-risk").innerHTML = `<i class="status-dot tone-${esc(row.tone)}"></i>${esc(titleCase(row.risk))}`;
  $("#drawer-reason").textContent = row.reason || "—";
  $("#drawer-impact").textContent = row.business_impact || "—";

  $("#drawer-metrics").innerHTML = row.metrics.map((metric) => `
    <div><small>${esc(metric.label)}</small><strong>${esc(metric.value)}</strong>
    ${metric.detail ? `<em>${esc(metric.detail)}</em>` : ""}</div>`).join("");

  $("#drawer-lambda").textContent = row.lambda_function || "No automated action";
  $("#drawer-payload").textContent = JSON.stringify(row.action_payload, null, 2);

  $("#drawer").hidden = false;
  $("#drawer-backdrop").hidden = false;
  $("#drawer-close").focus();
}

function closeDrawer() {
  $("#drawer").hidden = true;
  $("#drawer-backdrop").hidden = true;
  if (lastFocused) lastFocused.focus();
}

/* ── infrastructure view ─────────────────────────────────── */

async function loadInfrastructure() {
  const infra = await api("/api/infra/summary");
  state.infra = infra;
  const k = infra.kpi;

  $("#infra-scope").textContent = `${k.resources} machines · ${k.providers} providers`;
  $("#infra-kpis").innerHTML = [
    kpi("Monthly cost", money(k.monthly_cost_usd), `${k.resources} virtual machines`),
    kpi("Savings available", money(k.savings_usd), `${pct(k.savings_pct)} of infrastructure spend`, "good"),
    kpi("Idle machines", k.idle_resources, `under 2% average CPU`),
    kpi("Shutdown candidates", k.shutdown_candidates, `policy-allowed and non-critical`),
    kpi("Rightsizing candidates", k.scale_down_candidates, `running below their own baseline`),
  ].join("");

  $("#utilization-meters").innerHTML = [
    meter({ label: "CPU", value: k.avg_cpu, note: "The binding signal for shutdown and rightsizing." }),
    meter({ label: "Memory", value: k.avg_memory, note: "Constrains how far a machine can be downsized." }),
    meter({ label: "Disk", value: k.avg_disk, note: "Rarely the reason to resize, often the reason not to." }),
    meter({ label: "Network", value: k.avg_network, note: "Separates a truly idle machine from a quiet one." }),
  ].join("");

  $("#cpu-band-chart").innerHTML = barChart(
    infra.cpu_bands.map((band) => ({
      label: band.label,
      value: band.count,
      tip: `${band.count} machine${band.count === 1 ? "" : "s"} at ${band.range} CPU<br>${moneyExact(band.monthly_cost_usd)} per month`,
    })),
    { format: (value) => String(value) },
  );

  $("#provider-chart").innerHTML = barChart(
    infra.providers.map((row) => ({
      label: row.provider.toUpperCase(),
      value: row.monthly_cost_usd,
      tip: `${moneyExact(row.monthly_cost_usd)} per month<br>${row.resources} machines · ${pct(row.avg_cpu)} avg CPU`,
    })),
  );

  $("#action-chart").innerHTML = barChart(
    infra.action_mix.map((row) => ({
      label: titleCase(row.action),
      value: row.count,
      tip: `${row.count} machine${row.count === 1 ? "" : "s"}<br>${moneyExact(row.savings_usd)} per month at stake`,
    })),
    { format: (value) => String(value) },
  );

  $("#environment-chart").innerHTML = barChart(
    infra.environments.map((row) => ({
      label: row.environment.toUpperCase(),
      value: row.monthly_cost_usd,
      tip: `${moneyExact(row.monthly_cost_usd)} per month across ${row.count} machines`,
    })),
  );

  $("#top-resources tbody").innerHTML = infra.top_resources.map((row) => `
    <tr>
      <td>${esc(row.resource)}</td>
      <td>${esc(row.application)}</td>
      <td>${esc(row.provider.toUpperCase())}</td>
      <td>${esc(row.environment)}</td>
      <td class="num">${pct(row.avg_cpu)}</td>
      <td class="num">${moneyExact(row.monthly_cost_usd)}</td>
      <td class="num">${row.savings_usd > 0 ? moneyExact(row.savings_usd) : "—"}</td>
      <td><span class="cell-action">${esc(titleCase(row.action))}</span></td>
    </tr>`).join("");

  const picker = $("#resource-picker");
  picker.innerHTML = infra.resources.map((id) => `<option value="${esc(id)}">${esc(id)}</option>`).join("");
  if (infra.resources.length) loadResource(infra.resources[0]);
}

async function loadResource(resourceId) {
  const target = $("#resource-detail");
  try {
    const detail = await api(`/api/infra/resource/${encodeURIComponent(resourceId)}`);
    const rec = detail.recommendation;
    const signals = [
      ["CPU", "cpu_percent", "Drives shutdown and rightsizing"],
      ["Memory", "memory_percent", "Floor for how small it can go"],
      ["Disk", "disk_percent", "Capacity check"],
      ["Network", "network_percent", "Idle versus quiet"],
    ];
    target.innerHTML = `
      <div class="resource-summary">
        <i class="status-dot tone-${esc(toneFor(rec["Recommended Action"]))}" style="margin-top:6px"></i>
        <span><strong>${esc(titleCase(rec["Recommended Action"]))}</strong> — ${esc(rec.Reason)}</span>
      </div>
      ${signals.map(([label, key, note]) => `
        <div class="spark-card">
          <div class="spark-head"><span>${label}</span><strong>${pct(detail.current[key])}</strong></div>
          ${sparkline(detail.series[key])}
          <p class="spark-foot">Peak ${pct(detail.peak[key])} · ${note}</p>
        </div>`).join("")}`;
  } catch (error) {
    target.innerHTML = `<p class="empty">Could not load ${esc(resourceId)}: ${esc(error.message)}</p>`;
  }
}

const TONES = {
  SCHEDULE_SHUTDOWN: "good", SCALE_DOWN: "good", MOVE_TO_SMALLER_SKU: "good",
  SCALE_UP: "warning", APPLICATION_REVIEW: "serious", DB_INVESTIGATION: "serious",
};
const toneFor = (action) => TONES[action] || "neutral";

/* ── forecast view ───────────────────────────────────────── */

async function loadForecast() {
  const target = $("#forecast-table tbody");
  target.innerHTML = `<tr><td colspan="7">Fitting models…</td></tr>`;

  let data = await api("/api/forecast/summary");
  // Models train on a background thread at startup; poll rather than block.
  if (data.warming) {
    $("#forecast-scope").textContent = "training models…";
    for (let i = 0; i < 40 && data.warming; i += 1) {
      await new Promise((r) => setTimeout(r, 3000));
      data = await api("/api/forecast/summary");
    }
  }
  state.forecast = data;

  if (!data.forecasts.length) {
    $("#forecast-scope").textContent = "unavailable";
    target.innerHTML = `<tr><td colspan="7">No forecast available.</td></tr>`;
    return;
  }

  $("#forecast-scope").textContent = `${data.covered} of ${data.total} machines`;
  const recalls = data.forecasts.map((f) => f.breach_recall_pct).filter((v) => v != null);
  const meanMae = data.forecasts.reduce((s, f) => s + f.mae, 0) / data.forecasts.length;
  $("#forecast-kpis").innerHTML = [
    kpi("Predicted breaches", data.predicted_breaches, "in the next 24 hours",
        data.predicted_breaches ? "" : "good"),
    kpi("Tightest headroom", data.tightest_headroom == null ? "—" : `${data.tightest_headroom} pts`,
        "closest any machine comes to its threshold"),
    kpi("Machines modelled", `${data.covered} / ${data.total}`, data.selection),
    kpi("Mean error", `${meanMae.toFixed(2)} pts`, "CPU points, on held-out data"),
    kpi("Breach recall", recalls.length ? `${(recalls.reduce((a, b) => a + b, 0) / recalls.length).toFixed(0)}%` : "—",
        "of real breaches called in advance"),
  ].join("");

  target.innerHTML = data.forecasts.map((f) => {
    const tone = f.will_breach ? "critical" : "good";
    const verdict = f.will_breach ? "Will breach" : "Within limits";
    return `<tr>
      <td>${esc(f.resource)}</td>
      <td class="num">${f.predicted_peak_cpu == null ? "—" : pct(f.predicted_peak_cpu)}</td>
      <td class="num">${pct(f.threshold)}</td>
      <td class="num">${f.headroom_to_threshold == null ? "—" : `${f.headroom_to_threshold} pts`}</td>
      <td><span class="cell-action"><i class="status-dot tone-${tone}"></i>${verdict}</span></td>
      <td class="num">${f.mae.toFixed(2)}</td>
      <td class="num">${f.breach_recall_pct == null ? "—" : pct(f.breach_recall_pct)}</td>
    </tr>`;
  }).join("");

  const picker = $("#forecast-picker");
  picker.innerHTML = data.forecasts
    .map((f) => `<option value="${esc(f.resource)}">${esc(f.resource)}</option>`).join("");
  loadForecastDetail(data.forecasts[0].resource);
}

async function loadForecastDetail(resourceId) {
  const target = $("#forecast-detail");
  target.innerHTML = `<p class="empty">Fitting model for ${esc(resourceId)}…</p>`;
  try {
    const d = await api(`/api/forecast/${encodeURIComponent(resourceId)}`);
    const m = d.metrics;
    const ahead = d.ahead || {};
    const v = ahead.validation || {};
    target.innerHTML = `
      <div class="metric-grid" style="margin-bottom:18px">
        <div><small>Mean absolute error</small><strong>${m.mae} pts</strong><em>on ${d.tested_on} unseen hours</em></div>
        <div><small>RMSE</small><strong>${m.rmse} pts</strong></div>
        <div><small>Breaches called</small><strong>${m.breaches_caught} / ${m.breaches_caught + m.breaches_missed}</strong><em>${m.false_alarms} false alarms</em></div>
        <div><small>Predicted peak (${ahead.horizon_hours || 24}h)</small><strong>${ahead.predicted_peak_cpu == null ? "—" : pct(ahead.predicted_peak_cpu)}</strong><em>${v.mae ? `±${v.mae} pts` : ""}</em></div>
      </div>
      ${dualLine(d.actual, d.predicted, d.threshold)}
      <p class="safety-note">${esc(d.model)} · trained on ${d.trained_on} hours up to
        ${esc(String(d.train_end).replace("T", " "))} · threshold from training data only.</p>`;
  } catch (error) {
    target.innerHTML = `<p class="empty">Could not forecast ${esc(resourceId)}: ${esc(error.message)}</p>`;
  }
}

/* ── AI services view ────────────────────────────────────── */

async function loadAiServices() {
  const summary = await api("/api/ai-finops/summary");
  state.ai = summary;
  const p = summary.profile;

  $("#ai-scope").textContent = `${p.deployments} deployments · ${p.models} models`;
  $("#ai-kpis").innerHTML = [
    kpi("Monthly cost", money(p.monthly_cost_usd), `${p.deployments} deployments`),
    kpi("Savings available", money(p.savings_opportunity_usd), "approval-gated", "good"),
    kpi("Requests", compact(p.requests), "over 30 days"),
    kpi("Tokens processed", compact(p.input_tokens + p.output_tokens), "input plus output"),
  ].join("");

  $("#ai-provider-chart").innerHTML = barChart(
    Object.entries(summary.provider_cost).map(([name, value]) => ({
      label: name, value, tip: `${moneyExact(value)} per month`,
    })),
  );

  $("#ai-deployment-chart").innerHTML = barChart(
    summary.deployments.slice(0, 8).map((row) => ({
      label: row.deployment_key,
      value: row.monthly_cost_usd,
      tip: `${moneyExact(row.monthly_cost_usd)} per month<br>${compact(row.requests_30d)} requests · ${row.model}`,
    })),
  );

  $("#ai-deployments tbody").innerHTML = summary.deployments.map((row) => `
    <tr>
      <td>${esc(row.deployment_key)}</td>
      <td>${esc(row.application)}</td>
      <td>${esc(row.model)}</td>
      <td class="num">${compact(row.requests_30d)}</td>
      <td class="num">${moneyExact(row.monthly_cost_usd)}</td>
      <td class="num">${Number(row.quality_score).toFixed(2)}</td>
      <td class="num">${Math.round(row.latency_p95_ms)} ms</td>
      <td>${esc(titleCase(row.criticality))}</td>
    </tr>`).join("");
}

/* ── activity view ───────────────────────────────────────── */

async function loadActivity() {
  const [events, architecture, operational] = await Promise.all([
    api("/api/events?limit=25"),
    api("/api/architecture"),
    api("/api/operational/summary"),
  ]);

  $("#activity-kpis").innerHTML = [
    kpi("Events published", events.summary.total_events, `${events.summary.processed_events} processed`),
    kpi("Agent runs", operational.agent_runs, "recorded in the audit trail"),
    kpi("Lambda payloads", operational.serverless_actions, "proposed, never executed"),
    kpi("Pipeline runs", operational.pipeline_runs, "ingestion history"),
  ].join("");

  $("#flow").innerHTML = architecture.flow
    .map((step, index) => `<li><b>Step ${index + 1}</b>${esc(step)}</li>`)
    .join("");

  $("#event-table tbody").innerHTML = (events.events || []).map((event) => `
    <tr>
      <td>${esc(String(event.created_at).replace("T", " "))}</td>
      <td>${esc(event.event_type)}</td>
      <td>${esc(titleCase(event.status))}</td>
      <td style="white-space:normal">${esc(event.result_summary || event.source)}</td>
    </tr>`).join("");
}

async function runEventDemo() {
  const button = $("#run-events");
  button.disabled = true;
  button.textContent = "Processing…";
  try {
    await api("/api/demo-run", { method: "POST" });
    await loadActivity();
  } catch (error) {
    $("#event-table tbody").innerHTML =
      `<tr><td colspan="4">Event run failed: ${esc(error.message)}</td></tr>`;
  } finally {
    button.disabled = false;
    button.textContent = "Run a telemetry event";
  }
}

/* ── wiring ──────────────────────────────────────────────── */

function initEvents() {
  $$(".viewtab").forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));

  $("#ask-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runQuery();
  });

  $("#suggestions").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-question]");
    if (chip) runQuery(chip.dataset.question);
  });

  $("#decision-filters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-filter]");
    if (!button) return;
    state.filter = button.dataset.filter;
    renderFilters(state.result);
    renderDecisions();
  });

  $("#decision-list").addEventListener("click", (event) => {
    const card = event.target.closest("[data-index]");
    if (card) openDrawer(Number(card.dataset.index));
  });

  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#drawer").hidden) closeDrawer();
  });

  $("#copy-payload").addEventListener("click", async () => {
    const button = $("#copy-payload");
    try {
      await navigator.clipboard.writeText($("#drawer-payload").textContent);
      button.textContent = "Copied";
    } catch {
      button.textContent = "Copy failed";
    }
    setTimeout(() => { button.textContent = "Copy payload"; }, 1600);
  });

  $("#resource-picker").addEventListener("change", (event) => loadResource(event.target.value));
  $("#forecast-picker").addEventListener("change", (event) => loadForecastDetail(event.target.value));
  $("#run-events").addEventListener("click", runEventDemo);
}

async function boot() {
  initTheme();
  initTooltip();
  initEvents();

  try {
    const [, suggestions] = await Promise.all([loadOverview(), api("/api/suggestions")]);
    renderSuggestions(suggestions.suggestions);
    setStatus("Ready. Ask a question, or pick one of the examples above.");
  } catch (error) {
    setStatus(`Could not reach the API: ${error.message}`, "error");
  }
}

boot();
