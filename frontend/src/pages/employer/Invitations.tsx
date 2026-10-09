import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction, useAsync } from '../../lib/useAsync';
import { date, dateTime, daysLeft, percent, salaryRange } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  Tabs,
} from '../../components/ui';
import {
  ContactsBlock,
  InvitationStatusBadge,
  MatchBreakdown,
  MatchNotes,
  MessageThread,
  Salary,
  Timeline,
} from '../../components/domain';
import type { CandidateCard, Invitation, InvitationStats } from '../../api/types';

const FUNNEL: { key: string; title: string }[] = [
  { key: 'sent', title: 'Отправлено' },
  { key: 'viewed', title: 'Просмотрено' },
  { key: 'accepted', title: 'Принято' },
  { key: 'declined', title: 'Отклонено' },
  { key: 'expired', title: 'Истекло' },
  { key: 'withdrawn', title: 'Отозвано' },
];

type Filter = 'all' | 'sent' | 'viewed' | 'accepted' | 'declined';

export function EmployerInvitationList() {
  const [filter, setFilter] = useState<Filter>('all');
  const list = useAsync(
    () => api.get<Invitation[]>('/employer/invitations', filter === 'all' ? undefined : { status: filter }),
    [filter],
  );
  const stats = useAsync(() => api.get<InvitationStats>('/employer/invitations-stats'), []);

  return (
    <>
      <PageHeader
        title="Приглашения"
        subtitle="Выход на контакт по инициативе работодателя. Контакты кандидата открываются после принятия"
      />

      <div className="stack">
        {stats.data && (
          <Card title="Воронка" subtitle={`Всего приглашений: ${stats.data.total}`}>
            <div className="row-wrap" style={{ gap: 'var(--sp-5)' }}>
              {FUNNEL.map((f) => (
                <div key={f.key}>
                  <div className="field-label">{f.title}</div>
                  <div className="display" style={{ fontSize: 'var(--text-lg)', fontWeight: 700 }}>
                    {stats.data!.by_status[f.key] ?? 0}
                  </div>
                </div>
              ))}
              {stats.data.acceptance_rate !== null && (
                <div>
                  <div className="field-label">Принимают</div>
                  <div
                    className="display"
                    style={{ fontSize: 'var(--text-lg)', fontWeight: 700, color: 'var(--green-700)' }}
                  >
                    {percent(stats.data.acceptance_rate)}
                  </div>
                </div>
              )}
            </div>

            {!!stats.data.decline_reasons.length && (
              <div style={{ marginTop: 'var(--sp-5)' }}>
                <div className="field-label" style={{ marginBottom: 'var(--sp-2)' }}>
                  Почему отказываются
                </div>
                <table className="table">
                  <tbody>
                    {stats.data.decline_reasons.map((r) => (
                      <tr key={r.reason}>
                        <td>{r.title}</td>
                        <td className="table-num">{r.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        <Tabs<Filter>
          value={filter}
          onChange={setFilter}
          tabs={[
            { id: 'all', label: 'Все' },
            { id: 'sent', label: 'Отправленные' },
            { id: 'viewed', label: 'Просмотренные' },
            { id: 'accepted', label: 'Принятые' },
            { id: 'declined', label: 'Отклонённые' },
          ]}
        />

        {list.loading && <Loading rows={3} />}
        <ErrorNote error={list.error} />

        {list.data && !list.data.length && (
          <Empty
            title="Приглашений нет"
            action={
              <Link className="btn btn-primary" to="/employer/selection">
                Открыть подборку
              </Link>
            }
          >
            Найдите кандидата в подборке и отправьте предложение с вилкой зарплаты
          </Empty>
        )}

        {list.data?.map((i) => (
          <Link
            key={i.id}
            to={`/employer/invitations/${i.id}`}
            style={{ color: 'inherit', textDecoration: 'none' }}
          >
            <article className="card card-interactive">
              <div className="row-top" style={{ justifyContent: 'space-between' }}>
                <div className="stack-sm" style={{ minWidth: 0 }}>
                  <div className="row-wrap">
                    <strong style={{ fontFamily: 'var(--font-display)' }}>{i.candidate_name}</strong>
                    <InvitationStatusBadge status={i.status} />
                    {!!i.unread_messages && <Badge tone="accent">Новых сообщений: {i.unread_messages}</Badge>}
                  </div>
                  <div className="muted" style={{ fontSize: 'var(--text-sm)' }}>
                    {i.title}
                  </div>
                  <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                    отправлено {date(i.created_at)}
                    {i.expires_at ? ` · действует до ${date(i.expires_at)}` : ''}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className="salary salary-md">{salaryRange(i.salary_from, i.salary_to)}</div>
                  {i.match && (
                    <div className="faint mono" style={{ fontSize: 'var(--text-xs)', marginTop: 4 }}>
                      соответствие {Math.round(i.match.score)}
                    </div>
                  )}
                </div>
              </div>
            </article>
          </Link>
        ))}
      </div>
    </>
  );
}

export function EmployerInvitationDetail() {
  const { id } = useParams<{ id: string }>();
  const { title: refTitle } = useReference();
  const { data, loading, error, reload } = useAsync(
    () => api.get<Invitation>(`/employer/invitations/${id}`),
    [id],
  );
  // Контакты отдаёт карточка кандидата (просмотр пишется в журнал аудита), а не приглашение
  const card = useAsync(
    () =>
      data?.contacts_visible
        ? api.get<CandidateCard>(`/employer/candidates/${data.candidate_id}`)
        : Promise.resolve(undefined),
    [data?.contacts_visible, data?.candidate_id],
  );

  const withdraw = useAction(async () => {
    await api.post(`/employer/invitations/${id}/withdraw`);
    reload();
  });

  if (loading) return <Loading rows={4} />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  const open = data.status === 'sent' || data.status === 'viewed';

  return (
    <>
      <Link to="/employer/invitations" className="muted" style={{ fontSize: 'var(--text-sm)' }}>
        ← Все приглашения
      </Link>

      <div className="stack" style={{ marginTop: 'var(--sp-4)' }}>
        <Card>
          <div className="row-top" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
            <div className="stack-sm">
              <h1 className="page-title">{data.title}</h1>
              <div className="row-wrap">
                <Link to={`/employer/candidates/${data.candidate_id}`}>{data.candidate_name}</Link>
                <InvitationStatusBadge status={data.status} />
              </div>
            </div>
            <Salary from={data.salary_from} to={data.salary_to} size="lg" />
          </div>
        </Card>

        {data.status === 'accepted' &&
          (!data.contacts_visible ? (
            <Alert tone="neutral" title="Контакты закрыты">
              Кандидат закрыл компании доступ к своим контактам
            </Alert>
          ) : card.data ? (
            <ContactsBlock c={card.data} />
          ) : (
            <Card title="Контакты">
              {card.loading ? <Loading rows={1} /> : <ErrorNote error={card.error} />}
            </Card>
          ))}

        {data.status === 'declined' && (
          <Alert tone="neutral" title="Кандидат отклонил приглашение">
            {data.decline_reason_title ?? ''}
            {data.decline_comment ? ` – ${data.decline_comment}` : ''}
          </Alert>
        )}

        <Card title="Текст предложения">
          <p style={{ whiteSpace: 'pre-line' }}>{data.description}</p>
          <dl className="kv" style={{ marginTop: 'var(--sp-4)' }}>
            <dt>Способ связи</dt>
            <dd>{data.contact_method}</dd>
            {data.work_format && (
              <>
                <dt>Формат</dt>
                <dd>{refTitle('work_formats', data.work_format)}</dd>
              </>
            )}
          </dl>
        </Card>

        {data.match && (
          <Card
            title="Почему этот кандидат"
            subtitle="Эти же пункты кандидат видит в приглашении как «почему вас пригласили»"
          >
            <MatchBreakdown match={data.match} />
            <div style={{ marginTop: 'var(--sp-4)' }}>
              <MatchNotes match={data.match} />
            </div>
          </Card>
        )}

        <MessageThread
          path={`/employer/invitations/${data.id}/messages`}
          open={open || data.status === 'accepted'}
        />

        <Card title="Хронология">
          <Timeline events={data.timeline} />
          <p className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 'var(--sp-3)' }}>
            Отправлено {dateTime(data.created_at)}
            {data.viewed_at ? ` · просмотрено ${dateTime(data.viewed_at)}` : ''}
            {data.expires_at ? ` · осталось ${daysLeft(data.expires_at)}` : ''}
          </p>
        </Card>

        {open && (
          <Card title="Действия">
            <ErrorNote error={withdraw.error} />
            <Button variant="danger" busy={withdraw.busy} onClick={() => void withdraw.run()}>
              Отозвать приглашение
            </Button>
          </Card>
        )}
      </div>
    </>
  );
}
