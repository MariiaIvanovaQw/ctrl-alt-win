import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import { useAction, useAsync } from '../../lib/useAsync';
import { dateTime } from '../../lib/format';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  ErrorNote,
  Loading,
  Modal,
  PageHeader,
} from '../../components/ui';
import { FspAchievementCard, FspSummary } from '../../components/domain';
import type { FspProfile } from '../../api/types';

type Note = { tone: 'success' | 'warn' | 'danger'; text: string };

/** Итог возврата из ФСП ID — приходит параметром `?fsp=` в адресе. */
const RETURN_NOTE: Record<string, Note> = {
  linked: { tone: 'success', text: 'ФСП ID привязан, достижения загружены' },
  error: { tone: 'danger', text: 'Не удалось привязать ФСП ID. Попробуйте ещё раз' },
  cancelled: { tone: 'warn', text: 'Привязка отменена' },
};

/** Ошибки завершения привязки (`POST /candidate/fsp/link/complete`). */
const COMPLETE_ERRORS: Record<string, string> = {
  fsp_state_foreign: 'Привязку начали под другой учётной записью платформы. Начните привязку заново из этого кабинета',
  fsp_id_taken: 'Этот ФСП ID уже привязан к другому профилю',
  fsp_already_linked: 'К профилю уже привязан другой ФСП ID. Чтобы сменить его, сначала отвяжите текущий',
  fsp_state_invalid: 'Сеанс привязки устарел. Начните заново',
};

export default function Fsp() {
  const [params, setParams] = useSearchParams();
  const { data, loading, error, reload } = useAsync(() => api.get<FspProfile>('/candidate/fsp'), []);

  const [linking, setLinking] = useState(false);
  const [consent, setConsent] = useState(false);

  const returned = params.get('fsp');
  const [note, setNote] = useState<Note | undefined>(undefined);
  const completing = useRef(false);

  // Возврат из ФСП ID. При `fsp=confirm` привязку завершает этот кабинет
  // запросом с токеном кандидата: так ФСП ID нельзя присоединить к чужому
  // профилю по подсунутой ссылке. Затем параметры убираются из адреса.
  useEffect(() => {
    if (!returned) return;
    const code = params.get('fsp_code');
    const state = params.get('fsp_state');
    const cleanup = () => {
      const next = new URLSearchParams(params);
      ['fsp', 'fsp_code', 'fsp_state'].forEach((k) => next.delete(k));
      setParams(next, { replace: true });
    };
    if (returned === 'confirm' && code && state) {
      if (completing.current) return;
      completing.current = true;
      api
        .post<FspProfile>('/candidate/fsp/link/complete', { code, state })
        .then(() => setNote(RETURN_NOTE.linked))
        .catch((e: unknown) =>
          setNote({
            tone: 'danger',
            text:
              e instanceof ApiError ? (COMPLETE_ERRORS[e.code] ?? e.message) : 'Нет связи с сервером',
          }),
        )
        .finally(() => {
          reload();
          cleanup();
        });
      return;
    }
    setNote(RETURN_NOTE[returned]);
    reload();
    cleanup();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [returned]);

  const link = useAction(async () => {
    const res = await api.post<{ authorization_url: string }>('/candidate/fsp/link', {
      consent: true,
      redirect_after: '/candidate/fsp',
    });
    window.location.href = res.authorization_url;
  });

  const sync = useAction(async () => {
    await api.post('/candidate/fsp/sync');
    reload();
  });

  const unlink = useAction(async () => {
    await api.del('/candidate/fsp');
    reload();
  });

  if (loading) return <Loading rows={3} />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title="ФСП ID"
        subtitle="Привязка к профилю участника Федерации спортивного программирования. Достижения соревнований подтверждаются реестром и усиливают позицию в подборке"
      />

      <div className="stack">
        {note && <Alert tone={note.tone}>{note.text}</Alert>}

        {!data.linked ? (
          <Card title="Профиль не привязан">
            <Alert tone="neutral">
              {data.note ??
                'Привязка необязательна: категория и грейд определяются тестом. Достижения ФСП – дополнительный сигнал для работодателя'}
            </Alert>
            <div style={{ marginTop: 'var(--sp-4)' }}>
              <Button variant="primary" onClick={() => setLinking(true)}>
                Привязать ФСП ID
              </Button>
            </div>
          </Card>
        ) : (
          <>
            <Card
              title="Профиль участника"
              actions={
                <>
                  <Button size="sm" busy={sync.busy} onClick={() => void sync.run()}>
                    Обновить
                  </Button>
                  <Button size="sm" variant="danger" busy={unlink.busy} onClick={() => void unlink.run()}>
                    Отвязать
                  </Button>
                </>
              }
            >
              <dl className="kv">
                <dt>ФСП ID</dt>
                <dd className="mono">{data.fsp_id}</dd>
                <dt>Имя в реестре</dt>
                <dd>{data.display_name ?? '–'}</dd>
                <dt>Регион</dt>
                <dd>{data.region ?? '–'}</dd>
                <dt>Спортивный разряд</dt>
                <dd>{data.sport_rank_title ?? 'нет'}</dd>
                <dt>Синхронизировано</dt>
                <dd>{dateTime(data.last_sync_at)}</dd>
              </dl>
              <ErrorNote error={sync.error} />
              <ErrorNote error={unlink.error} />
              {data.sync_error && <Alert tone="warn">{data.sync_error}</Alert>}
            </Card>

            <Card
              title="Достижения"
              subtitle={
                data.achievements.length
                  ? 'Эти записи видит работодатель в вашей карточке'
                  : undefined
              }
            >
              {data.achievements.length ? (
                <div className="stack-sm">
                  <FspSummary stats={data.stats} />
                  <p className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                    В подборке учитываются число соревнований и результат: победы и призовые места
                    весят больше участия, свежие – больше давних. Соревнования и дисциплины между собой
                    не сравниваются, роль в команде не влияет; одни участия без результата дают
                    небольшой вклад
                  </p>
                  {data.achievements.map((a, i) => (
                    <FspAchievementCard key={`${a.event_name}-${i}`} a={a} />
                  ))}
                </div>
              ) : (
                <Alert tone="neutral">
                  {data.note ??
                    'В реестре ФСП пока нет ваших соревнований. Это не влияет на категорию и грейд'}
                </Alert>
              )}
            </Card>
          </>
        )}
      </div>

      {linking && (
        <Modal
          title="Привязка ФСП ID"
          onClose={() => setLinking(false)}
          footer={
            <>
              <Button onClick={() => setLinking(false)}>Отмена</Button>
              <Button
                variant="primary"
                busy={link.busy}
                disabled={!consent}
                onClick={() => void link.run()}
              >
                Перейти к входу в ФСП
              </Button>
            </>
          }
        >
          <div className="stack">
            <p style={{ fontSize: 'var(--text-sm)' }}>
              Вы перейдёте на страницу входа ФСП ID. После подтверждения мы получим из реестра ваш
              идентификатор, регион и список подтверждённых достижений
            </p>
            <Checkbox
              checked={consent}
              onChange={setConsent}
              label="Согласен на получение и показ данных о моих достижениях из реестра ФСП"
            />
            <Alert tone="neutral">
              Если вашего профиля в реестре пока нет, для проверки связи доступны тестовые
              участники FSP-100001, FSP-100002 и FSP-100003. Войти через ФСП ID можно и со страницы
              входа – тогда профиль кандидата создастся сам
            </Alert>
            <ErrorNote error={link.error} />
          </div>
        </Modal>
      )}
    </>
  );
}
