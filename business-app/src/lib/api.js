import { getAccessToken } from "./supabase.js";

// In dev Vite fa proxy /api -> Flask (vite.config). In prod usa il meta api-base.
const META_BASE = document.querySelector('meta[name="api-base"]')?.content || "";
const isLocal = /^(localhost|127\.0\.0\.1)$/.test(location.hostname);
export const API_BASE = (isLocal ? "" : META_BASE).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export async function api(path, { method = "GET", body, auth = true, token } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const t = await getAccessToken();
    if (t) headers.Authorization = "Bearer " + t;
  }
  if (token) headers["X-Onboarding-Token"] = token; // per le rotte onboarding pubbliche
  const res = await fetch(API_BASE + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* no body */ }
  if (!res.ok) {
    const msg = (data && (data.description || data.error)) || `HTTP ${res.status}`;
    throw new ApiError(msg, res.status, data);
  }
  return data;
}
