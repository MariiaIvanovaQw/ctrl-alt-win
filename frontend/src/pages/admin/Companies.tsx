import { useState } from 'react';
import { api } from '../../api/client';
import { useAction, useAsync } from '../../lib/useAsync';
import { dateTime } from '../../lib/format';
import { CabinetLayout } from '../../components/Layout';
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
  Tabs,
  Textarea,
} from '../../components/ui';
import type { AdminCompany, AdminComplaint } from '../../api/types';

export function AdminCabinet() {
  return (
    <CabinetLayout
      groups={[{ items: [{ to: '/admin/companies', label: 'Компании', end: true }] }]}
    />
  );
}

/** Жалобы кандидатов на конкретную компанию. */
function Complaints({ companyId }: { companyId: string }) {
  const { data, loading, error } = useAsync(
    () => api.get<AdminComplaint[]>(`/admin/companies/${companyId}/complaints`),
    [companyId],
  );

  if (loading) return <Loading rows={1} />;
  if (error) return <ErrorNote error={error} />;
  if (!data?.length) return <p className="muted">Жалоб нет</p>;

  return (
    <ul className="stack-sm">
      {data.map((c) => (
        <li key={c.id} className="card" style={{ padding: 'var(--sp-3)' }}>
          <div className="row-wrap">
            <Badge tone="warn">{c.reason_title ?? c.reason}</Badge>
            <span className="faint" style={{ fontSize: 'var(--text-xs)' }}>
              {dateTime(c.created_at)}
            </span>
          </div>
          {c.comment && (
            <p style={{ fontSize: 'var(--text-sm)', marginTop: 'var(--sp-2)' }}>{c.comment}</p>
          )}
        </li>
      ))}
    </ul>
  );
}

type Status = 'on_review' | 'active' | 'blocked' | 'verification';

/** Заявки на добровольную метку «Компания проверена». */
function VerificationRequests() {
  const { data, loading, error, reload } = useAsync(
    () => api.get<AdminCompany[]>('/admin/verification-requests'),
    [],
  );
  const [comment, setComment] = useState<Record<string, string>>({});
  const decide = useAction(async (id: string, approve: boolean) => {
    await api.post(`/admin/companies/${id}/verification`, { approve, comment: comment[id] || null });
    reload();
  });

  if (loading) return <Loading rows={2} />;
  if (error) return <ErrorNote error={error} />;
  if (!data?.length) return <Empty title="Заявок нет">Новые заявки на проверку появятся здесь</Empty>;

  return (
    <>
      <ErrorNote error={decide.error} />
      {data.map((c) => (
        <Card
          key={c.id}
          title={c.name}
          subtitle={c.verification_requested_at ? `Заявка от ${dateTime(c.verification_requested_at)}` : undefined}
        >
          <dl className="kv">
            <dt>ИНН</dt>
            <dd className="mono">{c.inn ?? '–'}</dd>
            <dt>Сайт</dt>
            <dd>{c.website ?? '–'}</dd>
          </dl>
          <p className="muted" style={{ fontSize: 'var(--text-sm)', margin: 'var(--sp-3) 0' }}>
            Сверьте ИНН и название с выпиской ЕГРЮЛ (egrul.nalog.ru) и сайтом компании
          </p>
          <Field label="Комментарий" hint="При отказе его увидит компания">
            {(p) => (
              <Textarea
                {...p}
                value={comment[c.id] ?? ''}
                onChange={(e) => setComment((m) => ({ ...m, [c.id]: e.target.value }))}
              />
            )}
          </Field>
          <div className="row-wrap" style={{ marginTop: 'var(--sp-3)' }}>
            <Button variant="primary" size="sm" busy={decide.busy} onClick={() => void decide.run(c.id, true)}>
              Выдать метку
            </Button>
            <Button size="sm" busy={decide.busy} onClick={() => void decide.run(c.id, false)}>
              Отказать
            </Button>
          </div>
        </Card>
      ))}
    </>
  );
}

