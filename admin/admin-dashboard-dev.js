"use strict";

const API = "/admin/api";
let csrfToken = null;
let collectors = [];
let actionBusy = false;
let operationStorageReady = false;
let inspectionGeneration = 0;
const uncertainCollectors = new Set();
const uncertainOperations = new Map();
const OPERATION_STORAGE_KEY = "otb-admin-uncertain-operations-v1";

function saveUncertainOperations() {
  const records = [];

  for (const [key, operationId] of uncertainOperations) {
    const [chain, collector] = JSON.parse(key);
    records.push({chain, collector, operation_id: operationId});
  }

  localStorage.setItem(
    OPERATION_STORAGE_KEY,
    JSON.stringify(records)
  );
}

function loadUncertainOperations() {
  const raw = localStorage.getItem(OPERATION_STORAGE_KEY);

  if (raw === null) return;

  const records = JSON.parse(raw);

  if (!Array.isArray(records) || records.length > 1000) {
    throw new Error("Invalid saved operation records");
  }

  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

  for (const record of records) {
    if (
      !record || typeof record !== "object" ||
      Array.isArray(record) ||
      Object.keys(record).sort().join(",") !==
        "chain,collector,operation_id" ||
      typeof record.chain !== "string" ||
      typeof record.collector !== "string" ||
      record.chain.length < 1 || record.chain.length > 128 ||
      record.collector.length < 1 || record.collector.length > 128 ||
      !uuid.test(record.operation_id)
    ) {
      throw new Error("Invalid saved operation record");
    }
  }

  for (const record of records) {
    const key = collectorKey(record);
    if (uncertainOperations.has(key)) {
      throw new Error("Duplicate saved collector record");
    }
    uncertainCollectors.add(key);
    uncertainOperations.set(key, record.operation_id);
  }
}

function reserveOperation(item, operationId) {
  const key = collectorKey(item);

  uncertainCollectors.add(key);
  uncertainOperations.set(key, operationId);

  // Must complete before any HTTP request is submitted.
  saveUncertainOperations();
}

function confirmOperation(item) {
  const key = collectorKey(item);
  const operationId = uncertainOperations.get(key);

  uncertainCollectors.delete(key);
  uncertainOperations.delete(key);

  try {
    saveUncertainOperations();
  } catch (error) {
    // If persistence fails, retain the collector lock.
    uncertainCollectors.add(key);
    uncertainOperations.set(key, operationId);
    throw error;
  }
}

function collectorKey(item) {
  return JSON.stringify([item.chain, item.collector]);
}

function markCollectorUncertain(item, operationId) {
  const key = collectorKey(item);
  uncertainCollectors.add(key);
  uncertainOperations.set(key, operationId);
}

const element = id => document.getElementById(id);

function showLogin() {
  csrfToken = null;
  collectors = [];
  element("dashboard").hidden = true;
  element("login-panel").hidden = false;
  element("identity").textContent = "";
  element("password").value = "";
}

function showDashboard(username) {
  element("login-panel").hidden = true;
  element("dashboard").hidden = false;
  element("identity").textContent = username;
  element("error").textContent = "";
}

async function apiRequest(path, options = {}) {
  return fetch(API + path, {
    ...options,
    credentials: "same-origin",
    cache: "no-store"
  });
}

function cell(row, value) {
  const td = document.createElement("td");
  td.textContent = value == null ? "" : String(value);
  row.appendChild(td);
  return td;
}

const allowedActions = {
  pending: ["approve", "deny"],
  enabled: ["suspend", "revoke"],
  suspended: ["enable", "revoke"],
  revoked: []
};

function actionConfirmation(action, item) {
  const target = item.chain + " / " + item.collector;

  if (action === "revoke") {
    return confirm(
      "REVOKE collector " + target + "?\\n\\n" +
      "This removes its authorization and registration. " +
      "A new enrollment will be required to restore access."
    );
  }

  if (action === "deny") {
    return confirm(
      "DENY pending registration for " + target + "?"
    );
  }

  return confirm(
    action.toUpperCase() + " collector " + target + "?"
  );
}

function showActionError(message) {
  element("error").textContent = message;
  element("notice").textContent = "";
}

