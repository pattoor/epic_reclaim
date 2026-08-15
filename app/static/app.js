const state = {
  view: "dashboard",
  accounts: [],
  authToken: null,
  authPollTimer: null,
  pollTimer: null,
  currentRunId: null,
};

function $(id) { return document.getElementById(id); }

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function switchView(view) {
  state.view = view;
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view)
  );
  document.querySelectorAll("main > section").forEach((s) => {
    s.hidden = s.id !== `view-${view}`;
  });
  if (view === "accounts") loadAccounts();
  if (view === "history") loadHistory();
  if (view === "settings") loadSettings();
  if (view === "dashboard") loadDashboard();
  if (view === "execution" && state.currentRunId) loadExecution(state.currentRunId);
}

document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => switchView(b.dataset.view))
);

async function loadDashboard() {
  try {
    const [health, runs, accounts, claims, settings] = await Promise.all([
      api("/health"),
      api("/api/runs?limit=5"),
      api("/api/accounts"),
      api("/api/claims?limit=8"),
      api("/api/settings"),
    ]);
    $("health-status").textContent =
      `status: ${health.status} | database: ${health.database} | playwright: ${health.playwright} | remote screen: ${health.remote_screen}`;

    const lastRun = runs[0];
    $("last-run").textContent = lastRun
      ? `#${lastRun.id} ${lastRun.status} (${lastRun.started_at})`
      : "no runs yet";

    const interventions = accounts.filter(
      (a) => a.state === "needs_intervention" || a.state === "needs_authentication"
    );
    $("interventions").textContent = interventions.length
      ? interventions.map((a) => `${a.display_name} (${a.state})`).join(", ")
      : "none";

    renderRecentClaims(claims);
    renderRecentRuns(runs);
    $("scheduler-status").textContent = settings.scheduler_enabled
      ? `enabled (every ${settings.scheduler_interval_seconds}s)`
      : "disabled";
    $("next-run").textContent = settings.scheduler_enabled && settings.next_run_at
      ? `next run: ${settings.next_run_at}`
      : "scheduler off";
  } catch (error) {
    $("health-status").textContent = error.message;
  }
}

function renderRecentRuns(runs) {
  const body = $("recent-runs").querySelector("tbody");
  body.innerHTML = runs
    .map(
      (r) =>
        `<tr><td>${r.id}</td><td>${escapeHtml(r.trigger_source)}</td><td class="status-${r.status}">${r.status}</td><td>${r.games_detected}</td><td>${r.claimed_count}</td><td>${r.failed_count}</td></tr>`
    )
    .join("");
}

function renderRecentClaims(claims) {
  const body = $("recent-claims").querySelector("tbody");
  body.innerHTML = claims
    .map(
      (c) =>
        `<tr><td>${escapeHtml(c.game_name || "")}</td><td class="status-${c.status}">${c.status}</td><td>${escapeHtml(c.updated_at || "")}</td></tr>`
    )
    .join("");
}

async function schedulerInfo() {
  try {
    const settings = await api("/api/settings");
    $("scheduler-status").textContent = settings.scheduler_enabled
      ? `enabled (every ${settings.scheduler_interval_seconds}s)`
      : "disabled";
    $("next-run").textContent = settings.scheduler_enabled && settings.next_run_at
      ? `next run: ${settings.next_run_at}`
      : "scheduler off";
  } catch (error) {
    $("scheduler-status").textContent = error.message;
  }
}

$("run-now").addEventListener("click", async () => {
  $("run-feedback").textContent = "starting run...";
  try {
    const result = await api("/api/runs/manual", { method: "POST" });
    $("run-feedback").textContent = `run #${result.run_id} started`;
    state.currentRunId = result.run_id;
    switchView("execution");
    watchRun(result.run_id);
  } catch (error) {
    $("run-feedback").textContent = error.message;
  }
});

function watchRun(runId) {
  state.currentRunId = runId;
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const [run, events] = await Promise.all([
        api(`/api/runs/${runId}`),
        api(`/api/runs/${runId}/events`),
      ]);
      renderExecution(runId, run, events);
      $("run-feedback").textContent =
        `run #${runId}: ${run.status} | claimed ${run.claimed_count} | failed ${run.failed_count} | games ${run.games_detected}`;
      if (run.status !== "running") {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
      }
      if (state.view === "dashboard") loadDashboard();
    } catch (error) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }, 2000);
}