export default function AdminCompanies() {
  const [status, setStatus] = useState<Status>('on_review');
  const { data, loading, error, reload } = useAsync(
    () =>
      status === 'verification'
        ? Promise.resolve(null)
        : api.get<AdminCompany[]>('/admin/companies', { status }),
    [status],
  );

  const [deciding, setDeciding] = useState<{ company: AdminCompany; decision: 'restore' | 'block' } | null>(
    null,
  );
  const [comment, setComment] = useState('');
  const [open, setOpen] = useState<string | null>(null);

  const decide = useAction(async () => {
    if (!deciding) return;
    await api.post(`/admin/companies/${deciding.company.id}/review`, {
      decision: deciding.decision,
      comment: comment || null,
    });
    setDeciding(null);
    setComment('');
    reload();
  });

  return (
    <>
      <PageHeader
        title="Модерация компаний"
        subtitle="Компании на проверке после жалоб кандидатов и заявки на добровольную метку «Компания проверена»"
      />

      <div className="stack">
        <Tabs<Status>
          value={status}
          onChange={setStatus}
          tabs={[
            { id: 'on_review', label: 'На проверке' },
            { id: 'active', label: 'Активные' },
            { id: 'blocked', label: 'Заблокированные' },
            { id: 'verification', label: 'Заявки на проверку' },
          ]}
        />

        {status === 'verification' && <VerificationRequests />}

        {loading && <Loading rows={2} />}
        <ErrorNote error={error} />
        <ErrorNote error={decide.error} />

        {status !== 'verification' && data && !data.length && (
          <Empty title="Пусто">
            {status === 'on_review'
              ? 'Компаний на проверке нет – жалоб недостаточно для приостановки'
              : 'В этом статусе компаний нет'}
          </Empty>
        )}

        {data?.map((c) => (
          <Card
            key={c.id}
            title={c.name}
            subtitle={
              c.review_reason ??
              (c.reviewed_at ? `Решение от ${dateTime(c.reviewed_at)}` : undefined)
            }
            actions={
              <>
                <Badge tone={c.complaints ? 'warn' : 'neutral'}>жалоб: {c.complaints}</Badge>
                <Button
                  size="sm"
                  onClick={() => setOpen((cur) => (cur === c.id ? null : c.id))}
                >
                  {open === c.id ? 'Скрыть' : 'Жалобы'}
                </Button>
              </>
            }
          >
            {open === c.id && (
              <div style={{ marginBottom: 'var(--sp-4)' }}>
                <Complaints companyId={c.id} />
              </div>
            )}

            {status === 'on_review' && (
              <div className="row-wrap">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setDeciding({ company: c, decision: 'restore' })}
                >
                  Восстановить
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => setDeciding({ company: c, decision: 'block' })}
                >
                  Заблокировать
                </Button>
              </div>
            )}
          </Card>
        ))}

        <Alert tone="neutral">
          На проверку компания попадает автоматически, когда за месяц набирается достаточно жалоб
          кандидатов. До решения модератора её приглашения и публикации приостановлены
        </Alert>
      </div>

      {deciding && (
        <Modal
          title={
            deciding.decision === 'restore'
              ? `Восстановить «${deciding.company.name}»`
              : `Заблокировать «${deciding.company.name}»`
          }
          onClose={() => setDeciding(null)}
          footer={
            <>
              <Button onClick={() => setDeciding(null)}>Отмена</Button>
              <Button
                variant={deciding.decision === 'restore' ? 'primary' : 'danger'}
                busy={decide.busy}
                onClick={() => void decide.run()}
              >
                Подтвердить
              </Button>
            </>
          }
        >
          <div className="stack">
            <Field label="Комментарий" hint="Останется в журнале модерации">
              {(p) => (
                <Textarea {...p} value={comment} onChange={(e) => setComment(e.target.value)} />
              )}
            </Field>
            <ErrorNote error={decide.error} />
          </div>
        </Modal>
      )}
    </>
  );
}
