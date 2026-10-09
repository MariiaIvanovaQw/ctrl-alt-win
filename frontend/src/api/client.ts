/**
 * HTTP-клиент платформы.
 *
 * Отвечает за три вещи, которые иначе пришлось бы повторять на каждом экране:
 * хранение пары токенов, единый формат ошибок и обновление access-токена.
 *
 * Обновление намеренно сделано «одним запросом на всё приложение»: бэкенд
 * считает повторное использование refresh-токена кражей сессии и гасит её
 * целиком (`401 refresh_token_reused`). Поэтому параллельные запросы ждут
 * один общий промис, а вкладки договариваются между собой через
 * BroadcastChannel.
 */

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000';
export const API_V1 = `${API_BASE}/api/v1`;

const STORE_KEY = 'fsp.tokens';
const CHANNEL = 'fsp.auth';

export type Tokens = {
  access_token: string;
  refresh_token: string;
  /** Отметка времени (мс), когда access-токен истекает. */
  expires_at: number;
};

export type ApiErrorBody = {
  code: string;
  message: string;
  details?: { fields?: { field: string; message: string }[] } & Record<string, unknown>;
};

/** Ошибка API в едином формате бэкенда. `message` готов к показу пользователю. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: ApiErrorBody['details'];

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.details = body.details;
  }

  /** Ошибки валидации по полям формы — для подсветки конкретных инпутов. */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const f of this.details?.fields ?? []) out[f.field] = f.message;
    return out;
  }
}

// ---------------------------------------------------------------- хранилище

let tokens: Tokens | null = readStored();
const listeners = new Set<(t: Tokens | null) => void>();

