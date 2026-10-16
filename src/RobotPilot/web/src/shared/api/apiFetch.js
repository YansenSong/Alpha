// Use the current origin. Vite proxies /api in development, while Flask serves
// the built UI and API from the same origin in deployment.
const API_BASE = "";
const credentials = "include";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

const STATUS_CODES = {
  401: "SESSION_EXPIRED",
  403: "PERMISSION_DENIED",
  409: "CONFLICT",
  412: "PRECONDITION_FAILED",
  429: "RATE_LIMITED",
  503: "ROBOT_UNAVAILABLE",
};

export class ApiError extends Error {
  constructor(
    message,
    { status = null, code = "NETWORK_ERROR", requestId = "", cause } = {},
  ) {
    super(message, { cause });
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

const responseError = async (response) => {
  let payload = {};
  try {
    payload = await response.clone().json();
  } catch {
    // The API may return an empty body or a proxy-generated text response.
  }
  const code = STATUS_CODES[response.status] || `HTTP_${response.status}`;
  const message =
    payload.message ||
    payload.description ||
    response.statusText ||
    "The robot API request failed.";
  const error = new ApiError(message, {
    status: response.status,
    code,
    requestId:
      payload.request_id ||
      response.headers.get("X-Request-Id") ||
      response.headers.get("X-Request-ID") ||
      "",
  });
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("robotpilot:auth-required"));
  }
  return error;
};

const fetchChecked = async (url, options) => {
  let response;
  try {
    response = await fetch(url, options);
  } catch (cause) {
    throw new ApiError("Robot API is offline or unreachable.", { cause });
  }
  if (!response.ok) throw await responseError(response);
  return response;
};

export async function apiFetch(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (!headers.has("X-Request-ID")) {
    const requestId =
      headers.get("Idempotency-Key") ||
      globalThis.crypto?.randomUUID?.() ||
      `robotpilot-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    headers.set("X-Request-ID", requestId);
  }
  if (!SAFE_METHODS.has(method)) {
    const response = await fetchChecked(`${API_BASE}/api/v1/auth/csrf`, {
      credentials,
      cache: "no-store",
    });
    const { csrf_token: csrfToken } = await response.json();
    if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  }
  return fetchChecked(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials,
  });
}
