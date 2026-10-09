import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError, api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction, useAsync } from '../../lib/useAsync';
import { useDraft } from '../../lib/useDraft';
import { clock, levelTitle } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorNote,
  Input,
  Loading,
  Modal,
} from '../../components/ui';
import { cx } from '../../lib/cx';
import AttemptResultView from './AttemptResult';
import type { Attempt, AttemptItem } from '../../api/types';

type AnswerValue = string | string[] | null;

const TYPE_LABEL: Record<string, string> = {
  theory: 'Теория',
  situational: 'Ситуация',
  practical: 'Практика',
};

/** Обратный отсчёт до `deadline_at`. По нулю попытку закрывает бэкенд. */
function Timer({ deadlineAt, onExpired }: { deadlineAt: string; onExpired: () => void }) {
  const deadline = useMemo(() => new Date(deadlineAt).getTime(), [deadlineAt]);
  const [left, setLeft] = useState(() => Math.max(0, (deadline - Date.now()) / 1000));
  const firedRef = useRef(false);

  useEffect(() => {
    const id = setInterval(() => {
      const next = Math.max(0, (deadline - Date.now()) / 1000);
      setLeft(next);
      if (next <= 0 && !firedRef.current) {
        firedRef.current = true;
        onExpired();
      }
    }, 1000);
    return () => clearInterval(id);
  }, [deadline, onExpired]);

  return (
    <div className={cx('timer', left < 300 && 'timer-warn')} role="timer" aria-live="off">
      {clock(left)}
      <span className="sr-only">осталось времени</span>
    </div>
  );
}

/** Поле ответа. Вид зависит от `validation_type` задания. */
function AnswerInput({
  item,
  value,
  onChange,
}: {
  item: AttemptItem;
  value: AnswerValue;
  onChange: (next: AnswerValue) => void;
}) {
  if (item.validation_type === 'single_choice') {
    return (
      <div className="optlist" role="radiogroup" aria-label="Варианты ответа">
        {(item.options ?? []).map((o) => (
          <label key={o.id} className={cx('opt', value === o.id && 'opt-on')}>
            <input
              type="radio"
              name={`q${item.position}`}
              checked={value === o.id}
              onChange={() => onChange(o.id)}
            />
            <span className="opt-id">{o.id}</span>
            <span>{o.text}</span>
          </label>
        ))}
      </div>
    );
  }

  if (item.validation_type === 'multiple_choice') {
    const picked = Array.isArray(value) ? value : [];
    return (
      <div className="optlist">
        <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
          Можно выбрать несколько вариантов
        </div>
        {(item.options ?? []).map((o) => (
          <label key={o.id} className={cx('opt', picked.includes(o.id) && 'opt-on')}>
            <input
              type="checkbox"
              checked={picked.includes(o.id)}
              onChange={(e) =>
                onChange(
                  e.target.checked ? [...picked, o.id].sort() : picked.filter((p) => p !== o.id),
                )
              }
            />
            <span className="opt-id">{o.id}</span>
            <span>{o.text}</span>
          </label>
        ))}
      </div>
    );
  }

  const isNumeric = item.validation_type === 'numeric';
  return (
    <div style={{ maxWidth: 320 }}>
      <Input
        type={isNumeric ? 'number' : 'text'}
        inputMode={isNumeric ? 'decimal' : 'text'}
        placeholder={isNumeric ? 'Число' : 'Ответ'}
        aria-label="Ответ"
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      />
    </div>
  );
}

/** Варианты экспресс-режима: чьими ответами заполнить оставшиеся задания. */
const AUTOFILL_AS = [
  { slug: 'junior', title: 'как Junior' },
  { slug: 'middle', title: 'как Middle' },
  { slug: 'senior', title: 'как Senior' },
  { slug: 'guesser', title: 'наугад' },
];

/**
 * Экспресс-режим для жюри (только демо-стенд): ответить на несколько заданий
 * самому, а остальные заполнить ответами синтетического кандидата и сразу
 * получить результат. Грейд считается по обычным правилам.
 */
