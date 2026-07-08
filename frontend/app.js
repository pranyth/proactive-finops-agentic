const state = {
  answer: null,
  audit: null,
  activeAuditTab: "agent_runs",
};

const $ = (selector) => document.querySelector(selector);

function fmt(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (typeof value === "boolean") return value ? "Yes" : "No";
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
  $("#metric-vms").textContent = fmt(profile.vm_count);
  $("#metric-vm-rows").textContent = fmt(profile.vm_rows);
  $("#metric-cost-rows").textContent = fmt(profile.cost_rows);
  $("#metric-incidents").textContent = fmt(profile.incident_rows);
  $("#metric-pipelines").textContent = fmt(profile.pipeline_rows);
  $("#metric-actions").textContent = fmt(profile.action_rows);

  renderKeyValueGrid($("#profile-grid"), [
    { label: "Dataset", value: profile.dataset_name },
    { label: "Types", value: (profile.dataset_types || []).join(", ") },
    { label: "Time Range", value: `${profile.time_range?.start || "-"} -> ${profile.time_range?.end || "-"}` },
    { label: "Applications", value: (profile.applications || []).join(", ") },
    { label: "Tagged VMs", value: profile.application_tagged_vms },
    { label: "Enterprise Context", value: profile.enterprise_context_available ? "Available" : "Missing" },
    { label: "Raw CoreStack BSON", value: profile.raw_corestack_bson },
    { label: "Raw BSON Required", value: profile.raw_corestack_required },
  ], "profile-item");

  const sourceRows = Object.entries(profile.source_mix || {}).map(([key, value]) => ({ label: key, value }));
  renderKeyValueGrid($("#source-mix"), sourceRows, "source-item");
}

function renderArchitecture(architecture) {
  $("#architecture-flow").innerHTML = architecture.flow.map((step) => `<div class="flow-step">${step}</div>`).join("");
  $("#component-grid").innerHTML = architecture.components.map((item) => `
    <div class="component-item">
      <span>${item.role}</span>
      <strong>${item.component}</strong>
      <p>${item.output}</p>
    </div>
  `).join("");
}

function renderAudit() {
  if (!state.audit) return;
  renderTable($("#audit-table"), state.audit[state.activeAuditTab] || []);
}

async function runAgent() {
  const button = $("#run-agent");
  const custom = $("#custom-question").value.trim();
  const selected = $("#question-select").value;
  button.disabled = true;
  button.textContent = "Running";
  try {
    const answer = await api("/api/query", {
      method: "POST",
      body: JSON.stringify({
        question: custom || selected,
        time_window: $("#time-window").value,
        cloud: "azure",
      }),
    });
    renderAnswer(answer);
  } finally {
    button.disabled = false;
    button.textContent = "Run Agent";
  }
}

async function refreshAudit(force = false) {
  if (force) {
    await api("/api/operational/refresh", { method: "POST", body: JSON.stringify({ force: true }) });
  }
  state.audit = await api("/api/operational/audit");
  renderAudit();
  const summary = await api("/api/operational/summary");
  if (!state.answer) {
    $("#metric-pipelines").textContent = fmt(summary.pipeline_runs);
    $("#metric-actions").textContent = fmt(summary.serverless_actions);
  }
}

async function init() {
  try {
    await api("/api/health");
    setApiStatus(true, "API online");
    const questions = await api("/api/questions");
    $("#question-select").innerHTML = questions.questions.map((question) => `<option value="${question}">${question}</option>`).join("");
    renderProfile(await api("/api/dataset-profile"));
    renderArchitecture(await api("/api/architecture"));
    await runAgent();
    await refreshAudit(false);
  } catch (error) {
    console.error(error);
    setApiStatus(false, "API error");
    $("#answer-text").textContent = `API error: ${error.message}`;
  }
}

$("#run-agent").addEventListener("click", runAgent);
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
