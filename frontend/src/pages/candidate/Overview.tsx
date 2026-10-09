import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { date, levelTitle } from '../../lib/format';
import { Alert, Card, ErrorNote, Loading, Meter, PageHeader } from '../../components/ui';
import { CompetencyList, InvitationStatusBadge, Salary } from '../../components/domain';
import type { AssessmentStatus, CandidateProfile, Consent, Invitation } from '../../api/types';

/** Порядок первого входа. Подсказку, где кандидат сейчас, даёт `next_step`. */
const STEP_HINT: Record<AssessmentStatus['next_step'], { title: string; text: string; to: string; cta: string }> = {
  survey: {
    title: 'Пройдите опрос',
    text: 'IT-направление, специализация и предполагаемый грейд – по ним соберётся персональный тест',
    to: '/candidate/assessment',
    cta: 'К опросу',
  },
  take_test: {
    title: 'Пройдите тест',
    text: 'Категория присваивается по результату теста, а не по словам в резюме',
    to: '/candidate/assessment',
    cta: 'Выбрать уровень',
  },
  continue_attempt: {
    title: 'Тест начат, но не завершён',
    text: 'Вернитесь к попытке: время идёт, ответы сохраняются автоматически',
    to: '/candidate/assessment',
    cta: 'Продолжить тест',
  },
  decide_recommendation: {
    title: 'Нужно ваше решение по уровню',
    text: 'Тест не подтвердил заявленный грейд, но есть рекомендация. Грейд без вашего согласия не меняется',
    to: '/candidate/assessment',
    cta: 'Посмотреть',
  },
  done: {
    title: 'Категория подтверждена',
    text: 'Вы в базе работодателей. Дальше они сами присылают приглашения с зарплатой',
    to: '/candidate/invitations',
    cta: 'Приглашения',
  },
};