async function loadExecution(runId) {
  try {
    const [run, events] = await Promise.all([
      api(`/api/runs/${runId}`),
      api(`/api/runs/${runId}/events`),
    ]);
    renderExecution(runId, run, events);
  } catch (error) {
    $("execution-summary").textContent = error.message;
  }
}

function renderExecution(runId, run, events) {
  $("execution-run").textContent = `Run #${runId} (${run.status})`;
  $("execution-summary").textContent =
    `games ${run.games_detected} | claimed ${run.claimed_count} | already owned ${run.already_owned_count} | failed ${run.failed_count}`;
  $("execution-events").querySelector("tbody").innerHTML = events
    .slice()
    .reverse()
    .map((event) => `<tr><td>${escapeHtml(event.created_at || "")}</td><td>${escapeHtml(event.event_type)}</td><td>${event.account_id || ""}</td><td>${event.game_id || ""}</td><td>${escapeHtml(event.message || "")}</td></tr>`)
    .join("");
}

$("add-account").addEventListener("click", async () => {
  const name = $("new-account-name").value.trim();
  if (!name) return;
  try {
    await api("/api/accounts", {
      method: "POST",
      body: JSON.stringify({ display_name: name }),
    });
    $("new-account-name").value = "";
    loadAccounts();
  } catch (error) {
    alert(error.message);
  }
});

async function loadAccounts() {
  try {
    state.accounts = await api("/api/accounts");
    const body = $("accounts-table").querySelector("tbody");
    body.innerHTML = state.accounts
      .map(
      (a) => `<tr>
          <td><input data-field="name" data-id="${a.id}" value="${escapeHtml(a.display_name)}"></td>
          <td><span class="badge ${a.state}">${a.state}</span></td>
          <td>${a.enabled ? "yes" : "no"}</td>
          <td><input data-field="order" data-id="${a.id}" type="number" value="${a.processing_order}"></td>
          <td>
            <button data-act="save" data-id="${a.id}">Save</button>
            <button data-act="toggle" data-id="${a.id}">${a.enabled ? "Deactivate" : "Activate"}</button>
            <button data-act="authenticate" data-id="${a.id}">Authenticate</button>
            <button data-act="resolve" data-id="${a.id}" ${a.state === "active" ? "disabled" : ""}>Resolve</button>
            <button data-act="delete" data-id="${a.id}" class="danger">Delete</button>
          </td>
        </tr>`
      )
      .join("");
  } catch (error) {
    alert(error.message);
  }
}

document.querySelector("#accounts-table").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-act]");
  if (!button) return;
  const id = Number(button.dataset.id);
  const act = button.dataset.act;
  try {
    if (act === "toggle") {
      const account = state.accounts.find((a) => a.id === id);
      await api(`/api/accounts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !account.enabled }),
      });
      loadAccounts();
    } else if (act === "save") {
      const name = document.querySelector(`[data-field="name"][data-id="${id}"]`).value.trim();
      const order = Number(document.querySelector(`[data-field="order"][data-id="${id}"]`).value);
      await api(`/api/accounts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ display_name: name, processing_order: order }),
      });
      loadAccounts();
    } else if (act === "authenticate") {
      await startAuth(id);
    } else if (act === "resolve") {
      await api(`/api/accounts/${id}/resolve-intervention`, { method: "POST" });
      loadAccounts();
    } else if (act === "delete") {
      if (confirm(`Permanently delete account #${id}? This cannot be undone.`)) {
        await api(`/api/accounts/${id}?confirm=true`, { method: "DELETE" });
        loadAccounts();
      }
    }
  } catch (error) {
    alert(error.message);
  }
});

async function startAuth(accountId) {
  try {
    const session = await api(`/api/accounts/${accountId}/authenticate`, { method: "POST" });
    state.authToken = session.token;
    $("auth-panel").hidden = false;
    if (session.screen_url) {
      $("auth-screen").src = session.screen_url;
    } else {
      $("auth-status").textContent = "remote screen unavailable";
    }
    pollAuth();
  } catch (error) {
    alert(error.message);
  }
}

