import { useRef, useState } from 'react';
import { api, download, upload } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction, useAsync } from '../../lib/useAsync';
import { useDraft } from '../../lib/useDraft';
import { date, percent } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ChipSelect,
  ErrorNote,
  Field,
  Input,
  Loading,
  PageHeader,
  Textarea,
} from '../../components/ui';
import type { CandidateProfile, Guardian } from '../../api/types';

type Suggestion = { value: string | string[]; confidence: number; source: string | null };
type Suggestions = Record<string, Suggestion | number>;

/** Поля анкеты, которые можно перенести из распознанного резюме. */
const SUGGESTION_LABEL: Record<string, string> = {
  full_name: 'ФИО',
  contact_email: 'Почта для связи',
  phone: 'Телефон',
  telegram: 'Telegram',
  city: 'Город',
  stack: 'Стек',
  roles: 'Роли в команде',
  experience_years: 'Опыт, лет',
  about: 'О себе',
};

function isSuggestion(v: Suggestion | number): v is Suggestion {
  return typeof v === 'object' && v !== null && 'confidence' in v;
}

/**
 * Разбор загруженного PDF. Профиль намеренно не перезаписывается
 * автоматически: кандидат сам отмечает, какие поля перенести.
 */
function ResumeCard({ profile, onApplied }: { profile: CandidateProfile; onApplied: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [suggestions, setSuggestions] = useState<Suggestions | null>(null);
  const [picked, setPicked] = useState<string[]>([]);

  const send = useAction(async (file: File) => {
    const res = await upload<{ suggestions: Suggestions }>('/candidate/profile/resume', file);
    setSuggestions(res.suggestions);
    // По умолчанию отмечаем только уверенные распознавания.
    setPicked(
      Object.entries(res.suggestions)
        .filter(([k, v]) => SUGGESTION_LABEL[k] && isSuggestion(v) && v.confidence >= 0.7)
        .map(([k]) => k),
    );
  });

  const apply = useAction(async () => {
    await api.post('/candidate/profile/resume/apply', { fields: picked });
    setSuggestions(null);
    setPicked([]);
    onApplied();
  });

  const getPdf = useAction(() => download('/candidate/profile/pdf', 'profile.pdf'));

  const rows = Object.entries(suggestions ?? {}).filter(
    ([k, v]) => SUGGESTION_LABEL[k] && isSuggestion(v),
  ) as [string, Suggestion][];

  return (
    <Card
      title="Резюме"
      subtitle={
        profile.resume_filename
          ? `Загружено: ${profile.resume_filename}, ${date(profile.resume_uploaded_at)}`
          : 'Загрузите PDF – распознаем поля и предложим перенести их в анкету'
      }
      actions={
        <Button size="sm" onClick={() => void getPdf.run()} busy={getPdf.busy}>
          Скачать PDF-профиль
        </Button>
      }
    >
      <div className="stack">
        <ErrorNote error={getPdf.error} />

        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          className="sr-only"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void send.run(f);
            e.target.value = '';
          }}
        />
        <div className="row-wrap">
          <Button variant="primary" onClick={() => fileRef.current?.click()} busy={send.busy}>
            Загрузить PDF-резюме
          </Button>
          <span className="faint" style={{ fontSize: 'var(--text-xs)' }}>
            Только PDF, до 5 МБ
          </span>
        </div>

        <ErrorNote error={send.error} />

        {suggestions && (
          <>
            <Alert tone="info" title="Что удалось распознать">
              Отметьте поля, которые перенести в анкету. Остальное останется как есть
            </Alert>

            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 36 }} />
                  <th>Поле</th>
                  <th>Значение</th>
                  <th className="table-num">Уверенность</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(([key, s]) => (
                  <tr key={key}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={SUGGESTION_LABEL[key]}
                        checked={picked.includes(key)}
                        onChange={(e) =>
                          setPicked((prev) =>
                            e.target.checked ? [...prev, key] : prev.filter((p) => p !== key),
                          )
                        }
                        style={{ width: 18, height: 18, accentColor: 'var(--violet-500)' }}
                      />
                    </td>
                    <td>{SUGGESTION_LABEL[key]}</td>
                    <td>
                      <div>{Array.isArray(s.value) ? s.value.join(', ') : s.value}</div>
                      {s.source && (
                        <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                          из резюме: {s.source.slice(0, 90)}
                        </div>
                      )}
                    </td>
                    <td className="table-num">{percent(s.confidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <ErrorNote error={apply.error} />
            <div className="row">
              <Button
                variant="primary"
                onClick={() => void apply.run()}
                busy={apply.busy}
                disabled={!picked.length}
              >
                Перенести отмеченное ({picked.length})
              </Button>
              <Button variant="ghost" onClick={() => setSuggestions(null)}>
                Не переносить
              </Button>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

const GUARDIAN_STATUS: Record<Guardian['status'], { title: string; tone: 'success' | 'warn' | 'neutral' }> = {
  pending: { title: 'Ждём ответа представителя', tone: 'warn' },
  granted: { title: 'Согласие получено', tone: 'success' },
  declined: { title: 'Представитель отказал', tone: 'neutral' },
  revoked: { title: 'Согласие отозвано', tone: 'neutral' },
};

/**
 * С 15 до 18 лет профиль показывается работодателям и отклики возможны
 * только после согласия законного представителя: ему уходит письмо со
 * ссылкой. На демо-стенде ссылка приходит и в ответе API (`dev_link`), чтобы
 * сценарий можно было пройти без почтового ящика.
 */
function GuardianCard({ profile, onChanged }: { profile: CandidateProfile; onChanged: () => void }) {
  const g = profile.guardian;
  const [name, setName] = useState(g?.guardian_name ?? '');
  const [email, setEmail] = useState(g?.guardian_email ?? '');
  const [demoLink, setDemoLink] = useState<string | null>(null);
  const send = useAction(async () => {
    const res = await api.post<{ dev_link?: string | null }>('/candidate/guardian', { full_name: name, email });
    setDemoLink(res.dev_link ?? null);
    onChanged();
  });
  const status = g ? GUARDIAN_STATUS[g.status] : null;
  const errs = send.error?.fieldErrors ?? {};

  return (
    <Card
      title="Согласие законного представителя"
      subtitle={`Вам ${profile.age} лет. Тест и категория доступны уже сейчас, а показать профиль работодателям и откликаться на вакансии можно после согласия родителя или опекуна`}
      actions={status && <Badge tone={status.tone}>{status.title}</Badge>}
    >
      <div className="stack">
        {g?.status === 'granted' ? (
          <Alert tone="success">
            {g.guardian_name} дал(а) согласие {g.decided_at ? date(g.decided_at) : ''}. Работодатели увидят
            отметку «до 18 лет» и смогут предложить только работу с лёгким трудом и сокращённым временем.
            Отозвать согласие представитель может по ссылке из письма
          </Alert>
        ) : (
          <>
            {g?.status === 'pending' && (
              <Alert tone="info">
                Письмо отправлено на {g.guardian_email}. Ссылка действует до {date(g.expires_at)}. Если письмо не
                дошло, проверьте адрес и отправьте ещё раз
              </Alert>
            )}
            {(g?.status === 'declined' || g?.status === 'revoked') && (
              <Alert tone="neutral">
                Прежняя ссылка больше не действует. Чтобы получить согласие, отправьте представителю новый запрос
              </Alert>
            )}
            {demoLink && (
              <Alert tone="neutral" title="Демо-стенд">
                Ссылка для представителя из письма:{' '}
                <a href={demoLink} target="_blank" rel="noreferrer">
                  открыть страницу согласия
                </a>
              </Alert>
            )}
            <div className="grid-2">
              <Field label="ФИО представителя" required error={errs.full_name}>
                {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
              </Field>
              <Field label="Почта представителя" required hint="Только в домене .ru" error={errs.email}>
                {(p) => (
                  <Input {...p} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
                )}
              </Field>
            </div>
            <ErrorNote error={send.error} />
            <div>
              <Button
                variant="primary"
                busy={send.busy}
                disabled={name.trim().length < 3 || !email.includes('@')}
                onClick={() => void send.run()}
              >
                {g ? 'Отправить письмо ещё раз' : 'Отправить письмо представителю'}
              </Button>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

export default function Profile() {
  const { ref, skillsFor } = useReference();
  const { data, loading, error, reload, set: setData } = useAsync(
    () => api.get<CandidateProfile>('/candidate/profile'),
    [],
  );

  // Данные приходят асинхронно — форма наполняется, когда профиль загрузился.
  const [form, setForm] = useDraft<CandidateProfile, Partial<CandidateProfile>>(data, (p) => p, {});
  const [saved, setSaved] = useState(false);

  const save = useAction(async () => {
    const updated = await api.patch<CandidateProfile>('/candidate/profile', {
      full_name: form.full_name || null,
      contact_email: form.contact_email || null,
      phone: form.phone || null,
      telegram: form.telegram || null,
      city: form.city || null,
      about: form.about || null,
      experience_years: form.experience_years ?? null,
      roles: form.roles ?? [],
      stack: form.stack ?? [],
      soft_skills: form.soft_skills ?? [],
      work_formats: form.work_formats ?? [],
      relocation: form.relocation ?? false,
      salary_expectation: form.salary_expectation ?? null,
      open_to_offers: form.open_to_offers ?? true,
      birth_date: form.birth_date || null,
    });
    setData(updated);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  });

  // при перечитывании (согласие представителя, резюме) карточки остаются на месте со своим состоянием
  if (loading && !data) return <Loading rows={5} />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  const set = <K extends keyof CandidateProfile>(key: K, value: CandidateProfile[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const fieldErrors = save.error?.fieldErrors ?? {};

  return (
    <>
      <PageHeader
        title="Анкета и резюме"
        subtitle="Эти данные видит работодатель с пометкой «заявлено кандидатом». Категорию и грейд подтверждает тест, а не анкета"
        actions={
          <Button variant="primary" onClick={() => void save.run()} busy={save.busy}>
            Сохранить
          </Button>
        }
      />

      <div className="stack">
        {saved && <Alert tone="success">Анкета сохранена</Alert>}
        <ErrorNote error={save.error} />

        {data.below_work_age && (
          <Alert tone="info" title={`До ${ref?.minors?.work_age ?? 15} лет — только тест и категория`}>
            Трудовой договор возможен с {ref?.minors?.work_age ?? 15} лет, поэтому до этого возраста профиль не
            показывается работодателям, а приглашения и отклики недоступны. Тест и категорию можно пройти уже сейчас
          </Alert>
        )}
        {data.minor && !data.below_work_age && <GuardianCard profile={data} onChanged={reload} />}

        <ResumeCard profile={data} onApplied={reload} />

        <Card title="Контакты" subtitle="Работодатель увидит их только после того, как вы примете приглашение">
          <div className="grid-2">
            <Field label="ФИО" error={fieldErrors.full_name}>
              {(p) => (
                <Input
                  {...p}
                  value={form.full_name ?? ''}
                  onChange={(e) => set('full_name', e.target.value)}
                />
              )}
            </Field>
            <Field label="Город" error={fieldErrors.city}>
              {(p) => (
                <Input {...p} value={form.city ?? ''} onChange={(e) => set('city', e.target.value)} />
              )}
            </Field>
            <Field label="Почта для связи" error={fieldErrors.contact_email}>
              {(p) => (
                <Input
                  {...p}
                  type="email"
                  value={form.contact_email ?? ''}
                  onChange={(e) => set('contact_email', e.target.value)}
                />
              )}
            </Field>
            <Field label="Телефон" error={fieldErrors.phone}>
              {(p) => (
                <Input {...p} value={form.phone ?? ''} onChange={(e) => set('phone', e.target.value)} />
              )}
            </Field>
            <Field label="Telegram" error={fieldErrors.telegram}>
              {(p) => (
                <Input
                  {...p}
                  placeholder="@username"
                  value={form.telegram ?? ''}
                  onChange={(e) => set('telegram', e.target.value)}
                />
              )}
            </Field>
            <Field
              label="Дата рождения"
              hint={`Работодатель её не видит. До ${ref?.minors?.adult_age ?? 18} лет действуют особые правила; тест — с ${ref?.minors?.min_age ?? 14} лет, показ работодателям — с ${ref?.minors?.work_age ?? 15}`}
              error={fieldErrors.birth_date}
            >
              {(p) => (
                <Input
                  {...p}
                  type="date"
                  value={form.birth_date ?? ''}
                  onChange={(e) => set('birth_date', e.target.value || null)}
                />
              )}
            </Field>
          </div>
          <div style={{ marginTop: 'var(--sp-4)' }}>
            <Checkbox
              checked={form.relocation ?? false}
              onChange={(v) => set('relocation', v)}
              label="Готов к переезду"
            />
          </div>
        </Card>

        <Card title="Опыт и ожидания">
          <div className="grid-2">
            <Field label="Опыт, лет" error={fieldErrors.experience_years}>
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  step="0.5"
                  min="0"
                  max="60"
                  value={form.experience_years ?? ''}
                  onChange={(e) =>
                    set('experience_years', e.target.value === '' ? null : Number(e.target.value))
                  }
                />
              )}
            </Field>
            <Field
              label="Ожидания по зарплате, ₽"
              hint="Работодатель увидит предупреждение, если предложит заметно меньше"
              error={fieldErrors.salary_expectation}
            >
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  min="0"
                  value={form.salary_expectation ?? ''}
                  onChange={(e) =>
                    set('salary_expectation', e.target.value === '' ? null : Number(e.target.value))
                  }
                />
              )}
            </Field>
          </div>

          <div style={{ marginTop: 'var(--sp-4)' }}>
            <Field label="О себе" error={fieldErrors.about}>
              {(p) => (
                <Textarea
                  {...p}
                  maxLength={3000}
                  value={form.about ?? ''}
                  onChange={(e) => set('about', e.target.value)}
                />
              )}
            </Field>
          </div>

          <div style={{ marginTop: 'var(--sp-4)' }}>
            <Checkbox
              checked={form.open_to_offers ?? true}
              onChange={(v) => set('open_to_offers', v)}
              label="Открыт к предложениям"
            />
          </div>
        </Card>

        <Card title="Стек" subtitle="Отметьте технологии, с которыми работали">
          <ChipSelect
            options={skillsFor(data.primary_specialization)}
            value={form.stack ?? []}
            onChange={(v) => set('stack', v)}
          />
        </Card>

        <Card title="Роль в команде">
          <ChipSelect
            options={ref?.team_roles ?? []}
            value={form.roles ?? []}
            onChange={(v) => set('roles', v)}
          />
        </Card>

        <Card title="Софт-скиллы">
          <ChipSelect
            options={ref?.soft_skills ?? []}
            value={form.soft_skills ?? []}
            onChange={(v) => set('soft_skills', v)}
          />
        </Card>

        <Card title="Формат работы">
          <ChipSelect
            options={ref?.work_formats ?? []}
            value={form.work_formats ?? []}
            onChange={(v) => set('work_formats', v)}
          />
        </Card>

        <div className="row">
          <Button variant="primary" onClick={() => void save.run()} busy={save.busy}>
            Сохранить анкету
          </Button>
          {saved && <span className="muted">Сохранено</span>}
        </div>
      </div>
    </>
  );
}
