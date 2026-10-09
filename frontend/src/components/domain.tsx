import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api/client';
import { useAction, useAsync } from '../lib/useAsync';
import { Alert, Badge, Button, Card, Chip, ErrorNote, Meter, Textarea } from './ui';
import { count, date, dateTime, levelTitle, percent, salaryRange, score } from '../lib/format';
import type {
  CandidateCard,
  Competency,
  CompanyTrust,
  FspAchievement,
  FspProfile,
  FspStats,
  Match,
  Message,
  TimelineEvent,
} from '../api/types';

/** Цвета слагаемых балла. Порядок повторяет порядок факторов с бэкенда. */
const FACTOR_COLOR: Record<string, string> = {
  competencies: 'var(--violet-500)',
  test: 'var(--violet-300)',
  stack: 'var(--brand-ink)',
  fsp: 'var(--brand-red)',
  freshness: 'var(--brand-gray)',
};
const FALLBACK_COLORS = ['var(--violet-700)', 'var(--amber-500)', 'var(--green-500)'];

function factorColor(slug: string, index: number): string {
  return FACTOR_COLOR[slug] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

// ------------------------------------------------------------- статусы

const INVITATION_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warn' | 'danger'> = {
  sent: 'accent',
  viewed: 'warn',
  accepted: 'success',
  declined: 'danger',
  expired: 'neutral',
  withdrawn: 'neutral',
};
const INVITATION_LABEL: Record<string, string> = {
  sent: 'Отправлено',
  viewed: 'Просмотрено',
  accepted: 'Принято',
  declined: 'Отклонено',
  expired: 'Истекло',
  withdrawn: 'Отозвано',
};

export function InvitationStatusBadge({ status }: { status: string }) {
  return <Badge tone={INVITATION_TONE[status] ?? 'neutral'}>{INVITATION_LABEL[status] ?? status}</Badge>;
}

const APPLICATION_LABEL: Record<string, string> = {
  sent: 'Отправлен',
  viewed: 'Просмотрен',
  invited: 'Приглашение',
  rejected: 'Отказ',
  withdrawn: 'Отозван',
};
const APPLICATION_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warn' | 'danger'> = {
  sent: 'accent',
  viewed: 'warn',
  invited: 'success',
  rejected: 'danger',
  withdrawn: 'neutral',
};

export function ApplicationStatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={APPLICATION_TONE[status] ?? 'neutral'}>{APPLICATION_LABEL[status] ?? status}</Badge>
  );
}

/**
 * Категория кандидата: IT-направление (отрасль), специализация и грейд.
 * Заявленный, но не подтверждённый тестом грейд показывается отдельно —
 * такие кандидаты видны работодателю, но стоят ниже подтверждённых.
 */
export function CategoryBadge({
  specialization,
  level,
  track,
  confirmed = true,
  tone = 'solid',
}: {
  specialization: string;
  level: string;
  track?: string | null;
  confirmed?: boolean;
  tone?: 'solid' | 'accent';
}) {
  if (!confirmed) {
    return (
      <Badge tone="warn">
        {specialization}
        {track ? ` · ${track}` : ''} · заявлен {levelTitle(level)}, не подтверждён
      </Badge>
    );
  }
  return (
    <Badge tone={tone}>
      {specialization}
      {track ? ` · ${track}` : ''} · {levelTitle(level)}
    </Badge>
  );
}

// ------------------------------------------------------------- зарплата

/**
 * Вилка зарплаты. По ТЗ кандидат видит условия до начала общения, поэтому
 * в карточках приглашений и вакансий она стоит первой и набрана крупно.
 */
