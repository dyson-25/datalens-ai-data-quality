const SESSION_KEY = 'datalens.session';
let session = null;
try {
  const saved = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null');
  if (saved?.dataset_id && saved?.token) session = saved;
} catch { /* Storage may be unavailable in private browser contexts. */ }

export class ApiError extends Error {
  constructor(message, status = 0, code = '') { super(message); this.status = status; this.code = code; }
}
export const getSession = () => session;
export function setSession(value) {
  session = value;
  if (value) sessionStorage.setItem(SESSION_KEY, JSON.stringify(value));
  else sessionStorage.removeItem(SESSION_KEY);
}
export const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
export async function api(path, { method = 'GET', body, blob = false, attachment = false, signal } = {}) {
  for (let attempt = 0; attempt < 5; attempt++) {
    const headers = { Accept: blob || attachment ? '*/*' : 'application/json' };
    if (session?.token) headers['X-Session-Token'] = session.token;
    if (body !== undefined && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
    let response;
    try {
      response = await fetch(`/api/v1${path}`, {
        method, headers, body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
        credentials: 'same-origin', cache: 'no-store', signal
      });
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new ApiError('The local API could not be reached. Check the server connection and retry.');
    }
    if (response.status === 429 && attempt < 4) {
      await delay(Math.min(2500, 400 * 2 ** attempt));
      continue;
    }
    if (!response.ok) {
      let payload;
      try { payload = await response.json(); } catch { /* Non-JSON errors still receive a useful status message. */ }
      throw new ApiError(payload?.error?.message || (typeof payload?.detail === 'string' ? payload.detail : `Request failed (${response.status}). Please review your inputs and try again.`), response.status, payload?.error?.code);
    }
    if (attachment) {
      const disposition = response.headers.get('Content-Disposition') || '';
      let filename = disposition.match(/filename="([^"]+)"/i)?.[1];
      const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
      if (encoded) { try { filename = decodeURIComponent(encoded); } catch { /* Fall back to the plain filename. */ } }
      return { blob: await response.blob(), filename };
    }
    if (blob) return response.blob();
    if (response.status === 204) return null;
    return response.json();
  }
}
export function datasetPath(suffix = '') {
  if (!session?.dataset_id) throw new ApiError('Upload a dataset to begin.');
  return `/datasets/${encodeURIComponent(session.dataset_id)}${suffix}`;
}
export const datasetApi = (suffix = '', options) => api(datasetPath(suffix), options);
