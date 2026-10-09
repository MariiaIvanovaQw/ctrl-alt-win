import { useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';

/**
 * Редактируемая копия загруженных данных (форма поверх ответа API).
 *
 * Когда источник меняется — пришёл первый ответ, данные перечитаны или
 * подменены после сохранения, — черновик заменяется его копией; правки
 * пользователя живут в черновике до следующей смены источника. Состояние
 * подстраивается во время рендера, а не в эффекте: так нет лишнего кадра
 * со старой формой и повторного рендера после него.
 */
export function useDraft<S, D>(
  source: S | null | undefined,
  toDraft: (source: S) => D,
  initial: D,
): [D, Dispatch<SetStateAction<D>>] {
  const [draft, setDraft] = useState<D>(() => (source != null ? toDraft(source) : initial));
  const [seen, setSeen] = useState(source);
  if (source !== seen) {
    setSeen(source);
    if (source != null) setDraft(toDraft(source));
  }
  return [draft, setDraft];
}
