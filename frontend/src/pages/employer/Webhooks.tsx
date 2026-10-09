import { useState } from 'react';
import { api } from '../../api/client';
import { useAction, useAsync } from '../../lib/useAsync';
import { dateTime } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Empty,
  ErrorNote,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
} from '../../components/ui';
import type { WebhookDelivery, WebhookEndpoint, WebhookEvent } from '../../api/types';

/** Секрет приходит один раз при создании — показываем его явно и один раз. */
function SecretOnce({ secret }: { secret: string }) {
  return (
    <Alert tone="warn" title="Сохраните секрет сейчас">
      Он показывается один раз. Им подписываются доставки – проверяйте подпись на своей стороне.
      <pre className="code" style={{ marginTop: 'var(--sp-3)' }}>
        <code>{secret}</code>
      </pre>
    </Alert>
  );
}

function EndpointModal({
  events,
  onClose,
  onCreated,
}: {
  events: WebhookEvent[];
  onClose: () => void;
  onCreated: (secret: string | undefined) => void;
}) {
  const [url, setUrl] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [description, setDescription] = useState('');

  const create = useAction(async () => {
    const created = await api.post<WebhookEndpoint>('/employer/webhooks', {
      url,
      events: picked,
      description: description || null,
    });
    onCreated(created.secret);
  });

  return (
    <Modal
      title="Подписка ATS на события"
      onClose={onClose}
      wide
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button
            variant="primary"
            busy={create.busy}
            disabled={!url || !picked.length}
            onClick={() => void create.run()}
          >
            Создать подписку
          </Button>
        </>
      }
    >
      <div className="stack">
        <Field label="Адрес приёмника" required hint="HTTPS-эндпоинт вашей ATS">
          {(p) => (
            <Input
              {...p}
              value={url}
              placeholder="https://ats.company.ru/hooks/fsp"
              onChange={(e) => setUrl(e.target.value)}
            />
          )}
        </Field>

        <Field label="Описание">
          {(p) => (
            <Input {...p} value={description} onChange={(e) => setDescription(e.target.value)} />
          )}
        </Field>

        <div>
          <div className="field-label" style={{ marginBottom: 'var(--sp-2)' }}>
            События
          </div>
          <div className="stack-sm">
            {events.map((e) => (
              <Checkbox
                key={e.event}
                checked={picked.includes(e.event)}
                onChange={(v) =>
                  setPicked((prev) => (v ? [...prev, e.event] : prev.filter((x) => x !== e.event)))
                }
                label={
                  <>
                    {e.title}
                    <span className="faint mono" style={{ fontSize: 'var(--text-xs)' }}>
                      {' '}
                      {e.event}
                    </span>
                  </>
                }
              />
            ))}
          </div>
        </div>

        <ErrorNote error={create.error} />
      </div>
    </Modal>
  );
}

