import { useState } from 'react';
import { api } from '../../api/client';
import { useAction, useAsync } from '../../lib/useAsync';
import { date, dateTime, taskAnswer } from '../../lib/format';
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
  PageHeader,
} from '../../components/ui';
import { cx } from '../../lib/cx';
import type { TaskAssignment } from '../../api/types';

const KIND_HINT: Record<string, string> = {
  choice: 'Выберите один вариант',
  numeric: 'Введите число',
  approach: 'Опишите подход к решению – не меньше 20 символов',
};

/** Форма ответа на регулярное задание. Вид зависит от типа задачи. */
function TaskForm({ item, onDone }: { item: TaskAssignment; onDone: () => void }) {
  const [option, setOption] = useState('');
  const [number, setNumber] = useState('');
  const [text, setText] = useState('');

  const submit = useAction(async () => {
    const body =
      item.task.kind === 'choice'
        ? { option }
        : item.task.kind === 'numeric'
          ? { number }
          : { text };
    await api.post(`/candidate/tasks/${item.id}/submit`, body);
    onDone();
  });

  const ready =
    item.task.kind === 'choice'
      ? Boolean(option)
      : item.task.kind === 'numeric'
        ? number !== ''
        : text.trim().length >= 20;

  return (
    <div className="stack">
      <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
        {KIND_HINT[item.task.kind]}
      </p>

      {item.task.kind === 'choice' && (
        <div className="optlist" role="radiogroup" aria-label="Варианты ответа">
          {item.task.options.map((o) => (
            <label key={o.id} className={cx('opt', option === o.id && 'opt-on')}>
              <input
                type="radio"
                name={`task-${item.id}`}
                checked={option === o.id}
                onChange={() => setOption(o.id)}
              />
              <span className="opt-id">{o.id}</span>
              <span>{o.text}</span>
            </label>
          ))}
        </div>
      )}

      {item.task.kind === 'numeric' && (
        <div style={{ maxWidth: 240 }}>
          <Field label="Ответ">
            {(p) => (
              <Input
                {...p}
                type="number"
                value={number}
                onChange={(e) => setNumber(e.target.value)}
              />
            )}
          </Field>
        </div>
      )}

      {item.task.kind === 'approach' && (
        <Field label="Как бы вы это решили" hint={`${text.trim().length} из 20 символов минимум`}>
          {(p) => (
            <textarea
              {...p}
              className="textarea"
              value={text}
              maxLength={5000}
              onChange={(e) => setText(e.target.value)}
              placeholder="Шаги решения, на что обратить внимание, какие риски…"
            />
          )}
        </Field>
      )}

      <ErrorNote error={submit.error} />

      <div>
        <Button variant="primary" busy={submit.busy} disabled={!ready} onClick={() => void submit.run()}>
          Отправить ответ
        </Button>
      </div>
    </div>
  );
}

export default function Tasks() {
  // Новое задание выдаётся при открытии раздела — так устроен бэкенд.
  const { data, loading, error, reload } = useAsync(
    () => api.get<TaskAssignment[]>('/candidate/tasks'),
    [],
  );

  if (loading && !data) return <Loading rows={3} />;
  if (error) return <ErrorNote error={error} />;

  const open = data?.filter((t) => t.status === 'assigned') ?? [];
  const done = data?.filter((t) => t.status !== 'assigned') ?? [];

  return (
    <>
      <PageHeader
        title="Регулярные задания"
        subtitle="Короткие задачи от работодателей. Они поддерживают профиль в актуальном состоянии и дают работодателю свежий сигнал о вас"
      />

      <div className="stack">
        {!data?.length && (
          <Empty title="Заданий пока нет">
            Новое задание появится автоматически – загляните сюда позже
          </Empty>
        )}

        {open.map((t) => (
          <Card
            key={t.id}
            title={t.task.title}
            subtitle={t.task.company ? `От компании «${t.task.company}»` : undefined}
            actions={
              t.due_at ? <Badge tone="warn">ответить до {date(t.due_at)}</Badge> : undefined
            }
          >
            <p style={{ whiteSpace: 'pre-line', marginBottom: 'var(--sp-4)' }}>{t.task.body}</p>
            <TaskForm item={t} onDone={reload} />
          </Card>
        ))}

        {done.map((t) => (
          <Card
            key={t.id}
            title={t.task.title}
            subtitle={t.submitted_at ? `Отправлено ${dateTime(t.submitted_at)}` : undefined}
            actions={
              t.auto_correct === true ? (
                <Badge tone="success">Верно</Badge>
              ) : t.auto_correct === false ? (
                <Badge tone="danger">Неверно</Badge>
              ) : t.employer_score !== null ? (
                <Badge tone="accent">Оценка {t.employer_score} из 5</Badge>
              ) : (
                <Badge tone="neutral">На проверке</Badge>
              )
            }
          >
            <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
              {t.task.body}
            </p>
            {t.answer && (
              <div style={{ marginTop: 'var(--sp-3)' }}>
                <div className="field-label">Ваш ответ</div>
                <p style={{ fontSize: 'var(--text-sm)', whiteSpace: 'pre-line' }}>
                  {taskAnswer(t.answer)}
                </p>
              </div>
            )}
            {t.employer_comment && (
              <div style={{ marginTop: 'var(--sp-3)' }}>
                <Alert tone="neutral" title="Комментарий работодателя">
                  {t.employer_comment}
                </Alert>
              </div>
            )}
          </Card>
        ))}
      </div>
    </>
  );
}
