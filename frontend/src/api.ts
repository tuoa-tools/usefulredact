/** Types and calls for UsefulRedact's API (app/main.py). Field names follow the JSON exactly. */

export type Verdict =
  'FAIL_RECOVERABLE' | 'PI_VISIBLE' | 'REVIEW_LOW_CONFIDENCE' | 'NO_ISSUES_FOUND' | 'NOT_CHECKED';

export type Kind = 'recoverable' | 'pi' | 'context' | 'low_confidence';

/** x0, y0, x1, y1 in the page's own units (points for a PDF, pixels for an image). */
export type Box = [number, number, number, number];

export interface Health {
  status: 'ok';
  version: string;
  desktop: boolean;
  /** null while the model is still loading. */
  ocr: boolean | null;
  ocr_error: string | null;
  ner: boolean | null;
  ner_error: string | null;
  checking: number;
  quit_requested: boolean;
}

export interface DocumentSummary {
  id: string;
  name: string;
  status: 'queued' | 'checking' | 'done';
  page_done: number;
  page_total: number;
  verdict: Verdict | null;
  meaning: string | null;
  error: string;
  pages: number;
  counts: Record<Kind, number>;
}

export interface Session {
  watchlist: string;
  ignore: string;
  checking: number;
  documents: DocumentSummary[];
  skipped?: string[];
}

export interface PageInfo {
  number: number;
  width: number;
  height: number;
  source: 'text_layer' | 'ocr' | 'empty';
  ocr_mean_conf: number | null;
  ocr_regions: number;
  enhanced_pass: boolean;
}

export interface Finding {
  id: number;
  /** 1-based; 0 means the document itself (its metadata). */
  page: number;
  kind: Kind;
  detector: string;
  text: string;
  bbox: Box | null;
  boxes: Box[];
  source: string;
  detail: string;
  score: number | null;
  covered: boolean;
  /** Recovered text: the kinds of personal information found in it (detector ids). */
  holds: string[];
  /** Other detectors that matched the same words. */
  also: string[];
}

export interface DocumentDetail extends DocumentSummary {
  page_list?: PageInfo[];
  findings?: Finding[];
}

export type ExportKind = 'json' | 'findings' | 'documents';

const API_BASE = '';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** FastAPI puts a string in `detail` for our errors and a list of {msg} for validation errors. */
async function errorDetail(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    const detail = data.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((e: { msg?: string }) => e.msg ?? '')
        .filter(Boolean)
        .join('; ');
    }
  } catch {
    // not JSON - fall through
  }
  return `Request failed (${res.status})`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: 'same-origin',
    headers: body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : undefined,
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(await errorDetail(res), res.status);
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>('GET', '/api/health'),
  session: () => request<Session>('GET', '/api/session'),
  document: (id: string) => request<DocumentDetail>('GET', `/api/documents/${id}`),
  addFiles: (files: File[]) => {
    const form = new FormData();
    for (const file of files) form.append('files', file, file.name);
    return request<Session>('POST', '/api/documents', form);
  },
  setLists: (watchlist: string, ignore: string) =>
    request<Session>('PUT', '/api/lists', { watchlist, ignore }),
  remove: (id: string) => request<Session>('DELETE', `/api/documents/${id}`),
  clear: () => request<Session>('DELETE', '/api/documents'),
  quit: () => request<{ ok: boolean }>('POST', '/api/quit'),
};

export function pageImageUrl(id: string, page: number, annotations = true, width = 1400): string {
  const query = `width=${width}${annotations ? '' : '&annotations=false'}`;
  return `${API_BASE}/api/documents/${id}/pages/${page}/image?${query}`;
}

export function exportUrl(kind: ExportKind, docId?: string): string {
  return `${API_BASE}/api/export?kind=${kind}${docId ? `&doc_id=${docId}` : ''}`;
}