function Deliveries({ endpointId }: { endpointId: string }) {
  const { data, loading, error, reload } = useAsync(
    () => api.get<WebhookDelivery[]>(`/employer/webhooks/${endpointId}/deliveries`),
    [endpointId],
  );

  const retry = useAction(async (id: string) => {
    await api.post(`/employer/webhooks/deliveries/${id}/retry`);
    reload();
  });

  if (loading) return <Loading rows={1} />;
  if (error) return <ErrorNote error={error} />;
  if (!data?.length) return <p className="muted">Доставок ещё не было</p>;

  return (
    <>
      <ErrorNote error={retry.error} />
      <table className="table">
        <thead>
          <tr>
            <th>Событие</th>
            <th>Когда</th>
            <th>Статус</th>
            <th className="table-num">Попыток</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.id}>
              <td className="mono" style={{ fontSize: 'var(--text-xs)' }}>
                {d.event}
              </td>
              <td>{dateTime(d.created_at)}</td>
              <td>
                <Badge tone={d.status === 'delivered' ? 'success' : 'danger'}>
                  {d.status}
                  {d.response_code ? ` · ${d.response_code}` : ''}
                </Badge>
                {d.error && (
                  <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                    {d.error}
                  </div>
                )}
              </td>
              <td className="table-num">{d.attempts}</td>
              <td style={{ textAlign: 'right' }}>
                {d.status !== 'delivered' && (
                  <Button size="sm" busy={retry.busy} onClick={() => void retry.run(d.id)}>
                    Повторить
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export default function Webhooks() {
  const events = useAsync(() => api.get<WebhookEvent[]>('/employer/webhooks/events'), []);
  const list = useAsync(() => api.get<WebhookEndpoint[]>('/employer/webhooks'), []);

  const [creating, setCreating] = useState(false);
  const [freshSecret, setFreshSecret] = useState<string | null>(null);
  const [openLog, setOpenLog] = useState<string | null>(null);

  const ping = useAction(async (id: string) => {
    await api.post(`/employer/webhooks/${id}/ping`);
    list.reload();
  });

  const rotate = useAction(async (id: string) => {
    const res = await api.post<{ secret: string }>(`/employer/webhooks/${id}/rotate-secret`);
    setFreshSecret(res.secret);
  });

  const remove = useAction(async (id: string) => {
    await api.del(`/employer/webhooks/${id}`);
    // Секрет показывается один раз и относится к удалённой подписке — убираем.
    setFreshSecret(null);
    list.reload();
  });

  if (list.loading) return <Loading rows={3} />;

  return (
    <>
      <PageHeader
        title="Интеграции с ATS"
        subtitle="События платформы приходят в вашу систему подбора: приглашения, отклики, решения кандидатов. Кандидата можно выгрузить в формате JSON Resume из его карточки"
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            Новая подписка
          </Button>
        }
      />

      <div className="stack">
        {freshSecret && <SecretOnce secret={freshSecret} />}
        <ErrorNote error={list.error} />
        <ErrorNote error={ping.error} />
        <ErrorNote error={rotate.error} />
        <ErrorNote error={remove.error} />

        {!list.data?.length ? (
          <Empty
            title="Подписок нет"
            action={
              <Button variant="primary" onClick={() => setCreating(true)}>
                Подписать ATS
              </Button>
            }
          >
            Подписка избавляет от ручного переноса кандидатов между платформой и вашей системой
          </Empty>
        ) : (
          list.data.map((e) => (
            <Card
              key={e.id}
              title={e.url}
              subtitle={`События: ${e.events.join(', ')}`}
              actions={
                <>
                  <Badge tone={e.active ? 'success' : 'neutral'}>
                    {e.active ? 'активна' : 'выключена'}
                  </Badge>
                  <Button size="sm" busy={ping.busy} onClick={() => void ping.run(e.id)}>
                    Тест
                  </Button>
                  <Button size="sm" busy={rotate.busy} onClick={() => void rotate.run(e.id)}>
                    Новый секрет
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => void remove.run(e.id)}>
                    Удалить
                  </Button>
                </>
              }
            >
              <div className="row-wrap muted" style={{ fontSize: 'var(--text-sm)' }}>
                <span>создана {dateTime(e.created_at)}</span>
                {e.last_delivery_at && <span>· последняя доставка {dateTime(e.last_delivery_at)}</span>}
              </div>

              <div style={{ marginTop: 'var(--sp-3)' }}>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setOpenLog((cur) => (cur === e.id ? null : e.id))}
                >
                  {openLog === e.id ? 'Скрыть журнал' : 'Журнал доставок'}
                </Button>
              </div>

              {openLog === e.id && (
                <div style={{ marginTop: 'var(--sp-4)' }}>
                  <Deliveries endpointId={e.id} />
                </div>
              )}
            </Card>
          ))
        )}

        {!!events.data?.length && (
          <Card title="Какие события доступны">
            <table className="table">
              <tbody>
                {events.data.map((e) => (
                  <tr key={e.event}>
                    <td className="mono" style={{ fontSize: 'var(--text-xs)' }}>
                      {e.event}
                    </td>
                    <td>{e.title}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>

      {creating && events.data && (
        <EndpointModal
          events={events.data}
          onClose={() => setCreating(false)}
          onCreated={(secret) => {
            setCreating(false);
            setFreshSecret(secret ?? null);
            list.reload();
          }}
        />
      )}
    </>
  );
}
