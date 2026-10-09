import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction, useAsync } from '../../lib/useAsync';
import { useDraft } from '../../lib/useDraft';
import { date, levelTitle, percent, salaryRange } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Chip,
  ChipSelect,
  Empty,
  ErrorNote,
  Field,
  Input,
  Loading,
  Meter,
  PageHeader,
  Select,
  Textarea,
} from '../../components/ui';
import type { Level, Need, NeedProfile } from '../../api/types';

export function NeedList() {
  const { data, loading, error } = useAsync(() => api.get<Need[]>('/employer/needs'), []);

  if (loading) return <Loading rows={3} />;
  if (error) return <ErrorNote error={error} />;

  return (
    <>
      <PageHeader
        title="Потребности"
        subtitle="Опишите, кто нужен, – платформа превратит описание в профиль компетенций и подберёт кандидатов. Публиковать вакансию при этом необязательно"
        actions={
          <Link className="btn btn-primary" to="/employer/needs/new">
            Новая потребность
          </Link>
        }
      />

      {!data?.length ? (
        <Empty
          title="Потребностей пока нет"
          action={
            <Link className="btn btn-primary" to="/employer/needs/new">
              Описать первую
            </Link>
          }
        >
          С неё начинается подбор: по описанию строится профиль компетенций
        </Empty>
      ) : (
        <div className="stack">
          {data.map((n) => (
            <article key={n.id} className="card">
              <div className="row-top" style={{ justifyContent: 'space-between' }}>
                <div className="stack-sm" style={{ minWidth: 0 }}>
                  <h3>{n.title}</h3>
                  <div className="row-wrap">
                    <Badge tone="accent">
                      {n.specialization} · {levelTitle(n.level)}
                    </Badge>
                    {n.is_published ? (
                      <Badge tone="success">Опубликована</Badge>
                    ) : (
                      <Badge tone="neutral">Черновик</Badge>
                    )}
                    {n.suitable_for_minors && <Badge tone="neutral">Подходит для 15–17 лет</Badge>}
                    <span className="muted" style={{ fontSize: 'var(--text-xs)' }}>
                      создана {date(n.created_at)}
                    </span>
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className="salary salary-md">{salaryRange(n.salary_from, n.salary_to)}</div>
                </div>
              </div>

              <div className="row-wrap" style={{ marginTop: 'var(--sp-3)' }}>
                {n.profile.top_competencies.slice(0, 5).map((c) => (
                  <Chip key={c.competency} title={c.sources.join(' · ')}>
                    {c.title} {percent(c.weight)}
                  </Chip>
                ))}
              </div>

              <div className="row-wrap" style={{ marginTop: 'var(--sp-4)' }}>
                <Link className="btn btn-primary btn-sm" to={`/employer/selection?need=${n.id}`}>
                  Показать подборку
                </Link>
                <Link className="btn btn-secondary btn-sm" to={`/employer/needs/${n.id}`}>
                  Редактировать
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}

/** Профиль потребности: что платформа будет искать и откуда взялись веса. */
function ProfilePreview({ profile }: { profile: NeedProfile }) {
  return (
    <Card
      title="Что мы будем искать"
      subtitle="Профиль собран из специализации, грейда, стека и текста описания"
    >
      <table className="table">
        <thead>
          <tr>
            <th>Компетенция</th>
            <th style={{ width: '34%' }}>Вес</th>
            <th>Источник веса</th>
          </tr>
        </thead>
        <tbody>
          {profile.top_competencies.map((c) => (
            <tr key={c.competency}>
              <td>{c.title}</td>
              <td>
                <div className="row" style={{ gap: 'var(--sp-3)' }}>
                  <span className="mono" style={{ minWidth: 40 }}>
                    {percent(c.weight)}
                  </span>
                  <div style={{ flex: 1 }}>
                    <Meter value={c.weight} label={c.title} />
                  </div>
                </div>
              </td>
              <td className="muted" style={{ fontSize: 'var(--text-xs)' }}>
                {c.sources.join(' · ')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {profile.skills_from_text.length > 0 && (
        <div style={{ marginTop: 'var(--sp-4)' }}>
          <div className="faint" style={{ fontSize: 'var(--text-xs)', marginBottom: 'var(--sp-2)' }}>
            Распознано прямо из текста описания:
          </div>
          <div className="row-wrap">
            {profile.skills_from_text.map((s) => (
              <Chip key={s} active>
                {s}
              </Chip>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

type TestPreview = {
  category: { specialization: string; level: Level };
  coverage: {
    seeds_simulated: number;
    competencies: {
      competency: string;
      title: string;
      weight: number;
      mandatory_in_test: boolean;
      share_of_attempts: number;
      items_per_attempt: number;
    }[];
  };
};

/**
 * Насколько тест категории измеряет именно то, что нужно этой потребности.
 *
 * Полезен ответ на вопрос «чему верить в подборке»: важная для задачи
 * компетенция, которая редко попадает в тест, подтверждена слабо — и это
 * честнее показать работодателю, чем прятать.
 */
function TestCoverage({ needId }: { needId: string }) {
  const { data, loading, error } = useAsync(
    () => api.get<TestPreview>(`/employer/needs/${needId}/test-preview`),
    [needId],
  );

  if (loading) return <Loading rows={2} />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  const rows = [...data.coverage.competencies].sort((a, b) => b.weight - a.weight);
  const weak = rows.filter((c) => c.weight >= 0.6 && c.share_of_attempts < 0.5);

  return (
    <Card
      title="Покрытие тестом"
      subtitle={`Что из нужного вам реально измеряет тест категории ${levelTitle(
        data.category.level,
      )}. Оценка по ${data.coverage.seeds_simulated} смоделированным вариантам теста`}
    >
      {weak.length > 0 && (
        <div style={{ marginBottom: 'var(--sp-4)' }}>
          <Alert tone="warn" title="Подтверждено слабее остального">
            {weak.map((c) => c.title).join(', ')} – важны для задачи, но попадают в тест не всегда.
            В подборке опирайтесь на эти оценки осторожнее
          </Alert>
        </div>
      )}

      <table className="table">
        <thead>
          <tr>
            <th>Компетенция</th>
            <th className="table-num">Вес в задаче</th>
            <th style={{ width: '30%' }}>Как часто в тесте</th>
            <th className="table-num">Заданий в попытке</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.competency}>
              <td>
                {c.title}
                {c.mandatory_in_test && (
                  <>
                    {' '}
                    <Badge tone="accent">всегда</Badge>
                  </>
                )}
              </td>
              <td className="table-num">{percent(c.weight)}</td>
              <td>
                <div className="row" style={{ gap: 'var(--sp-3)' }}>
                  <span className="mono" style={{ minWidth: 40 }}>
                    {percent(c.share_of_attempts)}
                  </span>
                  <div style={{ flex: 1 }}>
                    <Meter value={c.share_of_attempts} label={c.title} />
                  </div>
                </div>
              </td>
              <td className="table-num">{c.items_per_attempt.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

type FormState = {
  title: string;
  specialization: string;
  level: Level | '';
  description: string;
  team_description: string;
  stack: string[];
  work_format: string;
  city: string;
  salary_from: string;
  salary_to: string;
  suitable_for_minors: boolean;
};

function needToForm(n: Need): FormState {
  return {
    title: n.title,
    specialization: n.specialization,
    level: n.level,
    description: n.description ?? '',
    team_description: n.team_description ?? '',
    stack: n.stack,
    work_format: n.work_format ?? '',
    city: n.city ?? '',
    salary_from: String(n.salary_from),
    salary_to: String(n.salary_to),
    suitable_for_minors: Boolean(n.suitable_for_minors),
  };
}

const EMPTY: FormState = {
  title: '',
  specialization: '',
  level: '',
  description: '',
  team_description: '',
  stack: [],
  work_format: '',
  city: '',
  salary_from: '',
  salary_to: '',
  suitable_for_minors: false,
};

export function NeedForm() {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === 'new';
  const navigate = useNavigate();
  const { ref, skillsFor } = useReference();

  const existing = useAsync(
    () => (isNew ? Promise.resolve(null) : api.get<Need>(`/employer/needs/${id}`)),
    [id],
  );

  const [form, setForm] = useDraft(existing.data, needToForm, EMPTY);
  const [hints, setHints] = useState<string[]>([]);

  /** Помощник: вытаскивает навыки из текста описания. */
  const extract = useAction(async () => {
    const res = await api.get<{ skills_from_text: string[] }>('/employer/skills/extract', {
      text: `${form.description} ${form.team_description}`,
    });
    setHints(res.skills_from_text.filter((s) => !form.stack.includes(s)));
  });

  const save = useAction(async () => {
    const body = {
      title: form.title,
      specialization: form.specialization,
      level: form.level,
      description: form.description,
      team_description: form.team_description || null,
      stack: form.stack,
      work_format: form.work_format || undefined,
      city: form.city || null,
      salary_from: Number(form.salary_from),
      salary_to: Number(form.salary_to),
      suitable_for_minors: form.suitable_for_minors,
    };
    const saved = isNew
      ? await api.post<Need>('/employer/needs', body)
      : await api.patch<Need>(`/employer/needs/${id}`, body);
    navigate(`/employer/selection?need=${saved.id}`);
  });

  const publish = useAction(async (next: boolean) => {
    await api.post(`/employer/needs/${id}/${next ? 'publish' : 'unpublish'}`);
    existing.reload();
  });

  const close = useAction(async () => {
    await api.post(`/employer/needs/${id}/close`);
    existing.reload();
  });

  if (!isNew && existing.loading) return <Loading rows={4} />;

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }));
  const errs = save.error?.fieldErrors ?? {};
  const ready = form.title && form.specialization && form.level && form.salary_from && form.salary_to;

  return (
    <>
      <PageHeader
        title={isNew ? 'Новая потребность' : 'Потребность'}
        subtitle="Вилка зарплаты обязательна: кандидат должен видеть условия до начала общения"
        actions={
          !isNew && existing.data && existing.data.status !== 'closed' ? (
            <>
              {existing.data.is_published ? (
                <Button busy={publish.busy} onClick={() => void publish.run(false)}>
                  Снять с публикации
                </Button>
              ) : (
                <Button busy={publish.busy} onClick={() => void publish.run(true)}>
                  Опубликовать как вакансию
                </Button>
              )}
              <Button variant="danger" busy={close.busy} onClick={() => void close.run()}>
                Закрыть набор
              </Button>
            </>
          ) : null
        }
      />

      <div className="stack">
        <ErrorNote error={publish.error} />
        <ErrorNote error={close.error} />

        {existing.data?.status === 'closed' && (
          <Alert tone="neutral" title="Набор закрыт">
            Потребность больше не показывается кандидатам и не участвует в подборке
          </Alert>
        )}

        <Card title="Кто нужен">
          <div className="grid-2">
            <Field label="Название позиции" required error={errs.title}>
              {(p) => (
                <Input
                  {...p}
                  placeholder="Бэкенд-разработчик в платёжный сервис"
                  value={form.title}
                  onChange={(e) => set('title', e.target.value)}
                />
              )}
            </Field>
            <Field label="Город" error={errs.city}>
              {(p) => <Input {...p} value={form.city} onChange={(e) => set('city', e.target.value)} />}
            </Field>
            <Field label="Специализация" required error={errs.specialization}>
              {(p) => (
                <Select
                  {...p}
                  value={form.specialization}
                  onChange={(e) => set('specialization', e.target.value)}
                >
                  <option value="">Выберите…</option>
                  {ref?.specializations.map((s) => (
                    <option key={s.slug} value={s.slug}>
                      {s.title}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Грейд" required error={errs.level}>
              {(p) => (
                <Select {...p} value={form.level} onChange={(e) => set('level', e.target.value as Level)}>
                  <option value="">Выберите…</option>
                  {ref?.levels.map((l) => (
                    <option key={l.slug} value={l.slug}>
                      {l.title}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Формат работы" error={errs.work_format}>
              {(p) => (
                <Select
                  {...p}
                  value={form.work_format}
                  onChange={(e) => set('work_format', e.target.value)}
                >
                  <option value="">Не важно</option>
                  {ref?.work_formats.map((w) => (
                    <option key={w.slug} value={w.slug}>
                      {w.title}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>
        </Card>

        <Card
          title="Вилка зарплаты"
          subtitle="Обязательное поле. Кандидат увидит её первой строкой приглашения"
        >
          <div className="grid-2">
            <Field label="От, ₽" required error={errs.salary_from}>
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  min="0"
                  value={form.salary_from}
                  onChange={(e) => set('salary_from', e.target.value)}
                />
              )}
            </Field>
            <Field label="До, ₽" required error={errs.salary_to}>
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  min="0"
                  value={form.salary_to}
                  onChange={(e) => set('salary_to', e.target.value)}
                />
              )}
            </Field>
          </div>
          <div style={{ marginTop: 'var(--sp-4)' }}>
            <Checkbox
              checked={form.suitable_for_minors}
              onChange={(v) => set('suitable_for_minors', v)}
              label="Подходит для несовершеннолетних (15–17 лет): лёгкий труд, сокращённое время, без вредных и опасных условий"
            />
          </div>
        </Card>

        <Card
          title="Задача"
          subtitle="Чем конкретнее текст, тем точнее профиль компетенций"
          actions={
            <Button size="sm" busy={extract.busy} onClick={() => void extract.run()}>
              Найти навыки в тексте
            </Button>
          }
        >
          <div className="stack">
            <Field label="Что делать" error={errs.description}>
              {(p) => (
                <Textarea
                  {...p}
                  value={form.description}
                  placeholder="Развиваем сервис платежей: 3000 запросов в секунду в пике…"
                  onChange={(e) => set('description', e.target.value)}
                />
              )}
            </Field>
            <Field label="Чем занимается команда" error={errs.team_description}>
              {(p) => (
                <Textarea
                  {...p}
                  maxLength={3000}
                  value={form.team_description}
                  placeholder="Команда из 6 человек: 4 бэкенда, QA и тимлид…"
                  onChange={(e) => set('team_description', e.target.value)}
                />
              )}
            </Field>

            {hints.length > 0 && (
              <Alert tone="info" title="Нашли в тексте">
                <div className="row-wrap" style={{ marginTop: 'var(--sp-2)' }}>
                  {hints.map((s) => (
                    <Chip
                      key={s}
                      onClick={() => {
                        set('stack', [...form.stack, s]);
                        setHints((h) => h.filter((x) => x !== s));
                      }}
                    >
                      + {s}
                    </Chip>
                  ))}
                </div>
              </Alert>
            )}
          </div>
        </Card>

        <Card title="Стек">
          <ChipSelect
            options={skillsFor(form.specialization)}
            value={form.stack}
            onChange={(v) => set('stack', v)}
            emptyHint="Сначала выберите специализацию"
          />
        </Card>

        <ErrorNote error={save.error} />

        <div className="row">
          <Button variant="primary" size="lg" busy={save.busy} disabled={!ready} onClick={() => void save.run()}>
            {isNew ? 'Сохранить и показать подборку' : 'Сохранить'}
          </Button>
          <Link className="btn btn-ghost" to="/employer/needs">
            Отмена
          </Link>
        </div>

        {existing.data && (
          <>
            <ProfilePreview profile={existing.data.profile} />
            <TestCoverage needId={existing.data.id} />
          </>
        )}
      </div>
    </>
  );
}
