import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';

export type AsyncState<T> = {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  /** Перечитать данные, например после изменения на экране. */
  reload: () => void;
  /** Локально подменить данные без похода на сервер. */
  set: (next: T) => void;
};

/**
 * Ссылка на последнюю версию значения для эффектов и обработчиков событий.
 * Обновляется после отрисовки, а не во время неё: рендер остаётся чистым.
 */
function useLatest<T>(value: T) {
  const ref = useRef(value);
  useLayoutEffect(() => {
    ref.current = value;
  });
  return ref;
}

/**
 * Загрузка данных экрана. Намеренно простая замена react-query: держим
 * состояние загрузки, ошибку в формате API и игнорируем ответы, пришедшие
 * после размонтирования или после более свежего запроса.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  // Срабатывание счётчика отсекает ответы устаревших запросов.
  const runId = useRef(0);
  const fnRef = useLatest(fn);

  useEffect(() => {
    const id = ++runId.current;
    let alive = true;
    setLoading(true);
    setError(undefined);

    fnRef
      .current()
      .then((result) => {
        if (!alive || id !== runId.current) return;
        setData(result);
      })
      .catch((e: unknown) => {
        if (!alive || id !== runId.current) return;
        setError(
          e instanceof ApiError
            ? e
            : new ApiError(0, { code: 'network_error', message: 'Нет связи с сервером' }),
        );
      })
      .finally(() => {
        if (!alive || id !== runId.current) return;
        setLoading(false);
      });

    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const set = useCallback((next: T) => setData(next), []);

  return { data, error, loading, reload, set };
}

/**
 * Обёртка над действием пользователя (отправка формы, кнопка).
 * Хранит флаг выполнения и ошибку, чтобы не писать это в каждом компоненте.
 */
export function useAction<Args extends unknown[], R>(
  fn: (...args: Args) => Promise<R>,
): {
  run: (...args: Args) => Promise<R | undefined>;
  busy: boolean;
  error: ApiError | undefined;
  reset: () => void;
} {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const fnRef = useLatest(fn);

  const run = useCallback(async (...args: Args) => {
    setBusy(true);
    setError(undefined);
    try {
      return await fnRef.current(...args);
    } catch (e: unknown) {
      // ошибка кода (не ответ сервера) не должна теряться за «нет связи»
      if (!(e instanceof ApiError) && !(e instanceof TypeError && /fetch/i.test(e.message))) console.error(e);
      setError(
        e instanceof ApiError
          ? e
          : new ApiError(0, { code: 'network_error', message: 'Нет связи с сервером' }),
      );
      return undefined;
    } finally {
      setBusy(false);
    }
  }, [fnRef]);

  const reset = useCallback(() => setError(undefined), []);

  return { run, busy, error, reset };
}