async function performCollectorAction(item, action) {
  if (actionBusy || !csrfToken) return;

  if (!operationStorageReady) {
    showActionError(
      "Operation storage unavailable. Administrator actions disabled."
    );
    return;
  }

  if (uncertainCollectors.has(collectorKey(item))) {
    showActionError(
      "VERIFICATION REQUIRED: Further actions on this collector " +
      "are locked because an earlier transaction result is uncertain."
    );
    return;
  }

  if (!(allowedActions[item.status] || []).includes(action)) {
    showActionError("This action is not valid for the collector status.");
    return;
  }

  if (!actionConfirmation(action, item)) return;

  if (!globalThis.crypto ||
      typeof globalThis.crypto.randomUUID !== "function") {
    showActionError(
      "Secure operation ID generation is unavailable. " +
      "No action was submitted."
    );
    return;
  }

  const operationId = globalThis.crypto.randomUUID();

  try {
    reserveOperation(item, operationId);
  } catch (error) {
    showActionError(
      "Cannot save operation ID. No action submitted. " +
      "Collector remains locked for verification."
    );
    renderCollectors();
    return;
  }

  actionBusy = true;
  element("error").textContent = "";
  element("notice").textContent = "Submitting collector action...";
  renderCollectors();

  const endpoint =
    action === "suspend" || action === "enable"
      ? "status" : action;

  const payload = {
    chain: item.chain,
    collector: item.collector,
    operation_id: operationId
  };

  if (endpoint === "status") {
    payload.enabled = action === "enable";
  }

  try {
    let response;

    try {
      response = await apiRequest(
        "/collectors/" + endpoint,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken
          },
          body: JSON.stringify(payload)
        }
      );
    } catch (networkError) {
      markCollectorUncertain(item, operationId);
      throw new Error(
        "CONNECTION LOST: The server may have completed this action. " +
        "Further actions on this collector are locked. " +
        "Verify the transaction before trying again."
      );
    }

    if (response.status === 401) {
      showLogin();
      throw new Error("Session expired. Please sign in again.");
    }

    if (response.status === 503) {
      let details = {};

      try {
        details = await response.json();
      } catch (_) {
        // Missing or malformed details remain uncertain.
      }

      if (
        details &&
        details.error === "Audit unavailable; action not started"
      ) {
        throw new Error(
          "AUDIT UNAVAILABLE: The action did not start. " +
          "No collector transaction was attempted."
        );
      }

      if (
        details &&
        typeof details.error === "string" &&
        details.error.startsWith(
          "Transaction result requires verification"
        )
      ) {
        markCollectorUncertain(item, operationId);
        throw new Error(
          "RESULT UNCERTAIN: The action may have completed. " +
          "Inspect the collector status and audit log. " +
          "Do not repeat the action automatically."
        );
      }

      markCollectorUncertain(item, operationId);
      throw new Error(
        "TRANSACTION UNAVAILABLE: The result may be uncertain. " +
        "Verify the collector status before attempting another action."
      );
    }

    if (response.status === 409) {
      let details = {};

      try {
        details = await response.json();
      } catch (_) {
        // An unreadable conflict response cannot be trusted.
      }

      if (!details || details.verification_required !== false) {
        markCollectorUncertain(item, operationId);
        throw new Error(
          "VERIFICATION REQUIRED: Operation " + operationId +
          " was not confirmed. Collector actions are locked."
        );
      }

      if (details.duplicate !== true ||
          details.error !== "Operation already completed") {
        markCollectorUncertain(item, operationId);
        throw new Error(
          "Unexpected conflict response. Verification required."
        );
      }

      confirmOperation(item);

      throw new Error(
        "Operation was already completed. " +
        "No automatic retry was attempted."
      );
    }

    if (!response.ok) {
      throw new Error(
        "Collector action failed (HTTP " + response.status + ")."
      );
    }

    const confirmed = await response.json();

    if (
      confirmed.status !== "success" ||
      !confirmed.collector ||
      confirmed.collector.chain !== item.chain ||
      confirmed.collector.collector !== item.collector ||
      confirmed.verification_required !== false
    ) {
      markCollectorUncertain(item, operationId);
      throw new Error(
        "Unexpected success response. Verification required."
      );
    }

    confirmOperation(item);

    element("notice").textContent =
      action.toUpperCase() + " completed for " +
      item.chain + " / " + item.collector + ".";

  } catch (error) {
    showActionError(error.message);
  } finally {
    actionBusy = false;

    if (!element("dashboard").hidden) {
      try {
        await refreshCollectors(false);
      } catch (error) {
        showActionError(error.message);
      }
    }
  }
}