function DemoAutofill({ attemptId, onDone }: { attemptId: string; onDone: (a: Attempt) => void }) {
  const fill = useAction(async (answerAs: string) => {
    await api.post(`/dev/me/attempts/${attemptId}/autofill`, { answer_as: answerAs });
    onDone(await api.get<Attempt>(`/candidate/assessment/attempts/${attemptId}`));
  });
  return (
    <Card
      title="Экспресс-режим для жюри"
      subtitle="Демо-стенд. Ответьте на несколько заданий сами, остальные заполнит синтетический кандидат выбранного уровня – результат и грейд по обычным правилам за пару минут. Ваши ответы не меняются"
    >
      <div className="row-wrap">
        {AUTOFILL_AS.map((o) => (
          <Button key={o.slug} size="sm" busy={fill.busy} onClick={() => void fill.run(o.slug)}>
            Дозаполнить {o.title} и завершить
          </Button>
        ))}
      </div>
      <ErrorNote error={fill.error} />
    </Card>
  );
}

type Signal = 'focus_lost' | 'copy' | 'paste';

/**
 * Лёгкий прокторинг: уход со вкладки и копирование текста заданий
 * отправляются на сервер как сигналы. Они становятся признаками для
 * разбора в результате и карточке; грейд от них не зависит.
 */
function useProctoring(attemptId: string | undefined, active: boolean) {
  useEffect(() => {
    if (!attemptId || !active) return;
    const send = (kind: Signal) => {
      void api.post(`/candidate/assessment/attempts/${attemptId}/signals`, { kind }).catch(() => undefined);
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') send('focus_lost');
    };
    const onCopy = () => send('copy');
    const onPaste = () => send('paste');
    document.addEventListener('visibilitychange', onVisibility);
    document.addEventListener('copy', onCopy);
    document.addEventListener('paste', onPaste);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      document.removeEventListener('copy', onCopy);
      document.removeEventListener('paste', onPaste);
    };
  }, [attemptId, active]);
}

function restoreAnswers(attempt: Attempt): Record<number, AnswerValue> {
  const restored: Record<number, AnswerValue> = {};
  for (const [pos, value] of Object.entries(attempt.answers ?? {})) {
    restored[Number(pos)] = value as AnswerValue;
  }
  return restored;
}

