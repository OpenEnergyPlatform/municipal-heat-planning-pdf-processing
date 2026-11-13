/* The only way the page talks to its server: relative URLs, JSON, and on every POST the two headers the server asks for
   (server.py refuses a POST without them). The body is JSON.stringify of what the caller hands in, nothing added. */
import { isObj } from './util';
import { t } from './i18n';

const POST_HEADERS = { 'Content-Type': 'application/json', 'X-Docpipe-Edit': '1' };

function errText(e: unknown): string {
  if (!e) return t('unknown error');
  if (typeof e === 'string') return e;
  const o = e as { message?: string; where?: string };
  return (o.message || t('error')) + (o.where ? ' (' + o.where + ')' : '');
}

async function send(method: 'GET' | 'POST', url: string, body?: unknown): Promise<{ res: Response; j: any }> {
  const opts: RequestInit = { method };
  if (method === 'POST') {
    opts.headers = POST_HEADERS;
    opts.body = JSON.stringify(body == null ? {} : body);
  }
  let res: Response;
  try { res = await fetch(url, opts); }
  catch (e) { throw new Error(t('The server cannot be reached: {reason}', { reason: (e as Error).message })); }
  let j: any;
  try { j = await res.json(); }
  catch { throw new Error(t('The server answered {status} without JSON.', { status: String(res.status) })); }
  return { res, j };
}

/* An answer with "error" is thrown as its sentence; a 4xx/5xx without "saved" or "ok" too. */
export async function api<T = any>(method: 'GET' | 'POST', url: string, body?: unknown): Promise<T> {
  const { res, j } = await send(method, url, body);
  if (isObj(j) && typeof j.error === 'string') throw new Error(j.error);
  if (!res.ok && !(isObj(j) && ('saved' in j || 'ok' in j))) throw new Error(errText(j && j.error) || t('The server answered {status}.', { status: String(res.status) }));
  return j as T;
}

/* Like api() for a POST, but an answer that carries "ok" or "saved" is a report even when it holds an error sentence. */
export async function apiR<T = any>(url: string, body?: unknown): Promise<T> {
  const { res, j } = await send('POST', url, body);
  if (isObj(j) && ('ok' in j || 'saved' in j)) return j as T;
  if (isObj(j) && typeof j.error === 'string') throw new Error(j.error);
  if (!res.ok) throw new Error(t('The server answered {status}.', { status: String(res.status) }));
  return j as T;
}

export const get = <T = any>(url: string) => api<T>('GET', url);
export const post = <T = any>(url: string, body?: unknown) => api<T>('POST', url, body);
export { errText };
