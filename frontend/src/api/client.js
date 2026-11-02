const BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

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
  list: () => request("/api/statements"),
  get: (id) => request(`/api/statements/${id}`),
  remove: (id) => request(`/api/statements/${id}`, { method: "DELETE" }),
};
