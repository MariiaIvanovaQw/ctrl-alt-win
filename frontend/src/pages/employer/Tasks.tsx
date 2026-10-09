import { useState } from 'react';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction, useAsync } from '../../lib/useAsync';
import { dateTime, levelTitle, taskAnswer } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
  Select,
  Textarea,
} from '../../components/ui';
import type { EmployerTask, Level, TaskAnswer } from '../../api/types';

type Submission = {
  assignment_id: string;
  candidate_id: string;
  candidate_name: string;
  status: string;
  answer: TaskAnswer | null;
  submitted_at: string | null;
  auto_correct: boolean | null;
  employer_score: number | null;
  employer_comment: string | null;
  /** Антиплагиат: самый похожий ответ другого кандидата на это задание. */
  similar_to?: { candidate_id: string; share: number } | null;
};

const KIND_TITLE: Record<string, string> = {
  choice: 'Выбор варианта',
  numeric: 'Числовой ответ',
  approach: 'Предложите подход',
};

/** Создание короткого задания трёх видов. */
function TaskModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { ref } = useReference();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [kind, setKind] = useState<'choice' | 'numeric' | 'approach'>('approach');
  const [specialization, setSpecialization] = useState('backend');
  const [levelMin, setLevelMin] = useState<Level>('junior');
  const [levelMax, setLevelMax] = useState<Level>('senior');
  const [options, setOptions] = useState<{ id: string; text: string }[]>([
    { id: 'A', text: '' },
    { id: 'B', text: '' },
  ]);
  const [correctOption, setCorrectOption] = useState('A');
  const [correctNumber, setCorrectNumber] = useState('');
  const [tolerance, setTolerance] = useState('');

  const save = useAction(async () => {
    await api.post('/employer/tasks', {
      title,
      body,
      kind,
      specialization,
      level_min: levelMin,
      level_max: levelMax,
      options: kind === 'choice' ? options.filter((o) => o.text.trim()) : null,
      correct_option: kind === 'choice' ? correctOption : null,
      correct_number: kind === 'numeric' && correctNumber !== '' ? Number(correctNumber) : null,
      tolerance: kind === 'numeric' && tolerance !== '' ? Number(tolerance) : null,
    });
    onDone();
  });

  const ready = title && body && (kind !== 'numeric' || correctNumber !== '');

  return (
    <Modal
      title="Новое регулярное задание"
      onClose={onClose}
      wide
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" busy={save.busy} disabled={!ready} onClick={() => void save.run()}>
            Создать
          </Button>
        </>
      }
    >
      <div className="stack">
        <Field label="Заголовок" required>
          {(p) => <Input {...p} value={title} onChange={(e) => setTitle(e.target.value)} />}
        </Field>

        <Field label="Условие" required>
          {(p) => (
            <Textarea
              {...p}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Шлюз оплаты не ответил за 10 секунд. Как безопасно повторить операцию?"
            />
          )}
        </Field>

        <div className="grid-3">
          <Field label="Тип ответа" required>
            {(p) => (
              <Select
                {...p}
                value={kind}
                onChange={(e) => setKind(e.target.value as typeof kind)}
              >
                <option value="approach">Предложите подход (текст)</option>
                <option value="choice">Выбор варианта</option>
                <option value="numeric">Числовой ответ</option>
              </Select>
            )}
          </Field>
          <Field label="Кому показывать: от" required>
            {(p) => (
              <Select {...p} value={levelMin} onChange={(e) => setLevelMin(e.target.value as Level)}>
                {ref?.levels.map((l) => (
                  <option key={l.slug} value={l.slug}>
                    {levelTitle(l.slug)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="до" required>
            {(p) => (
              <Select {...p} value={levelMax} onChange={(e) => setLevelMax(e.target.value as Level)}>
                {ref?.levels.map((l) => (
                  <option key={l.slug} value={l.slug}>
                    {levelTitle(l.slug)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>

        <Field label="Специализация" required>
          {(p) => (
            <Select
              {...p}
              value={specialization}
              onChange={(e) => setSpecialization(e.target.value)}
            >
              {ref?.specializations.map((s) => (
                <option key={s.slug} value={s.slug}>
                  {s.title}
                </option>
              ))}
            </Select>
          )}
        </Field>

        {kind === 'choice' && (
          <Card title="Варианты ответа">
            <div className="stack-sm">
              {options.map((o, i) => (
                <div key={o.id} className="row">
                  <span className="opt-id">{o.id}</span>
                  <Input
                    value={o.text}
                    aria-label={`Вариант ${o.id}`}
                    onChange={(e) =>
                      setOptions((prev) =>
                        prev.map((x, xi) => (xi === i ? { ...x, text: e.target.value } : x)),
                      )
                    }
                  />
                </div>
              ))}
              <div className="row">
                <Button
                  size="sm"
                  onClick={() =>
                    setOptions((prev) => [
                      ...prev,
                      { id: String.fromCharCode(65 + prev.length), text: '' },
                    ])
                  }
                  disabled={options.length >= 6}
                >
                  Добавить вариант
                </Button>
              </div>
              <Field label="Правильный вариант">
                {(p) => (
                  <Select
                    {...p}
                    value={correctOption}
                    onChange={(e) => setCorrectOption(e.target.value)}
                  >
                    {options.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.id}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
          </Card>
        )}

        {kind === 'numeric' && (
          <div className="grid-2">
            <Field label="Правильный ответ" required>
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  value={correctNumber}
                  onChange={(e) => setCorrectNumber(e.target.value)}
                />
              )}
            </Field>
            <Field label="Допуск" hint="На сколько ответ может отличаться">
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  value={tolerance}
                  onChange={(e) => setTolerance(e.target.value)}
                />
              )}
            </Field>
          </div>
        )}

        <ErrorNote error={save.error} />
      </div>
    </Modal>
  );
}

/** Решения кандидатов и оценка свободных ответов. */
function Submissions({ taskId, onReviewed }: { taskId: string; onReviewed: () => void }) {
  const { data, loading, error, reload } = useAsync(
    () => api.get<{ task: { kind: string }; submissions: Submission[] }>(
      `/employer/tasks/${taskId}/submissions`,
    ),
    [taskId],
  );
  const [scoring, setScoring] = useState<Submission | null>(null);
  const [score, setScore] = useState('4');
  const [comment, setComment] = useState('');

  const review = useAction(async () => {
    if (!scoring) return;
    await api.post(`/employer/tasks/submissions/${scoring.assignment_id}/review`, {
      score: Number(score),
      comment: comment || null,
    });
    setScoring(null);
    setComment('');
    reload();
    onReviewed();
  });

  if (loading) return <Loading rows={2} />;
  if (error) return <ErrorNote error={error} />;

  const answered = data?.submissions.filter((s) => s.submitted_at) ?? [];
  if (!answered.length) return <p className="muted">Решений пока нет</p>;

  return (
    <>
      <table className="table">
        <thead>
          <tr>
            <th>Кандидат</th>
            <th>Ответ</th>
            <th>Итог</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {answered.map((s) => (
            <tr key={s.assignment_id}>
              <td>
                {s.candidate_name}
                <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                  {dateTime(s.submitted_at)}
                </div>
              </td>
              <td style={{ maxWidth: 420 }}>
                {taskAnswer(s.answer)}
                {s.similar_to && (
                  <div style={{ marginTop: 'var(--sp-2)' }}>
                    <Badge tone="warn">
                      Совпадает на {Math.round(s.similar_to.share * 100)} % с ответом{' '}
                      {answered.find((o) => o.candidate_id === s.similar_to?.candidate_id)?.candidate_name ??
                        s.similar_to.candidate_id}
                    </Badge>
                  </div>
                )}
              </td>
              <td>
                {s.auto_correct === true && <Badge tone="success">Верно</Badge>}
                {s.auto_correct === false && <Badge tone="danger">Неверно</Badge>}
                {s.employer_score !== null && <Badge tone="accent">{s.employer_score} из 5</Badge>}
                {s.auto_correct === null && s.employer_score === null && (
                  <Badge tone="neutral">Не оценено</Badge>
                )}
              </td>
              <td style={{ textAlign: 'right' }}>
                {data?.task.kind === 'approach' && s.employer_score === null && (
                  <Button size="sm" onClick={() => setScoring(s)}>
                    Оценить
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {scoring && (
        <Modal
          title={`Оценка решения: ${scoring.candidate_name}`}
          onClose={() => setScoring(null)}
          footer={
            <>
              <Button onClick={() => setScoring(null)}>Отмена</Button>
              <Button variant="primary" busy={review.busy} onClick={() => void review.run()}>
                Сохранить оценку
              </Button>
            </>
          }
        >
          <div className="stack">
            <Card title="Ответ кандидата">
              <p style={{ fontSize: 'var(--text-sm)', whiteSpace: 'pre-line' }}>
                {taskAnswer(scoring.answer)}
              </p>
            </Card>
            <Field label="Оценка от 1 до 5" required>
              {(p) => (
                <Select {...p} value={score} onChange={(e) => setScore(e.target.value)}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Комментарий">
              {(p) => (
                <Textarea {...p} value={comment} onChange={(e) => setComment(e.target.value)} />
              )}
            </Field>
            <ErrorNote error={review.error} />
          </div>
        </Modal>
      )}
    </>
  );
}

export default function EmployerTasks() {
  const { data, loading, error, reload } = useAsync(
    () => api.get<EmployerTask[]>('/employer/tasks'),
    [],
  );
  const [creating, setCreating] = useState(false);
  const [openTask, setOpenTask] = useState<string | null>(null);

  if (loading && !data) return <Loading rows={3} />;
  if (error) return <ErrorNote error={error} />;

  return (
    <>
      <PageHeader
        title="Регулярные задания"
        subtitle="Короткая задача от вашей компании периодически приходит кандидатам подходящей категории. Это свежий сигнал о людях, которых вы ещё не приглашали"
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            Новое задание
          </Button>
        }
      />

      <div className="stack">
        {!data?.length && (
          <Empty
            title="Заданий нет"
            action={
              <Button variant="primary" onClick={() => setCreating(true)}>
                Создать первое
              </Button>
            }
          >
            Задание из двух-трёх предложений даёт больше сигнала, чем ещё одна строка в резюме
          </Empty>
        )}

        {data?.map((t) => (
          <Card
            key={t.id}
            title={t.title}
            subtitle={`${KIND_TITLE[t.kind] ?? t.kind} · ${t.specialization} · ${t.level_range
              .map(levelTitle)
              .join('–')}`}
            actions={
              <>
                {t.awaiting_review > 0 && <Badge tone="warn">на проверке: {t.awaiting_review}</Badge>}
                <Button
                  size="sm"
                  onClick={() => setOpenTask((cur) => (cur === t.id ? null : t.id))}
                >
                  {openTask === t.id ? 'Свернуть' : 'Решения'}
                </Button>
              </>
            }
          >
            <div className="row-wrap">
              <Badge tone={t.active ? 'success' : 'neutral'}>
                {t.active ? 'Выдаётся' : 'Остановлено'}
              </Badge>
              <span className="muted" style={{ fontSize: 'var(--text-sm)' }}>
                назначено {t.assigned} · решили {t.submitted}
              </span>
            </div>

            {openTask === t.id && (
              <div style={{ marginTop: 'var(--sp-4)' }}>
                <Submissions taskId={t.id} onReviewed={reload} />
              </div>
            )}
          </Card>
        ))}

        <Alert tone="neutral">
          Результаты заданий влияют на актуальность профиля кандидата и видны в его карточке
        </Alert>
      </div>

      {creating && (
        <TaskModal
          onClose={() => setCreating(false)}
          onDone={() => {
            setCreating(false);
            reload();
          }}
        />
      )}
    </>
  );
}
