let BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

/** Where the backend lives. Used when the app is embedded as a module (for example "/statement-analyser"). */
export function setApiBase(base) {
  BASE = String(base || "").replace(/\/$/, "");
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function errorMessage(body, status) {
  if (!body) return `Request failed (${status})`;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    return body.detail
      .map((d) => `${(d.loc || []).slice(1).join(" › ")}: ${d.msg}`)
      .join("; ");
  }
  return `Request failed (${status})`;
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, options);
  } catch {
    throw new ApiError("Cannot reach the server. Is the backend running on port 8000?", 0);
  }
  if (res.status === 204) return null;
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) throw new ApiError(errorMessage(body, res.status), res.status);
  return body;
}

const sendJson = (method, path, body) =>
  request(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  health: () => request("/api/health"),
  extract: (file, signal) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/extract", { method: "POST", body: form, signal });
  },
  save: (payload) =>
    request("/api/statements", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  analyse: (file, password) => {
    const form = new FormData();
    form.append("file", file);
    if (password) form.append("password", password);
    return request("/api/analysis", { method: "POST", body: form });
  },
  savedAnalytics: (id) => request(`/api/statements/${id}/analytics`),
  checkStatement: (payload) => sendJson("POST", "/api/statements/check", payload),
  auditLog: (statementId) => request(`/api/audit${statementId ? `?statement_id=${statementId}` : ""}`),
  list: () => request("/api/statements"),
  get: (id) => request(`/api/statements/${id}`),
  remove: (id) => request(`/api/statements/${id}`, { method: "DELETE" }),
  // Merchant identification (derived data; never changes a statement)
  identifyMerchants: (descriptions) => sendJson("POST", "/api/merchants/identify", { descriptions }),
  listMerchantMappings: (q = "") => request(`/api/merchants/mappings${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  saveMerchantMapping: (payload) => sendJson("POST", "/api/merchants/mappings", payload),
  removeMerchantMapping: (id) => request(`/api/merchants/mappings/${id}`, { method: "DELETE" }),
  // Bank accounts and reconciliation (results are stored apart from the statements)
  listAccounts: () => request("/api/bank-accounts"),
  createAccount: (payload) => sendJson("POST", "/api/bank-accounts", payload),
  updateAccount: (id, changes) => sendJson("PUT", `/api/bank-accounts/${id}`, changes),
  listAssignments: () => request("/api/statement-accounts"),
  assignStatement: (statementId, accountId) => sendJson("PUT", `/api/statements/${statementId}/account`, { account_id: accountId }),
  createRecon: (payload) => sendJson("POST", "/api/reconciliations", payload),
  runRecon: (id) => request(`/api/reconciliations/${id}/run`, { method: "POST" }),
  listRecon: () => request("/api/reconciliations"),
  getRecon: (id) => request(`/api/reconciliations/${id}`),
  removeRecon: (id) => request(`/api/reconciliations/${id}`, { method: "DELETE" }),
  confirmMatch: (id, matchId) => sendJson("POST", `/api/reconciliations/${id}/matches/${matchId}/confirm`, {}),
  rejectMatch: (id, matchId) => sendJson("POST", `/api/reconciliations/${id}/matches/${matchId}/reject`, {}),
  consolidated: (id) => request(`/api/reconciliations/${id}/consolidated`),
  exportUrl: (id) => `${BASE}/api/reconciliations/${id}/export`,
  statementExportUrl: (id) => `${BASE}/api/statements/${id}/export.csv`,
};