export default function AttemptPage() {
  const { id } = useParams<{ id: string }>();
  const { ref } = useReference();

  const { data, loading, error, set, reload } = useAsync(
    () => api.get<Attempt>(`/candidate/assessment/attempts/${id}`),
    [id],
  );

  const [current, setCurrent] = useState(0);
  // Ответы с сервера — исходное состояние: попытка переживает перезагрузку.
  const [answers, setAnswers] = useDraft(data, restoreAnswers, {});
  const [confirming, setConfirming] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);
  const [expired, setExpired] = useState(false);

  useProctoring(data?.id, data?.status === 'in_progress');

  /** Автосохранение: каждый ответ уходит на сервер сразу. */
  const saveAnswer = useCallback(
    async (position: number, value: AnswerValue) => {
      setAnswers((prev) => ({ ...prev, [position]: value }));
      setSaveError(null);
      try {
        await api.put(`/candidate/assessment/attempts/${id}/answers/${position}`, { value });
      } catch (e) {
        if (e instanceof ApiError) {
          // Время вышло — бэкенд уже закрыл попытку, показываем результат.
          if (e.code === 'attempt_expired') {
            setExpired(true);
            reload();
            return;
          }
          setSaveError(e);
        }
      }
    },
    [id, reload, setAnswers],
  );

  const finish = useAction(async () => {
    const finished = await api.post<Attempt>(`/candidate/assessment/attempts/${id}/finish`);
    set(finished);
    setConfirming(false);
  });

  const onExpired = useCallback(() => {
    setExpired(true);
    reload();
  }, [reload]);

  if (loading) return <Loading rows={5} />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  // Попытка завершена — показываем разбор вместо заданий.
  if (data.status !== 'in_progress' && data.result) {
    return (
      <div className="stack">
        {expired && <Alert tone="warn">Время вышло. Попытка завершена с теми ответами, что были</Alert>}
        <AttemptResultView result={data.result} declaredLevel={data.declared_level} />
        <div className="row">
          <Link className="btn btn-primary" to="/candidate/assessment">
            К категории и тестам
          </Link>
          <Link className="btn btn-ghost" to="/candidate">
            В кабинет
          </Link>
        </div>
      </div>
    );
  }

  const item = data.items[current];
  const answeredCount = data.items.filter((i) => {
    const v = answers[i.position];
    return v !== null && v !== undefined && v !== '' && (!Array.isArray(v) || v.length > 0);
  }).length;
  const unanswered = data.items.length - answeredCount;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
        <div className="stack-sm">
          <h1 className="page-title">Тест {levelTitle(data.declared_level)}</h1>
          <div className="row-wrap muted" style={{ fontSize: 'var(--text-sm)' }}>
            <span>
              Отвечено {answeredCount} из {data.items.length}
            </span>
            <span className="faint mono" style={{ fontSize: 'var(--text-xs)' }}>
              {data.test_label}
            </span>
          </div>
        </div>
        <Timer deadlineAt={data.deadline_at} onExpired={onExpired} />
      </div>

      <p className="faint" style={{ fontSize: 'var(--text-xs)' }}>
        Во время теста фиксируются уход со вкладки и копирование или вставка текста. На грейд это
        не влияет, но работодатель увидит отметку рядом с результатом
      </p>

      {saveError && (
        <Alert tone="danger" title="Ответ не сохранился">
          {saveError.message} Проверьте связь и выберите вариант ещё раз
        </Alert>
      )}

      <Card>
        <div className="qgrid">
          {data.items.map((i, idx) => {
            const v = answers[i.position];
            const done = v !== null && v !== undefined && v !== '' && (!Array.isArray(v) || v.length > 0);
            return (
              <button
                key={i.position}
                type="button"
                className={cx('qbtn', done && 'qbtn-done', idx === current && 'qbtn-on')}
                aria-label={`Задание ${idx + 1}${done ? ', отвечено' : ', без ответа'}`}
                aria-current={idx === current}
                onClick={() => setCurrent(idx)}
              >
                {idx + 1}
              </button>
            );
          })}
        </div>
      </Card>

      {item && (
        <Card>
          <div className="row-wrap" style={{ marginBottom: 'var(--sp-4)' }}>
            <Badge tone="accent">Задание {current + 1}</Badge>
            <Badge tone="neutral">{TYPE_LABEL[item.type] ?? item.type}</Badge>
          </div>

          <p style={{ fontSize: 'var(--text-md)', whiteSpace: 'pre-line' }}>{item.question}</p>

          {item.code && (
            <div style={{ marginTop: 'var(--sp-4)' }}>
              {item.language && <span className="code-lang">{item.language}</span>}
              <pre className="code">
                <code>{item.code}</code>
              </pre>
            </div>
          )}

          <div style={{ marginTop: 'var(--sp-5)' }}>
            <AnswerInput
              item={item}
              value={answers[item.position] ?? null}
              onChange={(v) => void saveAnswer(item.position, v)}
            />
          </div>

          <div className="divider" style={{ margin: 'var(--sp-5) 0 var(--sp-4)' }} />

          <div className="row" style={{ justifyContent: 'space-between' }}>
            <Button disabled={current === 0} onClick={() => setCurrent((c) => c - 1)}>
              ← Назад
            </Button>

            <Button variant="ghost" onClick={() => void saveAnswer(item.position, null)}>
              Очистить ответ
            </Button>

            {current < data.items.length - 1 ? (
              <Button variant="primary" onClick={() => setCurrent((c) => c + 1)}>
                Дальше →
              </Button>
            ) : (
              <Button variant="primary" onClick={() => setConfirming(true)}>
                Завершить тест
              </Button>
            )}
          </div>
        </Card>
      )}

      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <Button onClick={() => setConfirming(true)}>Завершить тест</Button>
      </div>

      {ref?.demo_mode && <DemoAutofill attemptId={data.id} onDone={set} />}

      {confirming && (
        <Modal
          title="Завершить тест?"
          onClose={() => setConfirming(false)}
          footer={
            <>
              <Button onClick={() => setConfirming(false)}>Вернуться к заданиям</Button>
              <Button variant="primary" busy={finish.busy} onClick={() => void finish.run()}>
                Завершить
              </Button>
            </>
          }
        >
          <div className="stack">
            {unanswered > 0 ? (
              <Alert tone="warn">
                Без ответа осталось заданий: {unanswered}. Они будут засчитаны как неверные
              </Alert>
            ) : (
              <Alert tone="success">Все задания отвечены</Alert>
            )}
            <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
              После завершения вернуться к заданиям нельзя. Результат и категория появятся сразу
            </p>
            <ErrorNote error={finish.error} />
          </div>
        </Modal>
      )}
    </div>
  );
}
