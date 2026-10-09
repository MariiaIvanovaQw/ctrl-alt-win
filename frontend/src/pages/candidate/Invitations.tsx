import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction, useAsync } from '../../lib/useAsync';
import { date, dateTime, levelTitle } from '../../lib/format';
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
  Select,
  Textarea,
} from '../../components/ui';
import { InvitationStatusBadge, MessageThread, Salary, Timeline, TrustPanel } from '../../components/domain';
import type { Invitation } from '../../api/types';

export function InvitationList() {
  const { data, loading, error } = useAsync(() => api.get<Invitation[]>('/candidate/invitations'), []);

  if (loading) return <Loading rows={3} />;
  if (error) return <ErrorNote error={error} />;

  return (
    <>
      <PageHeader
        title="Приглашения"
        subtitle="Работодатель сам выходит на контакт и обязан указать вилку зарплаты. Вы решаете, начинать ли общение"
      />

      {!data?.length ? (
        <Empty title="Приглашений пока нет">
          Они появятся, когда работодатель найдёт вашу категорию. Убедитесь, что согласие на показ
          профиля включено в <Link to="/candidate/settings">настройках</Link>
        </Empty>
      ) : (
        <div className="stack">
          {data.map((i) => (
            <Link
              key={i.id}
              to={`/candidate/invitations/${i.id}`}
              style={{ color: 'inherit', textDecoration: 'none' }}
            >
              <article className="card card-interactive">
                {/* Вилка стоит первой: кандидат видит условия до начала общения. */}
                <div className="row-top" style={{ justifyContent: 'space-between' }}>
                  <Salary from={i.salary_from} to={i.salary_to} size="lg" />
                  <div className="row-wrap">
                    {!!i.unread_messages && <Badge tone="accent">Новых сообщений: {i.unread_messages}</Badge>}
                    <InvitationStatusBadge status={i.status} />
                  </div>
                </div>

                <h3 style={{ marginTop: 'var(--sp-3)' }}>{i.title}</h3>
                <div className="row-wrap muted" style={{ fontSize: 'var(--text-sm)', marginTop: 4 }}>
                  <span>{i.company.name}</span>
                  {i.need && (
                    <>
                      <span>·</span>
                      <span>{levelTitle(i.need.level)}</span>
                    </>
                  )}
                  <span>·</span>
                  <span>{date(i.created_at)}</span>
                  {i.expires_at && (
                    <>
                      <span>·</span>
                      <span>действует до {date(i.expires_at)}</span>
                    </>
                  )}
                </div>

                {!!i.company_trust?.warnings.length && (
                  <div className="row-wrap" style={{ marginTop: 'var(--sp-3)' }}>
                    {i.company_trust.warnings.map((w) => (
                      <Badge key={w} tone="warn">
                        {w}
                      </Badge>
                    ))}
                  </div>
                )}
              </article>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

/** Отказ с причиной из справочника — работодатель видит обобщённую статистику. */
function DeclineModal({
  invitationId,
  onClose,
  onDone,
}: {
  invitationId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const reasons = useAsync(() => api.get<Record<string, string>>('/candidate/decline-reasons'), []);
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');

  const submit = useAction(async () => {
    await api.post(`/candidate/invitations/${invitationId}/decline`, {
      reason,
      comment: comment || null,
    });
    onDone();
  });

  return (
    <Modal
      title="Отклонить приглашение"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" busy={submit.busy} disabled={!reason} onClick={() => void submit.run()}>
            Отклонить
          </Button>
        </>
      }
    >
      <div className="stack">
        <Field label="Причина" required>
          {(p) => (
            <Select {...p} value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="">Выберите…</option>
              {Object.entries(reasons.data ?? {}).map(([slug, title]) => (
                <option key={slug} value={slug}>
                  {title}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Комментарий" hint="Необязательно. Поможет работодателю скорректировать предложение">
          {(p) => (
            <Textarea {...p} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} />
          )}
        </Field>
        <ErrorNote error={submit.error} />
      </div>
    </Modal>
  );
}

/** Жалоба на приглашение — часть защиты от недобросовестных работодателей. */
function ComplaintModal({
  invitationId,
  onClose,
}: {
  invitationId: string;
  onClose: () => void;
}) {
  const reasons = useAsync(() => api.get<Record<string, string>>('/candidate/complaint-reasons'), []);
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');
  const [done, setDone] = useState(false);

  const submit = useAction(async () => {
    await api.post('/candidate/complaints', {
      invitation_id: invitationId,
      reason,
      comment: comment || null,
    });
    setDone(true);
  });

  return (
    <Modal
      title="Пожаловаться на приглашение"
      onClose={onClose}
      footer={
        done ? (
          <Button variant="primary" onClick={onClose}>
            Закрыть
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>Отмена</Button>
            <Button
              variant="primary"
              busy={submit.busy}
              disabled={!reason}
              onClick={() => void submit.run()}
            >
              Отправить жалобу
            </Button>
          </>
        )
      }
    >
      {done ? (
        <Alert tone="success" title="Спасибо">
          Жалоба отправлена на модерацию. Если жалоб на компанию накопится достаточно, её приглашения
          и публикации приостановят до проверки
        </Alert>
      ) : (
        <div className="stack">
          <Field label="Что не так" required>
            {(p) => (
              <Select {...p} value={reason} onChange={(e) => setReason(e.target.value)}>
                <option value="">Выберите…</option>
                {Object.entries(reasons.data ?? {}).map(([slug, title]) => (
                  <option key={slug} value={slug}>
                    {title}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Подробности">
            {(p) => (
              <Textarea
                {...p}
                maxLength={1000}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
            )}
          </Field>
          <ErrorNote error={submit.error} />
        </div>
      )}
    </Modal>
  );
}

export function InvitationDetail() {
  const { id } = useParams<{ id: string }>();
  const { title: refTitle } = useReference();
  const { data, loading, error, reload } = useAsync(
    () => api.get<Invitation>(`/candidate/invitations/${id}`),
    [id],
  );

  const [declining, setDeclining] = useState(false);
  const [complaining, setComplaining] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [message, setMessage] = useState('');

  const accept = useAction(async () => {
    await api.post(`/candidate/invitations/${id}/accept`, { message: message || null });
    setAccepting(false);
    reload();
  });

  const revoke = useAction(async () => {
    await api.post(`/candidate/invitations/${id}/revoke-contacts`);
    reload();
  });

  if (loading) return <Loading rows={4} />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  const open = data.status === 'sent' || data.status === 'viewed';

  return (
    <>
      <Link to="/candidate/invitations" className="muted" style={{ fontSize: 'var(--text-sm)' }}>
        ← Все приглашения
      </Link>

      <div className="stack" style={{ marginTop: 'var(--sp-4)' }}>
        <Card>
          {/* Зарплата — первое, что видит кандидат. */}
          <div className="row-top" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
            <div className="stack-sm">
              <Salary
                from={data.salary_from}
                to={data.salary_to}
                size="lg"
                warnings={data.salary_warnings}
              />
              <h1 className="page-title">{data.title}</h1>
              <div className="row-wrap muted" style={{ fontSize: 'var(--text-sm)' }}>
                <span>{data.company.name}</span>
                {data.company.city && (
                  <>
                    <span>·</span>
                    <span>{data.company.city}</span>
                  </>
                )}
                {data.work_format && (
                  <>
                    <span>·</span>
                    <span>{refTitle('work_formats', data.work_format)}</span>
                  </>
                )}
              </div>
            </div>
            <InvitationStatusBadge status={data.status} />
          </div>
        </Card>

        {data.status === 'accepted' && data.contacts_shared !== false && (
          <Alert tone="success" title="Вы приняли приглашение">
            Работодателю открылись ваши контакты. Способ связи с его стороны:{' '}
            <strong>{data.contact_method}</strong>.
            <div style={{ marginTop: 'var(--sp-3)' }}>
              <Button size="sm" variant="ghost" busy={revoke.busy} onClick={() => void revoke.run()}>
                Закрыть компании доступ к контактам
              </Button>
              <span className="faint" style={{ fontSize: 'var(--text-xs)', marginLeft: 'var(--sp-2)' }}>
                Платформа перестанет их показывать; то, что компания уже сохранила, отозвать нельзя
              </span>
            </div>
            <ErrorNote error={revoke.error} />
          </Alert>
        )}
        {data.status === 'accepted' && data.contacts_shared === false && (
          <Alert tone="neutral" title="Доступ к контактам закрыт">
            Вы закрыли компании доступ к контактам {data.contacts_revoked_at ? dateTime(data.contacts_revoked_at) : ''}.
            Переписка на платформе остаётся доступной
          </Alert>
        )}
        {data.status === 'declined' && (
          <Alert tone="neutral" title="Вы отклонили приглашение">
            {/* Кандидату приходит только слаг причины — название берём из справочника. */}
            {data.decline_reason_title ?? refTitle('decline_reasons', data.decline_reason)}
            {data.decline_comment ? ` – ${data.decline_comment}` : ''}
          </Alert>
        )}
        {data.status === 'withdrawn' && (
          <Alert tone="neutral">Работодатель отозвал приглашение</Alert>
        )}
        {data.status === 'expired' && <Alert tone="neutral">Срок приглашения истёк</Alert>}

        <Card title="Предложение">
          <p style={{ whiteSpace: 'pre-line' }}>{data.description}</p>
          {data.expires_at && open && (
            <p className="muted" style={{ fontSize: 'var(--text-sm)', marginTop: 'var(--sp-3)' }}>
              Ответить можно до {date(data.expires_at)}
            </p>
          )}
        </Card>

        {!!data.why_you?.length && (
          <Card
            title="Почему вас пригласили"
            subtitle="Эти пункты платформа показала работодателю вместе с вашей карточкой"
          >
            <ul className="stack-sm">
              {data.why_you.map((w) => (
                <li key={w} className="row-top" style={{ gap: 'var(--sp-2)', fontSize: 'var(--text-sm)' }}>
                  <span style={{ color: 'var(--green-500)' }} aria-hidden>
                    ✓
                  </span>
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}

        <Card title="О компании">
          {data.company.description && (
            <p className="muted" style={{ fontSize: 'var(--text-sm)', marginBottom: 'var(--sp-3)' }}>
              {data.company.description}
            </p>
          )}
          <TrustPanel trust={data.company_trust} />
        </Card>

        {open ? (
          <Card title="Ваш ответ" subtitle="Контакты откроются работодателю только после принятия">
            <ErrorNote error={accept.error} />
            <div className="row-wrap">
              <Button variant="primary" size="lg" onClick={() => setAccepting(true)}>
                Принять приглашение
              </Button>
              <Button size="lg" onClick={() => setDeclining(true)}>
                Отклонить
              </Button>
              <Button variant="ghost" onClick={() => setComplaining(true)}>
                Пожаловаться
              </Button>
            </div>
          </Card>
        ) : (
          /* Пожаловаться можно и после ответа: именно на недобросовестное
             предложение жалуются уже отклонив его. */
          <Card title="Что-то не так с предложением?">
            <Button variant="ghost" onClick={() => setComplaining(true)}>
              Пожаловаться на приглашение
            </Button>
          </Card>
        )}

        {/* Вопросы можно задать до принятия — контакты при этом не раскрываются. */}
        <MessageThread
          path={`/candidate/invitations/${data.id}/messages`}
          open={open || data.status === 'accepted'}
        />

        <Card title="Хронология">
          <Timeline events={data.timeline} />
          <p className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 'var(--sp-3)' }}>
            Отправлено {dateTime(data.created_at)}
          </p>
        </Card>
      </div>

      {accepting && (
        <Modal
          title="Принять приглашение"
          onClose={() => setAccepting(false)}
          footer={
            <>
              <Button onClick={() => setAccepting(false)}>Отмена</Button>
              <Button variant="primary" busy={accept.busy} onClick={() => void accept.run()}>
                Принять
              </Button>
            </>
          }
        >
          <div className="stack">
            <Alert tone="info">
              После принятия работодатель увидит ваши контактные данные: ФИО, почту, телефон и
              Telegram из анкеты
            </Alert>
            <Field label="Сообщение работодателю" hint="Необязательно.">
              {(p) => (
                <Textarea
                  {...p}
                  maxLength={1000}
                  value={message}
                  placeholder="Готов обсудить, удобнее созвон после 18:00…"
                  onChange={(e) => setMessage(e.target.value)}
                />
              )}
            </Field>
            <ErrorNote error={accept.error} />
          </div>
        </Modal>
      )}

      {declining && id && (
        <DeclineModal
          invitationId={id}
          onClose={() => setDeclining(false)}
          onDone={() => {
            setDeclining(false);
            reload();
          }}
        />
      )}

      {complaining && id && (
        <ComplaintModal invitationId={id} onClose={() => setComplaining(false)} />
      )}
    </>
  );
}