async function pollAuth() {
  if (!state.authToken) return;
  try {
    const session = await api(`/api/auth/${state.authToken}`);
    $("auth-status").textContent = `status: ${session.status}`;
    if (session.status === "completed" || session.status === "failed") {
      loadAccounts();
      $("auth-screen").src = "";
      if (state.authPollTimer) {
        clearInterval(state.authPollTimer);
        state.authPollTimer = null;
      }
    } else if (!state.authPollTimer) {
      state.authPollTimer = setInterval(pollAuth, 2000);
    }
  } catch (error) {
    $("auth-status").textContent = error.message;
  }
}

$("auth-close").addEventListener("click", async () => {
  if (state.authToken) {
    await api(`/api/auth/${state.authToken}/revoke`, { method: "POST" }).catch(() => {});
    state.authToken = null;
  }
  if (state.authPollTimer) {
    clearInterval(state.authPollTimer);
    state.authPollTimer = null;
  }
  $("auth-panel").hidden = true;
  loadAccounts();
});

async function loadHistory() {
  try {
    const accounts = await api("/api/accounts");
    const select = $("history-account");
    select.innerHTML =
      '<option value="">All accounts</option>' +
      accounts.map((a) => `<option value="${a.id}">${escapeHtml(a.display_name)}</option>`).join("");
    await renderHistory();
  } catch (error) {
    alert(error.message);
  }
}

async function renderHistory() {
  const accountId = $("history-account").value;
  const status = $("history-status").value;
  const params = new URLSearchParams();
  if (accountId) params.set("account_id", accountId);
  if (status) params.set("status", status);
  const claims = await api(`/api/claims?${params.toString()}`);
  const accounts = state.accounts.length ? state.accounts : await api("/api/accounts");
  const byId = Object.fromEntries(accounts.map((a) => [a.id, a]));
  $("history-table").querySelector("tbody").innerHTML = claims
    .map(
      (c) =>
        `<tr><td>${escapeHtml((byId[c.account_id] || {}).display_name || c.account_id)}</td>
         <td>${escapeHtml(c.game_name || "")}</td>
         <td class="status-${c.status}">${c.status}</td>
         <td>${c.attempts}</td><td>${escapeHtml(c.updated_at || "")}</td></tr>`
    )
    .join("");
}

$("history-account").addEventListener("change", renderHistory);
$("history-status").addEventListener("change", renderHistory);

function exportUrl(format) {
  const params = new URLSearchParams({ format });
  if ($("history-account").value) params.set("account_id", $("history-account").value);
  if ($("history-status").value) params.set("status", $("history-status").value);
  return `/api/claims/export?${params.toString()}`;
}

$("export-csv").addEventListener("click", () => { window.location = exportUrl("csv"); });
$("export-json").addEventListener("click", () => { window.location = exportUrl("json"); });

async function loadSettings() {
  try {
    const settings = await api("/api/settings");
    $("settings-scheduler-enabled").value = String(settings.scheduler_enabled);
    $("settings-interval").value = settings.scheduler_interval_seconds;
    $("settings-delay-min").value = settings.claim_delay_min_seconds;
    $("settings-delay-max").value = settings.claim_delay_max_seconds;
    $("settings-telegram").value = String(settings.telegram_enabled);
  } catch (error) {
    alert(error.message);
  }
}

$("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    scheduler_enabled: $("settings-scheduler-enabled").value === "true",
    scheduler_interval_seconds: Number($("settings-interval").value),
    claim_delay_min_seconds: Number($("settings-delay-min").value),
    claim_delay_max_seconds: Number($("settings-delay-max").value),
    telegram_enabled: $("settings-telegram").value === "true",
  };
  try {
    await api("/api/settings", { method: "PATCH", body: JSON.stringify(body) });
    schedulerInfo();
    loadSettings();
  } catch (error) {
    alert(error.message);
  }
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

switchView("dashboard");
setInterval(() => {
  if (state.view === "dashboard") loadDashboard();
}, 15000);