async function inspectCollectorOperation(item) {
  const generation = ++inspectionGeneration;
  const operationId = uncertainOperations.get(collectorKey(item));
  const panel = element("operation-inspection");
  const details = element("operation-details");
  const audit = element("operation-audit");
  const error = element("operation-inspection-error");

  panel.hidden = false;
  details.replaceChildren();
  audit.replaceChildren();
  error.textContent = "";

  if (!operationId || !csrfToken) {
    error.textContent =
      "Operation ID or administrator session unavailable.";
    return;
  }

  try {
    const response = await apiRequest(
      "/operations/" + encodeURIComponent(operationId)
    );

    if (!response.ok) {
      throw new Error(
        "Inspection unavailable (HTTP " + response.status + ")."
      );
    }

    const evidence = await response.json();

    if (generation !== inspectionGeneration) return;

    if (
      !evidence ||
      typeof evidence !== "object" ||
      Array.isArray(evidence) ||
      evidence.operation_id !== operationId ||
      evidence.chain !== item.chain ||
      evidence.collector !== item.collector ||
      !["success", "unresolved", "rejected"].includes(
        evidence.ledger_state
      ) ||
      !Array.isArray(evidence.audit_events) ||
      typeof evidence.journal_present !== "boolean" ||
      typeof evidence.requires_manual_review !== "boolean" ||
      evidence.automatic_resolution !== false
    ) {
      throw new Error("Invalid operation inspection response.");
    }

    const assessment = evidence.assessment;

    const classifications = [
      "manual_review_required",
      "recovery_review_required",
      "consistency_review_required",
      "finalized_success_recorded",
      "finalized_rejection_recorded"
    ];

    const assessmentFields = [
      "classification", "reason", "ledger_state",
      "registration_consistent", "journal_present",
      "audit_outcomes", "requires_manual_review",
      "automatic_resolution", "collector_unlock_allowed"
    ];

    if (
      !assessment ||
      typeof assessment !== "object" ||
      Array.isArray(assessment) ||
      Object.keys(assessment).length !== assessmentFields.length ||
      !assessmentFields.every(
        key => Object.prototype.hasOwnProperty.call(assessment, key)
      ) ||
      !classifications.includes(assessment.classification) ||
      typeof assessment.reason !== "string" ||
      !assessment.reason.trim() ||
      assessment.ledger_state !== evidence.ledger_state ||
      assessment.journal_present !== evidence.journal_present ||
      assessment.requires_manual_review !==
        evidence.requires_manual_review ||
      assessment.automatic_resolution !== false ||
      assessment.collector_unlock_allowed !== false ||
      !(
        assessment.registration_consistent === true ||
        assessment.registration_consistent === false ||
        assessment.registration_consistent === null
      ) ||
      !Array.isArray(assessment.audit_outcomes)
    ) {
      throw new Error("Invalid reconciliation assessment.");
    }

    const consistent = assessment.registration_consistent;

    const expectedClassification = evidence.journal_present
      ? "recovery_review_required"
      : consistent === false
        ? "consistency_review_required"
        : evidence.ledger_state === "unresolved"
          ? "manual_review_required"
          : evidence.ledger_state === "success"
            ? "finalized_success_recorded"
            : "finalized_rejection_recorded";

    if (
      assessment.classification !== expectedClassification ||
      (consistent === null && !evidence.journal_present) ||
      assessment.requires_manual_review !== (
        evidence.journal_present ||
        consistent !== true ||
        evidence.ledger_state === "unresolved"
      ) ||
      assessment.audit_outcomes.length !==
        evidence.audit_events.length ||
      !assessment.audit_outcomes.every(
        (outcome, index) =>
          outcome === evidence.audit_events[index]?.outcome
      )
    ) {
      throw new Error("Conflicting reconciliation assessment.");
    }

    const fields = [
      ["Operation ID", evidence.operation_id],
      ["Administrator", evidence.administrator],
      ["Action", evidence.action],
      ["Blockchain", evidence.chain],
      ["Collector", evidence.collector],
      ["Ledger state", evidence.ledger_state],
      ["Assessment",
        assessment.classification.replace(/_/g, " ")],
      ["Assessment reason", assessment.reason],
      ["Registration consistency",
        consistent === null ? "Unknown" :
          consistent ? "Consistent" : "Inconsistent"],
      ["Collector unlocking", "Not permitted"],
      ["Collector status", evidence.collector_status],
      ["Last action", evidence.collector_last_action],
      ["Last updated", evidence.collector_updated_at],
      ["Transaction journal",
        evidence.journal_present ? "Present" : "Not present"],
      ["Manual review",
        evidence.requires_manual_review ? "Required" : "Not flagged"]
    ];

    for (const [name, value] of fields) {
      const label = document.createElement("dt");
      label.textContent = name;

      const entry = document.createElement("dd");
      entry.textContent = value == null ? "Unknown" : String(value);

      details.appendChild(label);
      details.appendChild(entry);
    }

    for (const event of evidence.audit_events) {
      if (
        !event ||
        typeof event.timestamp !== "string" ||
        !["attempt", "success", "rejected", "error"].includes(
          event.outcome
        )
      ) {
        throw new Error("Invalid audit evidence.");
      }

      const entry = document.createElement("li");
      entry.textContent = event.timestamp + " — " + event.outcome;
      audit.appendChild(entry);
    }

    if (evidence.audit_events.length === 0) {
      const entry = document.createElement("li");
      entry.textContent = "No matching audit events";
      audit.appendChild(entry);
    }

  } catch (failure) {
    if (generation !== inspectionGeneration) return;
    details.replaceChildren();
    audit.replaceChildren();
    error.textContent = failure.message;
  }
}