export default function CandidateOverview() {
  const status = useAsync(() => api.get<AssessmentStatus>('/candidate/assessment/status'), []);
  const profile = useAsync(() => api.get<CandidateProfile>('/candidate/profile'), []);
  const invitations = useAsync(() => api.get<Invitation[]>('/candidate/invitations'), []);
  const consents = useAsync(() => api.get<Consent[]>('/candidate/consents'), []);

  if (status.loading || profile.loading) return <Loading rows={4} />;
  if (status.error) return <ErrorNote error={status.error} />;
  if (!status.data || !profile.data) return null;

  const s = status.data;
  const p = profile.data;
  const hint = STEP_HINT[s.next_step];

  // Без согласия на показ профиля кандидата не видно в подборках — это
  // самая частая причина «меня никто не приглашает», поэтому выносим наверх.
  const showConsent = consents.data?.find((c) => c.kind === 'profile_publication');
  const hidden = showConsent && !showConsent.granted;
  // до 18 лет включить показ можно только после согласия законного представителя
  const needsGuardian = p.minor && p.guardian?.status !== 'granted';

  const fresh = invitations.data?.filter((i) => i.status === 'sent') ?? [];

  return (
    <>
      <PageHeader
        title={p.full_name ? `Здравствуйте, ${p.full_name.split(' ')[0]}` : 'Кабинет кандидата'}
        subtitle="Вы заполняете профиль и подтверждаете категорию тестом. Дальше инициатива у работодателя"
      />

      <div className="stack">
        {hidden && needsGuardian && (
          <Alert tone="warn" title="Нужно согласие законного представителя">
            Вам меньше 18 лет: работодатели увидят профиль после согласия родителя или опекуна.{' '}
            <Link to="/candidate/profile">Отправить запрос в анкете</Link>
          </Alert>
        )}
        {hidden && !needsGuardian && (
          <Alert tone="warn" title="Профиль скрыт от работодателей">
            Вы не дали согласие на показ профиля, поэтому не попадаете в подборки.{' '}
            <Link to="/candidate/settings">Включить в настройках</Link>
          </Alert>
        )}

        {s.next_step !== 'done' ? (
          <Card title={hint.title} subtitle={hint.text}>
            <Link className="btn btn-primary" to={hint.to}>
              {hint.cta}
            </Link>
          </Card>
        ) : (
          s.grade && (
            /* Категория — главный результат кандидата, поэтому она подана
               фирменной тёмной панелью, а не рядовой карточкой. */
            <section className="ink grade-panel">
              <img className="art-line grade-line" src="/brand/lineline1.png" alt="" aria-hidden />
              <p className="eyebrow">Ваша категория</p>
              <div className="grade-main">
                <div>
                  <div className="grade-spec">
                    {s.specialization_title}
                    {s.track_title ? ` · ${s.track_title}` : ''}
                  </div>
                  <div className="grade-level">{levelTitle(s.grade.level)}</div>
                </div>
                <div className="grade-meta">
                  <div className="figure-label" style={{ marginTop: 0 }}>
                    Подтверждена тестом {date(s.grade.assigned_at)}
                  </div>
                  <Link className="btn btn-ink btn-sm" to="/candidate/assessment">
                    Разбор и история
                  </Link>
                </div>
              </div>
            </section>
          )
        )}

        <div className="grid-2">
          <Card
            title="Заполненность анкеты"
            actions={<span className="mono">{p.completeness}%</span>}
            subtitle="Чем полнее профиль, тем точнее подборка на стороне работодателя"
          >
            <Meter value={p.completeness / 100} label="Заполненность анкеты" />
            <div style={{ marginTop: 'var(--sp-4)' }}>
              <Link className="btn btn-secondary btn-sm" to="/candidate/profile">
                Дополнить анкету
              </Link>
            </div>
          </Card>

          <Card
            title="Новые приглашения"
            actions={<span className="mono">{fresh.length}</span>}
            subtitle={
              fresh.length
                ? 'Зарплата указана в каждом приглашении – решайте до начала общения'
                : 'Пока тихо. Приглашения приходят, когда работодатель находит вашу категорию'
            }
          >
            {fresh.slice(0, 2).map((i) => (
              <Link
                key={i.id}
                to={`/candidate/invitations/${i.id}`}
                style={{ color: 'inherit', textDecoration: 'none' }}
              >
                <div
                  className="card card-interactive"
                  style={{ padding: 'var(--sp-3)', marginBottom: 'var(--sp-2)' }}
                >
                  <div className="row" style={{ justifyContent: 'space-between' }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>{i.title}</div>
                      <div className="muted" style={{ fontSize: 'var(--text-xs)' }}>
                        {i.company.name}
                      </div>
                    </div>
                    <Salary from={i.salary_from} to={i.salary_to} size="md" />
                  </div>
                </div>
              </Link>
            ))}
            <Link className="btn btn-secondary btn-sm" to="/candidate/invitations">
              Все приглашения
            </Link>
          </Card>
        </div>

        {!!s.competencies?.length && (
          <Card
            title="Компетенции по итогам теста"
            subtitle="Достоверность показывает, на скольких заданиях основана оценка"
            actions={
              <Link className="btn btn-secondary btn-sm" to="/candidate/assessment">
                Подробно
              </Link>
            }
          >
            <CompetencyList items={s.competencies} limit={6} />
          </Card>
        )}

        {invitations.data && invitations.data.length > fresh.length && (
          <Card title="История приглашений">
            <table className="table">
              <tbody>
                {invitations.data
                  .filter((i) => i.status !== 'sent')
                  .slice(0, 5)
                  .map((i) => (
                    <tr key={i.id}>
                      <td>
                        <Link to={`/candidate/invitations/${i.id}`}>{i.title}</Link>
                        <div className="muted" style={{ fontSize: 'var(--text-xs)' }}>
                          {i.company.name} · {date(i.created_at)}
                        </div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <InvitationStatusBadge status={i.status} />
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </Card>
        )}

        {s.grade && s.policy && (
          <Card title="Правила смены грейда">
            <ul className="stack-sm" style={{ fontSize: 'var(--text-sm)' }}>
              <li className="muted">
                Менять грейд можно не чаще раза в {s.policy.grade_change_cooldown_days} дней
              </li>
              <li className="muted">
                Повторить тест того же уровня – через {s.policy.same_level_retry_days} дней
              </li>
              <li className="muted">
                В тесте {s.policy.test_size} заданий, на попытку {s.policy.attempt_time_limit_minutes}{' '}
                минут
              </li>
            </ul>
          </Card>
        )}

        {!!s.attempts?.length && (
          <Card title="Попытки">
            <table className="table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Заявленный уровень</th>
                  <th className="table-num">Балл</th>
                  <th>Итог</th>
                </tr>
              </thead>
              <tbody>
                {s.attempts.map((a) => (
                  <tr key={a.id}>
                    <td>{date(a.finished_at ?? a.started_at)}</td>
                    <td>{levelTitle(a.declared_level)}</td>
                    <td className="table-num">{a.score ?? '–'}</td>
                    <td className="muted">{a.applied?.message ?? a.outcome ?? 'в процессе'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </>
  );
}
