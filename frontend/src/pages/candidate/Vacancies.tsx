import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAction, useAsync } from '../../lib/useAsync';
import { date, levelTitle } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Chip,
  Empty,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
  Textarea,
} from '../../components/ui';
import { ApplicationStatusBadge, MessageThread, Salary, Timeline } from '../../components/domain';
import type { Application, RecommendedVacancies, Vacancy } from '../../api/types';

/** Отклик на вакансию — дополнительный сценарий к основной механике. */
function ApplyModal({
  vacancy,
  onClose,
  onDone,
}: {
  vacancy: Vacancy;
  onClose: () => void;
  onDone: () => void;
}) {
  const [letter, setLetter] = useState('');
  const submit = useAction(async () => {
    await api.post('/candidate/applications', {
      need_id: vacancy.id,
      cover_letter: letter || null,
    });
    onDone();
  });

  return (
    <Modal
      title={`Отклик: ${vacancy.title}`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" busy={submit.busy} onClick={() => void submit.run()}>
            Откликнуться
          </Button>
        </>
      }
    >
      <div className="stack">
        <Alert tone="info">
          При отклике работодатель сразу видит ваши контакты и балл соответствия – вы сами проявили
          инициативу
        </Alert>
        <Field label="Сопроводительное письмо" hint="Необязательно, но повышает шансы">
          {(p) => (
            <Textarea
              {...p}
              value={letter}
              placeholder="Делал похожие задачи: …"
              onChange={(e) => setLetter(e.target.value)}
            />
          )}
        </Field>
        <ErrorNote error={submit.error} />
      </div>
    </Modal>
  );
}

export function CandidateVacancies() {
  const { data, loading, error, reload } = useAsync(
    () => api.get<RecommendedVacancies>('/candidate/vacancies/recommended'),
    [],
  );
  // действующие отклики: на такую вакансию второй раз откликнуться нельзя (только после отзыва)
  const mine = useAsync(() => api.get<Application[]>('/candidate/applications'), []);
  const applied = new Set((mine.data ?? []).filter((a) => a.status !== 'withdrawn').map((a) => a.vacancy.id));
  const [applying, setApplying] = useState<Vacancy | null>(null);

  if (loading) return <Loading rows={3} />;
  if (error) return <ErrorNote error={error} />;

  return (
    <>
      <PageHeader
        title="Вакансии"
        subtitle="Вакансии, подходящие вашей категории. Можно откликнуться самому, не дожидаясь приглашения"
      />

      <div className="stack">
        {data?.minor && (
          <Alert tone="info">
            Вам меньше 18 лет, поэтому показаны только вакансии с отметкой «подходит для несовершеннолетних (15–17 лет)»:
            лёгкий труд и сокращённое рабочее время. Откликаться можно после согласия законного
            представителя (раздел «Анкета»)
          </Alert>
        )}
        {!data?.items.length ? (
          <Empty title="Подходящих вакансий пока нет">
            Загляните в <Link to="/vacancies">общий список</Link> или дождитесь приглашения
          </Empty>
        ) : (
          data.items.map((v) => (
            <article key={v.id} className="card">
              <div className="row-top" style={{ justifyContent: 'space-between' }}>
                <div className="stack-sm" style={{ minWidth: 0 }}>
                  <h3>{v.title}</h3>
                  <div className="row-wrap muted" style={{ fontSize: 'var(--text-sm)' }}>
                    <span>{v.company.name}</span>
                    <span>· {v.city ?? 'город не указан'}</span>
                    {v.work_format_title && <span>· {v.work_format_title}</span>}
                    {v.published_at && <span>· {date(v.published_at)}</span>}
                  </div>
                </div>
                <Salary from={v.salary_from} to={v.salary_to} size="md" />
              </div>

              <div className="row-wrap" style={{ marginTop: 'var(--sp-3)' }}>
                <Badge tone="accent">
                  {v.specialization_title} · {levelTitle(v.level)}
                </Badge>
                {v.fits_my_category && <Badge tone="success">Ваша категория</Badge>}
                {v.suitable_for_minors && <Badge tone="neutral">Подходит для 15–17 лет</Badge>}
                {v.salary_fits === false && <Badge tone="warn">Ниже ваших ожиданий</Badge>}
                {applied.has(v.id) && <Badge tone="success">Вы откликнулись</Badge>}
              </div>

              <div className="row-wrap" style={{ marginTop: 'var(--sp-3)' }}>
                {v.stack.slice(0, 8).map((s) => (
                  <Chip key={s.slug}>{s.title}</Chip>
                ))}
              </div>

              <p className="muted" style={{ fontSize: 'var(--text-sm)', marginTop: 'var(--sp-3)' }}>
                {v.description.slice(0, 220)}
                {v.description.length > 220 ? '…' : ''}
              </p>

              <div className="row-wrap" style={{ marginTop: 'var(--sp-4)' }}>
                {applied.has(v.id) ? (
                  <Link className="btn btn-secondary btn-sm" to="/candidate/applications">
                    Мой отклик
                  </Link>
                ) : (
                  <Button variant="primary" size="sm" onClick={() => setApplying(v)}>
                    Откликнуться
                  </Button>
                )}
                <Link className="btn btn-secondary btn-sm" to={`/vacancies/${v.id}`}>
                  Подробнее
                </Link>
              </div>
            </article>
          ))
        )}
      </div>

      {applying && (
        <ApplyModal
          vacancy={applying}
          onClose={() => setApplying(null)}
          onDone={() => {
            setApplying(null);
            reload();
            mine.reload();
          }}
        />
      )}
    </>
  );
}