function readStored(): Tokens | null {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

const channel: BroadcastChannel | null =
  typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel(CHANNEL) : null;

/** Применить токены, пришедшие из другой вкладки, без повторной рассылки. */
channel?.addEventListener('message', (e: MessageEvent<Tokens | null>) => {
  tokens = e.data;
  listeners.forEach((l) => l(tokens));
});

export function getTokens(): Tokens | null {
  return tokens;
}

export function onTokensChange(fn: (t: Tokens | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function saveTokens(raw: {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}): Tokens {
  const next: Tokens = {
    access_token: raw.access_token,
    refresh_token: raw.refresh_token,
    // 15 секунд запаса, чтобы не отправлять заведомо протухший токен
    expires_at: Date.now() + (raw.expires_in - 15) * 1000,
  };
  tokens = next;
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(next));
  } catch {
    /* приватный режим браузера — работаем в памяти */
  }
  channel?.postMessage(next);
  listeners.forEach((l) => l(next));
  return next;
}

export function clearTokens(): void {
  tokens = null;
  try {
    localStorage.removeItem(STORE_KEY);
  } catch {
    /* см. выше */
  }
  channel?.postMessage(null);
  listeners.forEach((l) => l(null));
}

// ------------------------------------------------------------- обновление

let refreshing: Promise<string> | null = null;

/**
 * Обновляет пару токенов. Все одновременные вызовы вкладки ждут один общий
 * запрос, а вкладки между собой — блокировку `navigator.locks`: иначе две
 * вкладки предъявили бы один и тот же refresh-токен, и бэкенд погасил бы
 * всю сессию как украденную.
 */
function refreshAccessToken(): Promise<string> {
  if (refreshing) return refreshing;

  const before = tokens?.refresh_token;
  if (!before) return Promise.reject(new Error('no refresh token'));

  const run = async (): Promise<string> => {
    // пока ждали блокировку, другая вкладка могла уже обновить пару
    const stored = readStored();
    if (stored && stored.refresh_token !== before && stored.expires_at > Date.now()) {
      tokens = stored;
      listeners.forEach((l) => l(stored));
      return stored.access_token;
    }
    const r = await fetch(`${API_V1}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: before }),
    });
    if (!r.ok) {
      clearTokens();
      throw new ApiError(r.status, {
        code: 'session_expired',
        message: 'Сессия истекла, войдите заново',
      });
    }
    return saveTokens(await r.json()).access_token;
  };

  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  // .then разворачивает Promise<Promise<string>>, который возвращает request с асинхронным колбэком
  const pending: Promise<string> = locks ? locks.request('fsp.auth.refresh', run).then((token) => token) : run();
  const shared = pending.finally(() => {
    refreshing = null;
  });
  refreshing = shared;
  return shared;
}

/** Действующий access-токен; при необходимости обновляет его заранее. */
async function freshAccessToken(): Promise<string | null> {
  if (!tokens) return null;
  if (Date.now() < tokens.expires_at) return tokens.access_token;
  try {
    return await refreshAccessToken();
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ запрос

type Options = {
  method?: string;
  body?: unknown;
  /** Запрос без токена — для публичных методов и входа. */
  anonymous?: boolean;
  query?: Record<string, string | number | boolean | string[] | undefined | null>;
  signal?: AbortSignal;
};

function buildUrl(path: string, query?: Options['query']): string {
  const url = new URL(API_V1 + path);
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) v.forEach((item) => url.searchParams.append(k, String(item)));
    else url.searchParams.set(k, String(v));
  }
  return url.toString();
}

async function toApiError(res: Response): Promise<ApiError> {
  let body: ApiErrorBody = { code: `http_${res.status}`, message: `Ошибка ${res.status}` };
  try {
    const json = await res.json();
    if (json?.error?.code) body = json.error as ApiErrorBody;
    else if (typeof json?.detail === 'string') body = { code: 'error', message: json.detail };
  } catch {
    /* тело не JSON — остаётся заглушка выше */
  }
  return new ApiError(res.status, body);
}

async function send(path: string, opts: Options, retry = true): Promise<Response> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';

  if (!opts.anonymous) {
    const token = await freshAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(buildUrl(path, opts.query), {
    method: opts.method ?? 'GET',
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: opts.signal,
  });

  // Токен мог протухнуть между проверкой и доставкой запроса — один повтор.
  if (res.status === 401 && retry && !opts.anonymous && tokens) {
    const err = await toApiError(res.clone());
    if (err.code === 'token_expired' || err.code === 'invalid_token') {
      try {
        await refreshAccessToken();
        return send(path, opts, false);
      } catch {
        clearTokens();
      }
    }
  }

  return res;
}

export async function request<T>(path: string, opts: Options = {}): Promise<T> {
  const res = await send(path, opts);
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Options['query'], signal?: AbortSignal) =>
    request<T>(path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Options['query']) =>
    request<T>(path, { method: 'POST', body: body ?? {}, query }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body: body ?? {} }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ?? {} }),
  del: <T>(path: string, body?: unknown) => request<T>(path, { method: 'DELETE', body }),
  /** Публичные методы и вход — без заголовка Authorization. */
  anon: {
    get: <T>(path: string, query?: Options['query']) => request<T>(path, { query, anonymous: true }),
    post: <T>(path: string, body?: unknown) =>
      request<T>(path, { method: 'POST', body: body ?? {}, anonymous: true }),
  },
};

// ------------------------------------------------------------------- файлы

/** Загрузка файла формой (`multipart/form-data`), например PDF-резюме. */
export async function upload<T>(path: string, file: File, field = 'file'): Promise<T> {
  const form = new FormData();
  form.append(field, file);

  const token = await freshAccessToken();
  const res = await fetch(buildUrl(path), {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

/** Скачивание бинарного ответа: имя файла берём из Content-Disposition. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const res = await send(path, {});
  if (!res.ok) throw await toApiError(res);

  // Content-Disposition не входит в список заголовков, доступных кросс-доменному
  // fetch по умолчанию, поэтому на практике чаще срабатывает запасное имя.
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  const name = utf8 ? decodeURIComponent(utf8[1]) : (plain?.[1] ?? fallbackName);

  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Сохранение произвольных данных как файла — выгрузка профиля, JSON Resume. */
export function saveJson(data: unknown, name: string): void {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
  );
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
