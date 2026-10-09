import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAction, useAsync } from '../../lib/useAsync';
import { candidateLink } from '../../lib/links';
import { date, levelTitle, salaryRange, years } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Empty,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
  Textarea,
} from '../../components/ui';
import {
  ApplicationStatusBadge,
  MatchBreakdown,
  MatchNotes,
  MessageThread,
  Salary,
  Timeline,
} from '../../components/domain';
import type { Application } from '../../api/types';

/** Ответ на отклик: пригласить на интервью или отказать с комментарием. */
function RespondModal({
  application,
  decision,
  onClose,
  onDone,
}: {
  application: Application;
  decision: 'invited' | 'rejected';
  onClose: () => void;
  onDone: () => void;
}) {
  const [comment, setComment] = useState('');
  const submit = useAction(async () => {
    await api.post(`/employer/applications/${application.id}/respond`, {
      status: decision,
      comment: comment || null,
    });
    onDone();
  });

  return (
    <Modal
      title={decision === 'invited' ? 'Пригласить на интервью' : 'Отказать по отклику'}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button
            variant={decision === 'invited' ? 'primary' : 'danger'}
            busy={submit.busy}
            onClick={() => void submit.run()}
          >
            {decision === 'invited' ? 'Пригласить' : 'Отказать'}
          </Button>
        </>
      }
    >
      <div className="stack">
        <Field
          label="Комментарий кандидату"
          hint={
            decision === 'invited'
              ? 'Напишите, как и когда свяжетесь'
              : 'Понятная причина отказа экономит время обеим сторонам'
          }
        >
          {(p) => (
            <Textarea {...p} value={comment} onChange={(e) => setComment(e.target.value)} />
          )}
        </Field>
        <ErrorNote error={submit.error} />
      </div>
    </Modal>
  );
}

export default function EmployerApplications() {
  const { data, loading, error, reload } = useAsync(
    () => api.get<Application[]>('/employer/applications'),
    [],
  );
  const [chatFor, setChatFor] = useState<string | null>(null);
  const [acting, setActing] = useState<{ app: Application; decision: 'invited' | 'rejected' } | null>(
    null,
  );

  if (loading) return <Loading rows={3} />;
  if (error) return <ErrorNote error={error} />;

  return (
    <>
      <PageHeader
        title="Отклики"
        subtitle="Кандидат проявил инициативу сам, поэтому его контакты открыты сразу. Балл соответствия считается по той же механике, что и в подборке"
      />

      {!data?.length ? (
        <Empty
          title="Откликов нет"
          action={
            <Link className="btn btn-primary" to="/employer/needs">
              Опубликовать вакансию
            </Link>
          }
        >
          Отклики приходят только на опубликованные потребности
        </Empty>
      ) : (
        <div className="stack">
          {data.map((a) => (
            <article key={a.id} className="card">
              <div className="row-top" style={{ justifyContent: 'space-between' }}>
                <div className="stack-sm" style={{ minWidth: 0 }}>
                  <div className="row-wrap">
                    {a.candidate ? (
                      <Link
                        to={candidateLink(a.candidate)}
                        style={{ fontFamily: 'var(--font-display)', fontWeight: 600, color: 'inherit' }}
                      >
                        {a.candidate.display_name}
                      </Link>
                    ) : (
                      <strong>Кандидат</strong>
                    )}
                    <ApplicationStatusBadge status={a.status} />
                    {a.candidate?.category && (
                      <Badge tone="accent">
                        {a.candidate.category.specialization_title} ·{' '}
                        {levelTitle(a.candidate.category.level)}
                      </Badge>
                    )}
                  </div>

                  <div className="muted" style={{ fontSize: 'var(--text-sm)' }}>
                    на «{a.vacancy.title}» · {date(a.created_at)}
                  </div>

                  {a.candidate && (
                    <div className="row-wrap muted" style={{ fontSize: 'var(--text-sm)' }}>
                      {a.candidate.city && <span>{a.candidate.city}</span>}
                      <span>· опыт {years(a.candidate.experience_years)}</span>
                      {a.candidate.salary_expectation && (
                        <span>· ожидает {salaryRange(a.candidate.salary_expectation, null)}</span>
                      )}
                    </div>
                  )}
                </div>

                <Salary from={a.vacancy.salary_from} to={a.vacancy.salary_to} size="md" />
              </div>

              {a.cover_letter && (
                <div style={{ marginTop: 'var(--sp-3)' }}>
                  <div className="field-label">Сопроводительное письмо</div>
                  <p style={{ fontSize: 'var(--text-sm)', whiteSpace: 'pre-line' }}>
                    {a.cover_letter}
                  </p>
                </div>
              )}

              {a.match && (
                <div className="stack-sm" style={{ marginTop: 'var(--sp-4)' }}>
                  <MatchBreakdown match={a.match} />
                  <MatchNotes match={a.match} />
                </div>
              )}

              {a.employer_comment && (
                <div style={{ marginTop: 'var(--sp-3)' }}>
                  <Alert tone="neutral" title="Ваш ответ">
                    {a.employer_comment}
                  </Alert>
                </div>
              )}

              <div style={{ marginTop: 'var(--sp-4)' }}>
                <Timeline events={a.timeline} />
              </div>

              <div style={{ marginTop: 'var(--sp-3)' }}>
                <Button size="sm" variant="ghost" onClick={() => setChatFor(chatFor === a.id ? null : a.id)}>
                  {chatFor === a.id ? 'Скрыть переписку' : 'Переписка'}
                  {a.unread_messages ? ` · новых: ${a.unread_messages}` : ''}
                </Button>
                {chatFor === a.id && (
                  <div style={{ marginTop: 'var(--sp-3)' }}>
                    <MessageThread
                      path={`/employer/applications/${a.id}/messages`}
                      open={['sent', 'viewed', 'invited'].includes(a.status)}
                    />
                  </div>
                )}
              </div>

              {(a.status === 'sent' || a.status === 'viewed') && (
                <div className="row-wrap" style={{ marginTop: 'var(--sp-4)' }}>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => setActing({ app: a, decision: 'invited' })}
                  >
                    Пригласить на интервью
                  </Button>
                  <Button size="sm" onClick={() => setActing({ app: a, decision: 'rejected' })}>
                    Отказать
                  </Button>
                  {a.candidate && (
                    <Link
                      className="btn btn-ghost btn-sm"
                      to={candidateLink(a.candidate)}
                    >
                      Открыть карточку
                    </Link>
                  )}
                </div>
              )}
            </article>
          ))}
        </div>
      )}

      {acting && (
        <RespondModal
          application={acting.app}
          decision={acting.decision}
          onClose={() => setActing(null)}
          onDone={() => {
            setActing(null);
            reload();
          }}
        />
      )}
    </>
  );
}
