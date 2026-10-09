import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api, download, saveJson } from '../../api/client';
import { useAction, useAsync } from '../../lib/useAsync';
import { ago, count, date, levelTitle, percent, salaryRange, years } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Card,
  Chip,
  ErrorNote,
  Field,
  Loading,
  Meter,
  Modal,
  PageHeader,
  Select,
} from '../../components/ui';
import {
  CategoryBadge,
  CompetencyList,
  ContactsBlock,
  FspBlock,
  StackChips,
} from '../../components/domain';
import InviteModal from './InviteModal';
import type { CandidateCard, EmployerTask, Need } from '../../api/types';

/**
 * Адресное задание: работодатель предлагает конкретному кандидату одно из
 * своих регулярных заданий (постановщики: «может предложить вакансию и тест
 * точечно»). Кандидат получает его сразу и письмо об этом.
 */
function AssignTaskModal({ candidateId, onClose }: { candidateId: string; onClose: () => void }) {
  const tasks = useAsync(() => api.get<EmployerTask[]>('/employer/tasks'), []);
  const [taskId, setTaskId] = useState('');
  const [done, setDone] = useState(false);
  const assign = useAction(async () => {
    await api.post(`/employer/tasks/${taskId}/assign`, { candidate_id: candidateId });
    setDone(true);
  });
  const active = (tasks.data ?? []).filter((t) => t.active);

  return (
    <Modal
      title="Предложить задание"
      onClose={onClose}
      footer={
        done ? (
          <Button variant="primary" onClick={onClose}>
            Готово
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>Отмена</Button>
            <Button variant="primary" busy={assign.busy} disabled={!taskId} onClick={() => void assign.run()}>
              Предложить
            </Button>
          </>
        )
      }
    >
      <div className="stack">
        {tasks.loading && <Loading rows={2} />}
        <ErrorNote error={tasks.error} />
        {done ? (
          <Alert tone="success">Задание отправлено: кандидат увидит его в разделе «Задания» и получит письмо</Alert>
        ) : active.length ? (
          <Field label="Задание" hint="Кандидат получит его сразу, срок решения — 7 дней">
            {(p) => (
              <Select {...p} value={taskId} onChange={(e) => setTaskId(e.target.value)}>
                <option value="">Выберите…</option>
                {active.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ) : (
          !tasks.loading && (
            <Alert tone="neutral">
              Активных заданий нет. Создайте его в разделе <Link to="/employer/tasks">«Задания»</Link>
            </Alert>
          )
        )}
        <ErrorNote error={assign.error} />
      </div>
    </Modal>
  );
}

export default function CandidateCardPage() {
  const { id } = useParams<{ id: string }>();
  // направление, в котором кандидата нашли: у него может быть несколько категорий
  const [params, setParams] = useSearchParams();
  const spec = params.get('spec') ?? undefined;
  const { data, loading, error, reload } = useAsync(
    () => api.get<CandidateCard>(`/employer/candidates/${id}`, { specialization: spec }),
    [id, spec],
  );
  const needs = useAsync(() => api.get<Need[]>('/employer/needs'), []);
  const [inviting, setInviting] = useState(false);
  const [assigning, setAssigning] = useState(false);

  const getPdf = useAction(() => download(`/employer/candidates/${id}/pdf${spec ? `?specialization=${spec}` : ''}`, `${id}.pdf`));
  const exportAts = useAction(async () => {
    const payload = await api.get<unknown>(`/employer/candidates/${id}/export`);
    saveJson(payload, `${id}-jsonresume.json`);
  });

  // Перечитывание после приглашения не прячет карточку: иначе модалка с
  // «Приглашение отправлено» размонтировалась бы и открылась пустой формой.
  if (loading && data?.candidate_id !== id) return <Loading rows={5} />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  const t = data.test;

  return (
    <>
      <Link to="/employer/selection" className="muted" style={{ fontSize: 'var(--text-sm)' }}>
        ← К подборке
      </Link>

      <div style={{ marginTop: 'var(--sp-4)' }}>
        <PageHeader
          title={data.display_name}
          subtitle={
            data.category
              ? data.category.confirmed === false
                ? `${data.category.specialization_title} · ${levelTitle(data.category.level)} – ${data.category.status_title ?? 'не подтверждено тестом'}`
                : `${data.category.specialization_title} · ${levelTitle(data.category.level)} – подтверждено тестом ${date(data.category.confirmed_at)}`
              : 'Категория ещё не подтверждена тестом'
          }
          actions={
            <>
              <Button variant="primary" onClick={() => setInviting(true)}>
                Пригласить
              </Button>
              <Button onClick={() => setAssigning(true)}>Предложить задание</Button>
              <Button busy={getPdf.busy} onClick={() => void getPdf.run()}>
                Скачать PDF
              </Button>
              <Button busy={exportAts.busy} onClick={() => void exportAts.run()}>
                Выгрузить для ATS
              </Button>
            </>
          }
        />
      </div>

      <div className="stack">
        <ErrorNote error={getPdf.error} />
        <ErrorNote error={exportAts.error} />

        {(data.other_categories?.length ?? 0) > 0 && (
          <Alert tone="neutral" title="Другие категории кандидата">
            <div className="row-wrap">
              {data.other_categories!.map((c) => (
                <Button key={c.specialization} size="sm" onClick={() => setParams({ spec: c.specialization })}>
                  {c.specialization_title} · {levelTitle(c.level)}
                  {c.confirmed === false ? ' (не подтверждено)' : ''}
                </Button>
              ))}
            </div>
          </Alert>
        )}

        <Card>
          <div className="row-wrap">
            {data.category && (
              <CategoryBadge
                specialization={data.category.specialization_title}
                track={data.category.track_title}
                level={data.category.level}
                confirmed={data.category.confirmed !== false}
              />
            )}
            {data.fsp?.linked && data.fsp.achievements.length > 0 && <Badge tone="accent">ФСП</Badge>}
            {data.minor && <Badge tone="warn">До 18 лет</Badge>}
            {data.open_to_offers ? (
              <Badge tone="success">Открыт к предложениям</Badge>
            ) : (
              <Badge tone="neutral">Не ищет работу</Badge>
            )}
          </div>

          <dl className="kv" style={{ marginTop: 'var(--sp-4)' }}>
            {data.city && (
              <>
                <dt>Город</dt>
                <dd>
                  {data.city}
                  {data.relocation ? ' · готов к переезду' : ''}
                </dd>
              </>
            )}
            <dt>Опыт</dt>
            <dd>{years(data.experience_years)}</dd>
            {data.salary_expectation && (
              <>
                <dt>Ожидания</dt>
                <dd>{salaryRange(data.salary_expectation, null)}</dd>
              </>
            )}
            {data.roles.length > 0 && (
              <>
                <dt>Роль в команде</dt>
                <dd>{data.roles.map((r) => r.title).join(', ')}</dd>
              </>
            )}
            {data.work_formats.length > 0 && (
              <>
                <dt>Формат работы</dt>
                <dd>{data.work_formats.map((w) => w.title).join(', ')}</dd>
              </>
            )}
            {data.last_active_at && (
              <>
                <dt>Активность</dt>
                <dd>{ago(data.last_active_at)}</dd>
              </>
            )}
          </dl>

          {data.about && (
            <p className="muted" style={{ fontSize: 'var(--text-sm)', marginTop: 'var(--sp-4)' }}>
              {data.about}
            </p>
          )}
        </Card>

        {data.minor && data.minor_note && (
          <Alert tone="warn" title="Несовершеннолетний кандидат">
            {data.minor_note}
          </Alert>
        )}

        {data.category?.confirmed === false && (
          <Alert tone="warn" title="Грейд заявлен кандидатом, тест его не подтвердил">
            Такие кандидаты показываются ниже подтверждённых. Можно пригласить кандидата и
            попросить пройти тест заявленного уровня
          </Alert>
        )}

        {t && t.score != null && (
          <Card
            title="Результат теста"
            subtitle="Главное отличие от резюме: эти цифры получены на заданиях, а не заявлены кандидатом"
          >
            <div className="grid-3">
              <div>
                <div className="field-label">Балл</div>
                <div
                  className="display"
                  style={{ fontSize: 'var(--text-xl)', fontWeight: 800, color: 'var(--violet-600)' }}
                >
                  {t.score}
                </div>
                <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                  заявлял {levelTitle(t.declared_level)}
                </div>
              </div>

              <div>
                <div className="field-label">На заданиях своего уровня</div>
                <div className="row" style={{ gap: 'var(--sp-3)', marginTop: 6 }}>
                  <span className="mono">{percent(t.level_band_rate)}</span>
                  <div style={{ flex: 1 }}>
                    <Meter value={t.level_band_rate} label="Доля решённых заданий своего уровня" />
                  </div>
                </div>
              </div>

              <div>
                <div className="field-label">Место в категории</div>
                <div className="row" style={{ gap: 'var(--sp-3)', marginTop: 6 }}>
                  <span className="mono">{percent(t.percentile_in_category)}</span>
                  <div style={{ flex: 1 }}>
                    <Meter value={t.percentile_in_category} label="Перцентиль в категории" />
                  </div>
                </div>
                <div className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 4 }}>
                  сильнее стольких же в своей категории
                </div>
              </div>
            </div>

            {!!t.level_band_detail?.length && (
              <table className="table" style={{ marginTop: 'var(--sp-5)' }}>
                <thead>
                  <tr>
                    <th>Полоса сложности</th>
                    <th style={{ width: '32%' }}>Решено</th>
                    <th className="table-num">Среднее по категории</th>
                  </tr>
                </thead>
                <tbody>
                  {t.level_band_detail.map((b) => (
                    <tr key={b.band}>
                      <td className="mono">{b.band}</td>
                      <td>
                        <div className="row" style={{ gap: 'var(--sp-3)' }}>
                          <span className="mono" style={{ minWidth: 40 }}>
                            {percent(b.rate)}
                          </span>
                          <div style={{ flex: 1 }}>
                            <Meter value={b.rate} label={b.band} />
                          </div>
                        </div>
                      </td>
                      <td className="table-num">{percent(b.category_average)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {!!t.flags?.length && (
              <Alert tone="neutral" title="Признаки для разбора">
                {t.flags.map((f) => f.message).join('. ')}. На грейд признаки не влияют – это повод
                уточнить детали на собеседовании
              </Alert>
            )}

            <p className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 'var(--sp-4)' }}>
              Попыток: {t.attempts_total} · последняя {date(t.finished_at)}
            </p>
          </Card>
        )}

        <Card title="Компетенции" subtitle="Подтверждено тестом">
          <CompetencyList items={data.competencies} />
        </Card>

        <Card title="Стек">
          <StackChips stack={data.stack} />
          {!!data.soft_skills?.length && (
            <div style={{ marginTop: 'var(--sp-4)' }}>
              <div className="field-label" style={{ marginBottom: 'var(--sp-2)' }}>
                Софт-скиллы
              </div>
              <div className="row-wrap">
                {data.soft_skills.map((s) => (
                  <Chip key={s.slug}>{s.title}</Chip>
                ))}
              </div>
              <div className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 'var(--sp-2)' }}>
                заявлено кандидатом
              </div>
            </div>
          )}
        </Card>

        <Card title="Достижения ФСП" subtitle="Подтверждены реестром Федерации">
          <FspBlock fsp={data.fsp} />
        </Card>

        {data.regular_tasks && (data.regular_tasks.total ?? 0) > 0 && (
          <Card
            title="Регулярные задания"
            subtitle="Короткие задачи от работодателей – свежий сигнал о кандидате"
          >
            <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
              Решено {data.regular_tasks.solved ?? 0} из{' '}
              {count(data.regular_tasks.total ?? 0, 'задания', 'заданий', 'заданий')}
              {data.regular_tasks.last_at ? `, последнее ${ago(data.regular_tasks.last_at)}` : ''}
            </p>
          </Card>
        )}

        <ContactsBlock c={data} />

        {!data.contacts_visible && (
          <Alert tone="neutral">
            Чтобы получить контакты, отправьте приглашение с вилкой зарплаты. Кандидат увидит
            условия и решит, начинать ли общение
          </Alert>
        )}
      </div>

      {assigning && <AssignTaskModal candidateId={data.candidate_id} onClose={() => setAssigning(false)} />}

      {inviting && (
        <InviteModal
          candidate={data}
          // потребность той же специализации, что у кандидата: иначе фронтендеру ушло бы
          // описание и уровень вакансии бэкендера
          need={needs.data?.find((n) => n.specialization === data.category?.specialization) ?? null}
          onClose={() => setInviting(false)}
          onSent={reload}
        />
      )}
    </>
  );
}
