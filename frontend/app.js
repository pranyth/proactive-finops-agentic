const state = {
  answer: null,
  audit: null,
  events: null,
  architecture: null,
  activeAuditTab: "agent_runs",
  selectedRecommendationIndex: 0,
};

const $ = (selector) => document.querySelector(selector);

function fmt(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value).slice(0, 220);
  return String(value);
}

function money(value) {
  const number = Number(value || 0);
  return `$${number.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function esc(value) {
  return fmt(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function field(row, name, fallback = "-") {
  return row && row[name] !== undefined && row[name] !== null && row[name] !== "" ? row[name] : fallback;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function setApiStatus(ok, text) {
  const dot = document.querySelector(".status-dot");
  dot.classList.toggle("ok", ok);
  dot.classList.toggle("bad", !ok);
  $("#api-status").textContent = text;
}

function setRunStatus(text, kind = "idle") {
  const target = $("#run-status");
  if (!target) return;
  target.textContent = text;
  target.className = `run-status ${kind}`;
}

function renderKeyValueGrid(target, rows, className) {
  target.innerHTML = rows.map((row) => `
    <div class="${className}">
      <span>${esc(row.label)}</span>
      <strong>${esc(row.value)}</strong>
    </div>
  `).join("");
}

function renderTable(target, rows) {
  if (!rows || rows.length === 0) {
    target.innerHTML = "<tbody><tr><td>No rows returned.</td></tr></tbody>";
    return;
  }
  const columns = Object.keys(rows[0]);
  target.innerHTML = `
    <thead><tr>${columns.map((col) => `<th>${esc(col)}</th>`).join("")}</tr></thead>
    <tbody>
      ${rows.map((row) => `
        <tr>${columns.map((col) => `<td>${esc(row[col])}</td>`).join("")}</tr>
      `).join("")}
    </tbody>
  `;
}

function requirementClass(status) {
  const value = String(status).toLowerCase();
  if (value.includes("missing")) return "missing";
  if (value.includes("optional") || value.includes("depends") || value.includes("important")) return "optional";
  return "available";
}

function providerClass(provider) {
  const value = String(provider || "").toLowerCase();
  if (value.includes("aws")) return "aws";
  if (value.includes("gcp")) return "gcp";
  return "azure";
}

function actionFunctionName(action) {
  const value = String(action || "").toUpperCase();
  if (value.includes("SCALE_UP")) return "finops-scale-up-lambda";
  if (value.includes("SCALE_DOWN") || value.includes("SMALLER")) return "finops-scale-down-lambda";
  if (value.includes("SHUTDOWN")) return "finops-schedule-shutdown-lambda";
  if (value.includes("DB")) return "finops-db-investigation-lambda";
  if (value.includes("PIPELINE")) return "finops-pipeline-alert-lambda";
  return "finops-review-recommendation-lambda";
}

function buildActionPayload(row) {
  const action = field(row, "Recommended Action", "REVIEW");
  return {
    function_name: actionFunctionName(action),
    payload: {
      resource_id: field(row, "VM"),
      provider: field(row, "Provider"),
      account_id: field(row, "Account ID"),
      region: field(row, "Region"),
      application: field(row, "Application"),
      environment: field(row, "Environment"),
      action,
      confidence: field(row, "Confidence"),
      estimated_monthly_savings_usd: field(row, "Estimated Savings Monthly USD", 0),
      approval_required: field(row, "Approval Required"),
      reason: field(row, "Reason"),
      source: "FinOps Analyst Agent",
    },
  };
}

function renderRecommendationCards(recommendations) {
  const target = $("#recommendation-cards");
  if (!recommendations || recommendations.length === 0) {
    target.className = "recommendation-cards empty-state";
    target.textContent = "No recommendations returned for this question.";
    renderSelectedRecommendation(null);
    return;
  }

  target.className = "recommendation-cards";
  target.innerHTML = recommendations.slice(0, 8).map((row, index) => {
    const selected = index === state.selectedRecommendationIndex ? " selected" : "";
    return `
      <button class="rec-card${selected}" data-rec-index="${index}">
        <div class="rec-card-top">
          <span class="provider ${providerClass(field(row, "Provider"))}">${esc(field(row, "Provider"))}</span>
          <strong>${esc(field(row, "Recommended Action"))}</strong>
        </div>
        <h3>${esc(field(row, "VM"))}</h3>
        <div class="rec-card-meta">
          <span>${esc(field(row, "Environment"))}</span>
          <span>${esc(field(row, "Business Criticality"))} criticality</span>
          <span>${money(field(row, "Estimated Savings Monthly USD", 0))}/mo</span>
        </div>
        <p>${esc(field(row, "Reason"))}</p>
      </button>
    `;
  }).join("");

  document.querySelectorAll(".rec-card").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedRecommendationIndex = Number(card.dataset.recIndex);
      renderRecommendationCards(state.answer.recommendations || []);
      renderSelectedRecommendation(state.answer.recommendations[state.selectedRecommendationIndex]);
    });
  });
}

function renderSelectedRecommendation(row) {
  if (!row) {
    $("#selected-action-pill").textContent = "no selection";
    $("#selected-summary").className = "selected-summary empty-state";
    $("#selected-summary").textContent = "Select a recommendation to see the evidence and action payload.";
    $("#selected-detail-grid").innerHTML = "";
    $("#payload-function").textContent = "-";
    $("#action-payload").textContent = "{}";
    return;
  }

  const action = field(row, "Recommended Action");
  const payload = buildActionPayload(row);
  $("#selected-action-pill").textContent = action;
  $("#selected-summary").className = "selected-summary";
  $("#selected-summary").innerHTML = `
    <strong>${esc(field(row, "VM"))}</strong>
    <span>${esc(field(row, "Business Impact"))}</span>
    <p>${esc(field(row, "Reason"))}</p>
  `;

  renderKeyValueGrid($("#selected-detail-grid"), [
    { label: "Provider", value: field(row, "Provider") },
    { label: "Application", value: field(row, "Application") },
    { label: "Environment", value: field(row, "Environment") },
    { label: "Criticality", value: field(row, "Business Criticality") },
    { label: "Avg CPU 48h", value: `${field(row, "Avg CPU 48h")}%` },
    { label: "Avg Network 48h", value: `${field(row, "Avg Network 48h")}%` },
    { label: "Confidence", value: `${field(row, "Confidence")}%` },
    { label: "Monthly Savings", value: money(field(row, "Estimated Savings Monthly USD", 0)) },
    { label: "Approval Required", value: field(row, "Approval Required") },
    { label: "Shutdown Allowed", value: field(row, "Shutdown Allowed") },
    { label: "Incidents", value: field(row, "Incident Count") },
    { label: "Telemetry Source", value: field(row, "Telemetry Source") },
  ], "detail-item");

  $("#payload-function").textContent = payload.function_name;
  $("#action-payload").textContent = JSON.stringify(payload.payload, null, 2);
}

function renderAnswer(answer) {
  state.answer = answer;
  state.selectedRecommendationIndex = 0;

  $("#intent-pill").textContent = answer.intent;
  $("#answer-text").textContent = answer.answer;
  $("#next-action").textContent = answer.next_action;
  $("#tools-used").innerHTML = (answer.tools_used || []).map((tool) => `<div class="tool-chip">${esc(tool)}</div>`).join("");

  $("#requirement-list").innerHTML = (answer.requirement_check || []).map((item) => `
    <div class="requirement ${requirementClass(item.Status)}">
      <span>${esc(item.Requirement)}</span>
      <strong>${esc(item.Status)}</strong>
    </div>
  `).join("");

  const evidenceRows = Object.entries(answer.evidence || {}).map(([key, value]) => ({ label: key.replaceAll("_", " "), value }));
  renderKeyValueGrid($("#evidence-strip"), evidenceRows, "evidence-item");
  renderTable($("#recommendations-table"), answer.recommendations);
  renderRecommendationCards(answer.recommendations || []);
  renderSelectedRecommendation((answer.recommendations || [])[0]);
  renderProfile(answer.dataset_profile);

  const count = (answer.recommendations || []).length;
  const savings = answer.evidence?.estimated_monthly_savings_usd || answer.recommendations?.reduce((sum, row) => sum + Number(field(row, "Estimated Savings Monthly USD", 0)), 0) || 0;
  $("#metric-recommendations").textContent = fmt(count);
  $("#metric-savings").textContent = money(savings);
}

function renderProfile(profile) {
  $("#metric-vms").textContent = fmt(profile.provider_count || profile.vm_count);
  $("#metric-vm-rows").textContent = fmt(profile.multicloud_rows || profile.vm_rows);

  renderKeyValueGrid($("#profile-grid"), [
    { label: "Project Title", value: profile.primary_title || "Agentic Proactive FinOps Governance" },
    { label: "Dataset", value: profile.dataset_name },
    { label: "Platform Scope", value: profile.platform_scope || "single_cloud" },
    { label: "Providers", value: Object.entries(profile.providers || {}).map(([key, value]) => `${key}: ${value}`).join(", ") },
    { label: "Source Systems", value: Object.keys(profile.source_systems || {}).join(", ") },
    { label: "Schema Versions", value: (profile.schema_versions || []).join(", ") },
    { label: "Types", value: (profile.dataset_types || []).join(", ") },
    { label: "Time Range", value: `${profile.time_range?.start || "-"} -> ${profile.time_range?.end || "-"}` },
    { label: "Applications", value: (profile.applications || []).join(", ") },
    { label: "Tagged VMs", value: profile.application_tagged_vms },
    { label: "Enterprise Context", value: profile.enterprise_context_available ? "Available" : "Missing" },
    { label: "Raw CoreStack BSON", value: profile.raw_corestack_bson },
    { label: "Raw BSON Required", value: profile.raw_corestack_required },
    { label: "Evaluation Note", value: profile.evaluation_note },
  ], "profile-item");

  const sourceRows = Object.entries(profile.source_mix || {}).map(([key, value]) => ({ label: key, value }));
  renderKeyValueGrid($("#source-mix"), sourceRows, "source-item");
}

function renderArchitecture(architecture) {
  state.architecture = architecture;
  $("#architecture-flow").innerHTML = architecture.flow.map((step) => `<div class="flow-step">${esc(step)}</div>`).join("");
  $("#event-flow").innerHTML = (architecture.event_flow || []).map((step) => `<div class="event-step">${esc(step)}</div>`).join("");
  $("#component-grid").innerHTML = architecture.components.map((item) => `
    <div class="component-item">
      <span>${esc(item.role)}</span>
      <strong>${esc(item.component)}</strong>
      <p>${esc(item.output)}</p>
    </div>
  `).join("");
}

function compactEventRows(events) {
  return (events || []).map((event) => ({
    created_at: event.created_at,
    event_type: event.event_type,
    source: event.source,
    status: event.status,
    attempts: event.attempts,
    correlation_id: event.correlation_id,
    result_summary: event.result_summary,
  }));
}

function renderEvents(data) {
  state.events = data;
  const summary = data.summary || {};
  const coordinator = data.coordinator || {};
  renderKeyValueGrid($("#event-summary"), [
    { label: "Total Events", value: summary.total_events },
    { label: "Pending", value: summary.pending_events },
    { label: "Processed", value: summary.processed_events },
    { label: "Failed", value: summary.failed_events },
  ], "evidence-item");
  $("#coordinator-status").textContent = fmt(coordinator.status);
  $("#coordinator-decision").textContent = fmt(coordinator.last_decision);
  $("#coordinator-last-event").textContent = fmt(coordinator.last_event_type);
  $("#coordinator-processed").textContent = fmt(coordinator.events_processed);
  $("#coordinator-failed").textContent = fmt(coordinator.events_failed);
  renderTable($("#events-table"), compactEventRows(data.events));
}

function renderAudit() {
  if (!state.audit) return;
  if (state.activeAuditTab === "events") {
    renderTable($("#audit-table"), compactEventRows(state.audit.events));
    return;
  }
  renderTable($("#audit-table"), state.audit[state.activeAuditTab] || []);
}

async function runAgent(options = {}) {
  const button = $("#run-agent");
  const question = $("#custom-question").value.trim();
  if (!question) {
    setRunStatus("Type a question before running the agent.", "error");
    return;
  }
  button.disabled = true;
  button.textContent = "Running";
  setRunStatus(`Running FinOps Analyst Agent for: ${question}`, "running");
  $("#answer-text").textContent = "Analyzing telemetry, requirements, recommendations, and evidence...";
  try {
    const answer = await api("/api/query", {
      method: "POST",
      body: JSON.stringify({
        question,
        time_window: $("#time-window").value,
        cloud: "multi-cloud",
      }),
    });
    renderAnswer(answer);
    setRunStatus("Answer updated. Click any VM card to inspect the reasoning and action payload.", "success");
    if (!options.silent) $("#decision").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    console.error(error);
    setRunStatus(`Agent failed: ${error.message}`, "error");
    $("#answer-text").textContent = `Agent failed: ${error.message}`;
  } finally {
    button.disabled = false;
    button.textContent = "Run Agent";
  }
}

async function runEventDemo() {
  const button = $("#run-event-demo");
  button.disabled = true;
  button.textContent = "Running Events";
  try {
    await api("/api/events/demo-run", { method: "POST", body: JSON.stringify({}) });
    await refreshEvents();
    await refreshAudit(false);
    document.querySelector("#operations details")?.setAttribute("open", "open");
  } finally {
    button.disabled = false;
    button.textContent = "Run Event Demo";
  }
}

async function refreshEvents() {
  renderEvents(await api("/api/events"));
}

async function refreshAudit(force = false) {
  if (force) await api("/api/operational/refresh", { method: "POST", body: JSON.stringify({ force: true }) });
  state.audit = await api("/api/operational/audit");
  renderAudit();
  const summary = await api("/api/operational/summary");
  $("#metric-pipelines").textContent = fmt(summary.pipeline_runs);
  $("#metric-actions").textContent = fmt(summary.serverless_actions);
}

async function init() {
  try {
    await api("/api/health");
    setApiStatus(true, "API online");
    renderProfile(await api("/api/dataset-profile"));
    renderArchitecture(await api("/api/architecture"));
    await refreshEvents();
    await runAgent({ silent: true });
    await refreshAudit(false);
    window.setInterval(refreshEvents, 5000);
  } catch (error) {
    console.error(error);
    setApiStatus(false, "API error");
    setRunStatus(`API error: ${error.message}`, "error");
    $("#answer-text").textContent = `API error: ${error.message}`;
  }
}

$("#run-agent").addEventListener("click", () => runAgent());
$("#run-event-demo").addEventListener("click", runEventDemo);
$("#refresh-demo").addEventListener("click", () => refreshAudit(true));

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    state.activeAuditTab = tab.dataset.tab;
    renderAudit();
  });
});

init();