function addActionButtons(row, item) {
  const td = document.createElement("td");

  for (const action of allowedActions[item.status] || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent =
      action.charAt(0).toUpperCase() + action.slice(1);
    button.className = "secondary";
    button.disabled =
      actionBusy || uncertainCollectors.has(collectorKey(item));
    button.addEventListener("click", () => {
      performCollectorAction(item, action);
    });
    td.appendChild(button);
    td.appendChild(document.createTextNode(" "));
  }

  if (uncertainCollectors.has(collectorKey(item))) {
    const warning = document.createElement("span");
    warning.textContent = "Verification required";
    warning.className = "muted";
    td.appendChild(warning);

    if (uncertainOperations.has(collectorKey(item))) {
      const inspect = document.createElement("button");
      inspect.type = "button";
      inspect.textContent = "Inspect operation";
      inspect.className = "secondary";
      inspect.addEventListener("click", () => {
        inspectCollectorOperation(item);
      });
      td.appendChild(inspect);
    }
  }

  row.appendChild(td);
}

function renderCollectors() {
  const tbody = element("collector-rows");
  tbody.replaceChildren();

  const filter = element("chain-filter").value;
  const visible = collectors.filter(
    item => filter === "all" || item.chain === filter
  );

  element("count").textContent =
    visible.length + " collector(s)";

  for (const item of visible) {
    const row = document.createElement("tr");
    cell(row, item.chain);
    cell(row, item.collector);

    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    const allowed = ["enabled", "pending", "suspended", "revoked"];
    status.className = "status " +
      (allowed.includes(item.status) ? item.status : "");
    status.textContent = item.status;
    statusCell.appendChild(status);
    row.appendChild(statusCell);

    cell(row, item.last_action);
    cell(row, item.updated_at);
    addActionButtons(row, item);
    tbody.appendChild(row);
  }
}

async function refreshCollectors(showNotice = true) {
  const response = await apiRequest("/collectors");

  if (response.status === 401) {
    showLogin();
    throw new Error("Your session expired. Sign in again.");
  }

  if (!response.ok) {
    throw new Error("Unable to retrieve collector registrations.");
  }

  const data = await response.json();

  if (!Array.isArray(data.collectors)) {
    throw new Error("Invalid collector response.");
  }

  collectors = data.collectors;
  renderCollectors();
  if (showNotice) {
    element("notice").textContent = "Collector listing updated.";
  }
}

async function restoreSession() {
  const response = await apiRequest("/session");

  if (!response.ok) {
    showLogin();
    return;
  }

  const session = await response.json();
  csrfToken = session.csrf_token;
  showDashboard(session.username);
  await refreshCollectors();
}

element("login-form").addEventListener("submit", async event => {
  event.preventDefault();
  element("error").textContent = "";
  element("notice").textContent = "";

  const username = element("username").value;
  const password = element("password").value;

  try {
    const response = await apiRequest("/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username, password})
    });

    element("password").value = "";

    if (!response.ok) {
      throw new Error(
        response.status === 429
          ? "Too many login attempts. Try again later."
          : "Administrator login unsuccessful."
      );
    }

    await restoreSession();
  } catch (error) {
    element("error").textContent = error.message;
  }
});

element("refresh").addEventListener("click", async () => {
  try {
    await refreshCollectors();
  } catch (error) {
    element("error").textContent = error.message;
  }
});

element("chain-filter").addEventListener("change", renderCollectors);

element("close-inspection").addEventListener("click", () => {
  ++inspectionGeneration;
  element("operation-inspection").hidden = true;
  element("operation-details").replaceChildren();
  element("operation-audit").replaceChildren();
  element("operation-inspection-error").textContent = "";
});

element("logout").addEventListener("click", async () => {
  try {
    const response = await apiRequest("/logout", {
      method: "POST",
      headers: {"X-CSRF-Token": csrfToken || ""}
    });

    if (!response.ok && response.status !== 401) {
      throw new Error("Logout failed. Please retry.");
    }

    showLogin();
    element("notice").textContent = "Logged out.";
  } catch (error) {
    element("error").textContent = error.message;
  }
});

try {
  loadUncertainOperations();
  operationStorageReady = true;

  restoreSession().catch(error => {
    showLogin();
    element("error").textContent = error.message;
  });
} catch (error) {
  operationStorageReady = false;
  showLogin();
  element("error").textContent =
    "Saved operation records unavailable. " +
    "Administrator actions are disabled.";
}
