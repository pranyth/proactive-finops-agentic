const state = {
  answer: null,
  audit: null,
  events: null,
  architecture: null,
  activeAuditTab: "agent_runs",
};

const $ = (selector) => document.querySelector(selector);

function fmt(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value).slice(0, 220);
  return String(value);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
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
      <span>${row.label}</span>
      <strong>${fmt(row.value)}</strong>
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
    <thead><tr>${columns.map((col) => `<th>${col}</th>`).join("")}</tr></thead>
    <tbody>
      ${rows.map((row) => `
        <tr>${columns.map((col) => `<td>${fmt(row[col])}</td>`).join("")}</tr>
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

function renderAnswer(answer) {
  state.answer = answer;
  $("#intent-pill").textContent = answer.intent;
  $("#answer-text").textContent = answer.answer;
  $("#next-action").textContent = answer.next_action;

  $("#tools-used").innerHTML = answer.tools_used.map((tool) => `<div class="tool-chip">${tool}</div>`).join("");
  $("#requirement-list").innerHTML = answer.requirement_check.map((item) => `
    <div class="requirement ${requirementClass(item.Status)}">
      <span>${item.Requirement}</span>
      <strong>${item.Status}</strong>
    </div>
  `).join("");

  const evidenceRows = Object.entries(answer.evidence || {}).map(([key, value]) => ({ label: key.replaceAll("_", " "), value }));
  renderKeyValueGrid($("#evidence-strip"), evidenceRows, "evidence-item");
  renderTable($("#recommendations-table"), answer.recommendations);
  renderProfile(answer.dataset_profile);
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
  $("#architecture-flow").innerHTML = architecture.flow.map((step) => `<div class="flow-step">${step}</div>`).join("");
  $("#event-flow").innerHTML = (architecture.event_flow || []).map((step) => `<div class="event-step">${step}</div>`).join("");
  $("#component-grid").innerHTML = architecture.components.map((item) => `
    <div class="component-item">
      <span>${item.role}</span>
      <strong>${item.component}</strong>
      <p>${item.output}</p>
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
  $("#metric-events").textContent = fmt(summary.total_events);
  $("#metric-events-processed").textContent = fmt(summary.processed_events);
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
  const custom = $("#custom-question").value.trim();
  const selected = $("#question-select").value;
  const question = custom || selected;
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
    setRunStatus("Answer updated below. Requirements and evidence are refreshed too.", "success");
    if (!options.silent) {
      $("#agent-output").scrollIntoView({ behavior: "smooth", block: "start" });
    }
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
  } finally {
    button.disabled = false;
    button.textContent = "Run Event Demo";
  }
}

async function refreshEvents() {
  renderEvents(await api("/api/events"));
}

async function refreshAudit(force = false) {
  if (force) {
    await api("/api/operational/refresh", { method: "POST", body: JSON.stringify({ force: true }) });
  }
  state.audit = await api("/api/operational/audit");
  renderAudit();
  const summary = await api("/api/operational/summary");
  $("#metric-pipelines").textContent = fmt(summary.pipeline_runs);
  $("#metric-actions").textContent = fmt(summary.serverless_actions);
  if (summary.events !== undefined) $("#metric-events").textContent = fmt(summary.events);
  if (summary.processed_events !== undefined) $("#metric-events-processed").textContent = fmt(summary.processed_events);
}

async function init() {
  try {
    await api("/api/health");
    setApiStatus(true, "API online");
    const questions = await api("/api/questions");
    $("#question-select").innerHTML = questions.questions.map((question) => `<option value="${question}">${question}</option>`).join("");
    renderProfile(await api("/api/dataset-profile"));
    renderArchitecture(await api("/api/architecture"));
    await refreshEvents();
    await runAgent({ silent: true });
    await refreshAudit(false);
    window.setInterval(refreshEvents, 5000);
  } catch (error) {
    console.error(error);
    setApiStatus(false, "API error");
    $("#answer-text").textContent = `API error: ${error.message}`;
  }
}

$("#run-agent").addEventListener("click", runAgent);
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