export function CandidateApplications() {
  const { data, loading, error, reload } = useAsync(
    () => api.get<Application[]>('/candidate/applications'),
    [],
  );

  const withdraw = useAction(async (id: string) => {
    await api.post(`/candidate/applications/${id}/withdraw`);
    reload();
  });
  const revoke = useAction(async (id: string) => {
    await api.post(`/candidate/applications/${id}/revoke-contacts`);
    reload();
  });
  const [chatFor, setChatFor] = useState<string | null>(null);

  if (loading) return <Loading rows={3} />;
  if (error) return <ErrorNote error={error} />;

  return (
    <>
      <PageHeader title="Мои отклики" subtitle="Статусы обновляются по мере работы работодателя" />

      {!data?.length ? (
        <Empty
          title="Откликов пока нет"
          action={
            <Link className="btn btn-primary" to="/candidate/vacancies">
              Посмотреть вакансии
            </Link>
          }
        >
          Откликнитесь на подходящую вакансию или дождитесь приглашения от работодателя
        </Empty>
      ) : (
        <div className="stack">
          <ErrorNote error={withdraw.error} />
          {data.map((a) => (
            <article key={a.id} className="card">
              <div className="row-top" style={{ justifyContent: 'space-between' }}>
                <div className="stack-sm" style={{ minWidth: 0 }}>
                  <div className="row-wrap">
                    <h3>{a.vacancy.title}</h3>
                    <ApplicationStatusBadge status={a.status} />
                  </div>
                  <div className="muted" style={{ fontSize: 'var(--text-sm)' }}>
                    {a.vacancy.company.name} · отклик от {date(a.created_at)}
                  </div>
                </div>
                <Salary from={a.vacancy.salary_from} to={a.vacancy.salary_to} size="md" />
              </div>

              {a.cover_letter && (
                <p className="muted" style={{ fontSize: 'var(--text-sm)', marginTop: 'var(--sp-3)' }}>
                  «{a.cover_letter}»
                </p>
              )}

              {a.employer_comment && (
                <div style={{ marginTop: 'var(--sp-3)' }}>
                  <Alert tone="neutral" title="Ответ работодателя">
                    {a.employer_comment}
                  </Alert>
                </div>
              )}

              <div style={{ marginTop: 'var(--sp-4)' }}>
                <Timeline events={a.timeline} />
              </div>

              <div className="row-wrap" style={{ marginTop: 'var(--sp-4)' }}>
                {(a.status === 'sent' || a.status === 'viewed') && (
                  <Button size="sm" busy={withdraw.busy} onClick={() => void withdraw.run(a.id)}>
                    Отозвать отклик
                  </Button>
                )}
                {a.contacts_shared && (
                  <Button size="sm" variant="ghost" busy={revoke.busy} onClick={() => void revoke.run(a.id)}>
                    Закрыть компании доступ к контактам
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setChatFor(chatFor === a.id ? null : a.id)}>
                  {chatFor === a.id ? 'Скрыть переписку' : 'Переписка'}
                  {a.unread_messages ? ` · новых: ${a.unread_messages}` : ''}
                </Button>
              </div>
              <ErrorNote error={revoke.error} />
              {chatFor === a.id && (
                <div style={{ marginTop: 'var(--sp-3)' }}>
                  <MessageThread
                    path={`/candidate/applications/${a.id}/messages`}
                    open={['sent', 'viewed', 'invited'].includes(a.status)}
                  />
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </>
  );
}