export function Salary({
  from,
  to,
  size = 'md',
  warnings,
}: {
  from?: number | null;
  to?: number | null;
  size?: 'md' | 'lg';
  warnings?: string[] | null;
}) {
  return (
    <div>
      <div className={`salary salary-${size}`}>{salaryRange(from, to)}</div>
      {/* Основа сумм подписана явно: на платформе все суммы до вычета НДФЛ. */}
      <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
        в месяц, до вычета НДФЛ
      </div>
      {warnings?.map((w) => (
        <div key={w} className="field-error" style={{ marginTop: 4 }}>
          {w}
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------- разложение балла

/**
 * Главный элемент объяснимости выдачи: из чего сложился балл соответствия.
 * Ширина сегмента — вклад фактора в баллах, подсказка — текст с бэкенда.
 */
export function MatchBreakdown({ match, compact }: { match: Match; compact?: boolean }) {
  const total = match.factors.reduce((sum, f) => sum + Math.max(0, f.contribution), 0) || 1;

  return (
    <div className="stack-sm">
      <div className="contrib">
        {match.factors.map((f, i) => (
          <div
            key={f.factor}
            className="contrib-seg"
            style={{
              width: `${(Math.max(0, f.contribution) / total) * 100}%`,
              background: factorColor(f.factor, i),
            }}
            title={`${f.title}: ${f.contribution.toFixed(1)} из 100 – ${f.text}`}
          />
        ))}
      </div>

      {!compact && (
        <ul className="row-wrap" style={{ gap: 'var(--sp-3)', fontSize: 'var(--text-xs)' }}>
          {match.factors.map((f, i) => (
            <li key={f.factor} className="row" style={{ gap: 6 }} title={f.text}>
              <span
                aria-hidden
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 2,
                  background: factorColor(f.factor, i),
                  flexShrink: 0,
                }}
              />
              <span className="muted">{f.title}</span>
              <span className="mono">{f.contribution.toFixed(1)}</span>
            </li>
          ))}
        </ul>
      )}

      {!!match.penalty && match.penalty > 0 && match.base_score !== null && (
        <PenaltyNote match={match} base={match.base_score} />
      )}
    </div>
  );
}

/**
 * Снижение балла за условия. На бэкенде это множитель
 * (score = base × (1 − penalty)), но рядом стоят вклады факторов в баллах,
 * поэтому долю показывать нельзя: «−0.1» читается как «минус 0.1 балла»
 * вместо «минус 10% от всего». Показываем цену в баллах, а по кнопке
 * раскрываем, что именно не совпало и сколько стоила каждая причина.
 */
function PenaltyNote({ match, base }: { match: Match; base: number }) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return (
    <div className="stack-sm">
      <p className="penalty-line">
        Поправка на условия: −{(base - match.score).toFixed(1)} балла, {base.toFixed(1)} →{' '}
        {match.score.toFixed(1)}
        <button
          type="button"
          className="hint-btn"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((v) => !v)}
        >
          <span aria-hidden>?</span>
          <span className="sr-only">Почему снизился балл</span>
        </button>
      </p>
      {open && (
        <div className="hint-box" id={id}>
          <p>
            Балл снижается, когда пожелания кандидата расходятся с условиями места. Результат
            теста и подтверждённый грейд это не затрагивает
          </p>
          {match.penalty_reasons.length > 0 && (
            <ul className="hint-list">
              {match.penalty_reasons.map((r) => (
                <li key={r.title}>
                  <span>{r.title}</span>
                  <span className="mono">−{r.points.toFixed(1)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Зелёные «почему подходит» и жёлтые «что учесть». */
export function MatchNotes({ match }: { match: Match }) {
  if (!match.highlights.length && !match.warnings.length) return null;
  return (
    <div className="stack-sm">
      {match.highlights.map((h) => (
        <div key={h} className="row-top" style={{ gap: 'var(--sp-2)', fontSize: 'var(--text-sm)' }}>
          <span style={{ color: 'var(--green-500)' }} aria-hidden>
            ✓
          </span>
          <span>{h}</span>
        </div>
      ))}
      {match.warnings.map((w) => (
        <div key={w} className="row-top" style={{ gap: 'var(--sp-2)', fontSize: 'var(--text-sm)' }}>
          <span style={{ color: 'var(--amber-500)' }} aria-hidden>
            !
          </span>
          <span className="muted">{w}</span>
        </div>
      ))}
    </div>
  );
}

/** Крупный балл соответствия 0–100. */
export function ScoreDial({ value, caption }: { value: number; caption?: ReactNode }) {
  return (
    <div style={{ textAlign: 'center', minWidth: 76 }}>
      <div
        className="display"
        style={{ fontSize: 'var(--text-xl)', fontWeight: 800, color: 'var(--violet-600)' }}
      >
        {score(value)}
      </div>
      <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
        {caption ?? 'из 100'}
      </div>
    </div>
  );
}

// ---------------------------------------------------------- компетенции

/**
 * Компетенции с оценкой и достоверностью. Достоверность показываем словом
 * с бэкенда (`confidence_label`): она говорит, на скольких заданиях
 * основана оценка, и без неё процент читается как более точный, чем есть.
 */
export function CompetencyList({ items, limit }: { items: Competency[]; limit?: number }) {
  const shown = limit ? items.slice(0, limit) : items;
  if (!shown.length) return <p className="muted">Пока нет данных: компетенции появятся после теста</p>;

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Компетенция</th>
          <th style={{ width: '38%' }}>Оценка</th>
          <th className="table-num">Заданий</th>
          <th>Достоверность</th>
        </tr>
      </thead>
      <tbody>
        {shown.map((c) => (
          <tr key={c.competency}>
            <td>{c.title}</td>
            <td>
              <div className="row" style={{ gap: 'var(--sp-3)' }}>
                <span className="mono" style={{ minWidth: 40 }}>
                  {percent(c.estimate)}
                </span>
                <div style={{ flex: 1 }}>
                  <Meter value={c.estimate} label={c.title} />
                </div>
              </div>
            </td>
            <td className="table-num">{c.items}</td>
            <td className="muted">{c.confidence_label}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ------------------------------------------------------------------ ФСП

export function FspAchievementCard({ a }: { a: FspAchievement }) {
  const resultTone = a.result === 'winner' ? 'success' : a.result === 'prize' ? 'accent' : 'neutral';
  return (
    <div className="card" style={{ padding: 'var(--sp-4)' }}>
      <div className="row-wrap" style={{ marginBottom: 'var(--sp-2)' }}>
        <Badge tone={resultTone}>
          {a.result_title}
          {a.place ? ` · ${a.place} место` : ''}
        </Badge>
        <Badge tone="neutral">{a.event_level_title}</Badge>
        {a.verified && <Badge tone="success">Подтверждено ФСП</Badge>}
      </div>
      <div style={{ fontWeight: 600 }}>{a.event_name}</div>
      <div className="muted" style={{ fontSize: 'var(--text-sm)', marginTop: 4 }}>
        {a.discipline_title} · {date(a.event_date)}
      </div>
      {a.team_name && (
        <div className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 4 }}>
          Команда «{a.team_name}»{a.team_role === 'captain' ? ', капитан' : ''}
        </div>
      )}
    </div>
  );
}

/**
 * Блок достижений ФСП. Случай «истории нет» обязателен по ТЗ и оформляется
 * нейтрально: без нулей, красного цвета и намёка на недостаток.
 */
/**
 * Сводка ФСП: спортивный разряд, число соревнований и призовых мест.
 * Именно это учитывается в ранжировании — соревнования между собой не
 * сравниваются, роль в команде на вес не влияет.
 */
export function FspSummary({ stats, rank }: { stats?: FspStats; rank?: string | null }) {
  if (!stats && !rank) return null;
  return (
    <div className="row-wrap" style={{ fontSize: 'var(--text-sm)' }}>
      {rank && <Badge tone="accent">{rank}</Badge>}
      {stats && (
        <span className="muted">
          соревнований: {stats.competitions} · побед: {stats.wins} · призовых мест: {stats.podiums}
        </span>
      )}
    </div>
  );
}

export function FspBlock({ fsp }: { fsp: FspProfile | CandidateCard['fsp'] }) {
  const achievements = fsp.achievements ?? [];

  if (!fsp.linked || !achievements.length) {
    return (
      <Alert tone="neutral">
        {fsp.note ??
          (fsp.linked
            ? 'В реестре ФСП пока нет соревнований этого участника. Это не влияет на категорию'
            : 'Профиль ФСП ID не привязан. Это не влияет на категорию и грейд')}
      </Alert>
    );
  }

  return (
    <div className="stack-sm">
      <FspSummary stats={fsp.stats} rank={fsp.sport_rank_title} />
      {achievements.map((a, i) => (
        <FspAchievementCard key={`${a.event_name}-${i}`} a={a} />
      ))}
    </div>
  );
}

// --------------------------------------------------------- хронология

/**
 * Подпись события зависит от того, кто его совершил: «sent» от работодателя —
 * это приглашение, от кандидата — отклик. Сначала ищем пару «кто:что».
 */
const EVENT_TITLE: Record<string, string> = {
  'employer:sent': 'Приглашение отправлено',
  'candidate:viewed': 'Кандидат открыл приглашение',
  'candidate:accepted': 'Кандидат принял приглашение',
  'candidate:declined': 'Кандидат отклонил приглашение',
  'employer:withdrawn': 'Работодатель отозвал приглашение',
  'system:expired': 'Срок приглашения истёк',
  'candidate:sent': 'Отклик отправлен',
  'employer:viewed': 'Работодатель просмотрел отклик',
  'candidate:withdrawn': 'Кандидат отозвал отклик',
  'employer:invited': 'Работодатель пригласил на интервью',
  'employer:rejected': 'Работодатель отказал',
  'candidate:contacts_revoked': 'Кандидат закрыл доступ к контактам',
};
const ACTOR_TITLE: Record<string, string> = {
  candidate: 'кандидат',
  employer: 'работодатель',
  system: 'система',
};

export function Timeline({ events }: { events: TimelineEvent[] }) {
  if (!events?.length) return null;
  return (
    <ol className="stack-sm">
      {events.map((e, i) => (
        <li key={`${e.event}-${i}`} className="row-top" style={{ gap: 'var(--sp-3)' }}>
          <span
            aria-hidden
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              marginTop: 7,
              flexShrink: 0,
              background: i === events.length - 1 ? 'var(--violet-500)' : 'var(--line-300)',
            }}
          />
          <div>
            <div style={{ fontSize: 'var(--text-sm)' }}>
              {EVENT_TITLE[`${e.actor}:${e.event}`] ?? e.event}
              {ACTOR_TITLE[e.actor] && (
                <span className="faint"> · {ACTOR_TITLE[e.actor]}</span>
              )}
            </div>
            <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
              {dateTime(e.at)}
            </div>
            {e.note && (
              <div className="muted" style={{ fontSize: 'var(--text-sm)', marginTop: 2 }}>
                {e.note}
              </div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

// ------------------------------------------------- показатели компании

/** Что кандидат должен знать о компании до ответа на приглашение. */
export function TrustPanel({ trust }: { trust: CompanyTrust | null | undefined }) {
  if (!trust) return null;

  return (
    <div className="stack-sm">
      <div className="row-wrap">
        {trust.verified && <Badge tone="success">Компания проверена</Badge>}
        {trust.review_status === 'on_review' && <Badge tone="warn">На проверке</Badge>}
        {trust.review_status === 'blocked' && <Badge tone="danger">Заблокирована</Badge>}
        <span className="muted" style={{ fontSize: 'var(--text-xs)' }}>
          на платформе {count(trust.days_on_platform, 'день', 'дня', 'дней')}
        </span>
        <span className="muted" style={{ fontSize: 'var(--text-xs)' }}>
          · приглашений: {trust.invitations_sent}
        </span>
        {trust.acceptance_rate !== null && (
          <span className="muted" style={{ fontSize: 'var(--text-xs)' }}>
            · принимают {percent(trust.acceptance_rate)}
          </span>
        )}
        {trust.complaints_recent > 0 && (
          <span className="muted" style={{ fontSize: 'var(--text-xs)' }}>
            · жалоб за месяц: {trust.complaints_recent}
          </span>
        )}
      </div>
      {trust.warnings?.map((w) => (
        <div key={w} className="alert alert-warn">
          {w}
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------- карточка кандидата

/** Стек с обязательной подписью об источнике данных — требование ТЗ. */
export function StackChips({ stack }: { stack: { slug: string; title: string }[] }) {
  if (!stack?.length) return null;
  return (
    <div>
      <div className="row-wrap">
        {stack.map((s) => (
          <Chip key={s.slug}>{s.title}</Chip>
        ))}
      </div>
      <div className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 'var(--sp-2)' }}>
        заявлено кандидатом
      </div>
    </div>
  );
}

/** Контакты по правилам видимости: до принятия приглашения их нет. */
export function ContactsBlock({ c }: { c: CandidateCard }) {
  if (!c.contacts_visible) {
    return (
      <Card title="Контакты">
        <Alert tone="neutral">
          {c.contacts_note ??
            'Контакты откроются, когда кандидат примет приглашение или сам откликнется'}
        </Alert>
      </Card>
    );
  }

  const entries = Object.entries(c.contacts ?? {}).filter(([, v]) => v);
  return (
    <Card title="Контакты" subtitle={c.contacts_note ?? undefined}>
      {entries.length ? (
        <dl className="kv">
          {entries.map(([k, v]) => (
            <div key={k} style={{ display: 'contents' }}>
              <dt>{CONTACT_LABEL[k] ?? k}</dt>
              <dd className="mono">{v}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="muted">Кандидат не указал контактов в анкете</p>
      )}
    </Card>
  );
}

const CONTACT_LABEL: Record<string, string> = {
  full_name: 'ФИО',
  email: 'Почта',
  contact_email: 'Почта',
  phone: 'Телефон',
  telegram: 'Telegram',
};

// ------------------------------------------------------------ переписка

/**
 * Переписка по приглашению или отклику. Кандидат может уточнить условия до
 * принятия приглашения — контакты при этом не раскрываются.
 * `path` — адрес переписки без префикса, например
 * `/candidate/invitations/<id>/messages`.
 */
export function MessageThread({
  path,
  open,
  closedNote = 'Переписка закрыта: взаимодействие завершено',
}: {
  path: string;
  open: boolean;
  closedNote?: string;
}) {
  const thread = useAsync(() => api.get<Message[]>(path), [path]);
  const [text, setText] = useState('');
  const end = useRef<HTMLDivElement>(null);
  const send = useAction(async () => {
    const m = await api.post<Message>(path, { body: text });
    thread.set([...(thread.data ?? []), m]);
    setText('');
  });

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest' });
  }, [thread.data?.length]);

  const items = thread.data ?? [];
  return (
    <Card title="Переписка">
      <div className="stack-sm" style={{ maxHeight: 360, overflowY: 'auto' }}>
        {!items.length && (
          <div className="faint" style={{ fontSize: 'var(--text-sm)' }}>
            Сообщений пока нет
          </div>
        )}
        {items.map((m) => (
          <div
            key={m.id}
            style={{
              alignSelf: m.mine ? 'flex-end' : 'flex-start',
              maxWidth: '80%',
              padding: 'var(--sp-2) var(--sp-3)',
              borderRadius: 'var(--radius-md)',
              background: m.mine ? 'var(--violet-050)' : 'var(--paper-100, #f4f4f6)',
            }}
          >
            <div style={{ whiteSpace: 'pre-wrap', fontSize: 'var(--text-sm)' }}>{m.body}</div>
            <div className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 2 }}>
              {m.mine ? 'вы' : m.sender === 'candidate' ? 'кандидат' : 'компания'} · {dateTime(m.created_at)}
            </div>
          </div>
        ))}
        <div ref={end} />
      </div>
      {open ? (
        <form
          className="stack-sm"
          style={{ marginTop: 'var(--sp-3)' }}
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) void send.run();
          }}
        >
          <Textarea
            aria-label="Сообщение"
            rows={2}
            maxLength={2000}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Например: уточнить формат работы или этапы отбора"
          />
          <ErrorNote error={send.error} />
          <div>
            <Button type="submit" size="sm" disabled={!text.trim() || send.busy}>
              Отправить
            </Button>
          </div>
        </form>
      ) : (
        <div className="faint" style={{ fontSize: 'var(--text-sm)', marginTop: 'var(--sp-3)' }}>
          {closedNote}
        </div>
      )}
    </Card>
  );
}
