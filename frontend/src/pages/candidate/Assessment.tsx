import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction, useAsync } from '../../lib/useAsync';
import { date, dateTime, levelTitle } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorNote,
  Loading,
  Modal,
  PageHeader,
} from '../../components/ui';
import { CompetencyList } from '../../components/domain';
import AttemptResultView from './AttemptResult';
import Survey from './Survey';
import type { AssessmentStatus, Attempt, Availability, CandidateProfile, Level } from '../../api/types';

const LEVEL_BLURB: Record<string, string> = {
  junior: 'Типовые задачи под руководством, работа по готовому дизайну',
  middle: 'Самостоятельные задачи от проектирования до выката',
  senior: 'Архитектура, сложные компромиссы, ответственность за систему',
};

/** Карточка выбора уровня теста. Недоступный уровень объясняет причину. */
function LevelCard({
  item,
  specialization,
  onStart,
  busy,
}: {
  item: Availability;
  specialization: string;
  onStart: (level: Level) => void;
  busy: boolean;
}) {
  return (
    <div className="card" style={{ opacity: item.allowed ? 1 : 0.75 }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 'var(--sp-2)' }}>
        <h3>{levelTitle(item.level)}</h3>
        {!item.allowed && <Badge tone="neutral">недоступен</Badge>}
      </div>

      <p className="muted" style={{ fontSize: 'var(--text-sm)', minHeight: '3em' }}>
        {LEVEL_BLURB[item.level] ?? ''}
      </p>

      {item.allowed ? (
        <Button
          variant="primary"
          block
          busy={busy}
          onClick={() => onStart(item.level)}
          aria-label={`Начать тест уровня ${levelTitle(item.level)} по специализации ${specialization}`}
        >
          Начать тест
        </Button>
      ) : (
        <div className="alert alert-neutral" style={{ fontSize: 'var(--text-xs)' }}>
          <div>
            {item.message ?? 'Пока недоступен'}
            {item.available_at && <> · можно с {date(item.available_at)}</>}
          </div>
        </div>
      )}
    </div>
  );
}

/** Просмотр разбора выбранной попытки в модальном окне. */
function AttemptModal({ attemptId, onClose }: { attemptId: string; onClose: () => void }) {
  const { data, loading, error } = useAsync(
    () => api.get<Attempt>(`/candidate/assessment/attempts/${attemptId}`),
    [attemptId],
  );

  return (
    <Modal title="Разбор попытки" onClose={onClose} wide>
      {loading && <Loading rows={3} />}
      <ErrorNote error={error} />
      {data?.result && (
        <AttemptResultView result={data.result} declaredLevel={data.declared_level} />
      )}
    </Modal>
  );
}

/**
 * Категории кандидата: по одной на направление (постановщики: «поддержка
 * нескольких категорий будет плюсом»). Работодатель находит кандидата в
 * каждой из них; правила смены грейда действуют внутри направления.
 */
function CategorySwitch({
  grades,
  current,
  onPick,
  onAdd,
}: {
  grades: CandidateProfile['grades'];
  current: string;
  onPick: (specialization: string) => void;
  onAdd: () => void;
}) {
  const { title } = useReference();
  const withoutGrade = !grades.some((g) => g.specialization === current);
  return (
    <Card
      title="Мои категории"
      subtitle="Категорию можно подтвердить в нескольких направлениях – работодатель найдёт вас в каждом"
    >
      <div className="row-wrap">
        {grades.map((g) => (
          <Button
            key={g.specialization}
            size="sm"
            variant={g.specialization === current ? 'primary' : 'secondary'}
            onClick={() => onPick(g.specialization)}
          >
            {title('specializations', g.specialization)} · {levelTitle(g.level)}
          </Button>
        ))}
        {withoutGrade && (
          <Button size="sm" variant="primary" disabled>
            {title('specializations', current)} · без категории
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onAdd}>
          + Другое направление
        </Button>
      </div>
    </Card>
  );
}

/** Почему менялся грейд — подписи для истории. */
const GRADE_REASON: Record<string, string> = {
  initial: 'первое присвоение',
  promotion: 'повышение отдельным тестом',
  recommendation_accepted: 'принята рекомендация по результату',
  lowered_by_choice: 'тест уровнем ниже по вашему выбору',
};

export default function Assessment() {
  const navigate = useNavigate();
  const { ref } = useReference();
  // выбранное направление; без него — основное из профиля
  const [spec, setSpec] = useState<string | undefined>(undefined);
  const [adding, setAdding] = useState(false);
  const status = useAsync(
    () => api.get<AssessmentStatus>('/candidate/assessment/status', { specialization: spec }),
    [spec],
  );
  const profile = useAsync(() => api.get<CandidateProfile>('/candidate/profile'), []);
  const [openAttempt, setOpenAttempt] = useState<string | null>(null);

  const start = useAction(async (level: Level) => {
    const attempt = await api.post<Attempt>('/candidate/assessment/attempts', {
      specialization: status.data?.specialization,
      level,
    });
    navigate(`/candidate/assessment/attempt/${attempt.id}`);
  });

  const decide = useAction(async (accept: boolean) => {
    const path = accept
      ? '/candidate/assessment/recommendation/accept'
      : '/candidate/assessment/recommendation/decline';
    await api.post(path, { specialization: status.data?.specialization });
    status.reload();
  });

  // Демо-стенд: жюри проверяет воспроизводимость, проходя тест повторно без ожидания.
  const reset = useAction(async () => {
    await api.post('/dev/me/reset-assessment');
    status.reload();
  });

  if (status.loading && !status.data) return <Loading rows={4} />;
  if (status.error) return <ErrorNote error={status.error} />;
  if (!status.data) return null;

  const s = status.data;

  // Новая категория в другом направлении: опрос по нему, прежние категории остаются.
  if (adding) {
    return (
      <>
        <PageHeader
          title="Категория в другом направлении"
          subtitle="Опрос по новому направлению, затем тест. Уже подтверждённые категории сохраняются"
        />
        <div className="stack">
          <Survey
            onDone={() => {
              setAdding(false);
              setSpec(undefined); // после опроса основным становится новое направление
              status.reload();
              profile.reload();
            }}
          />
          <div>
            <Button onClick={() => setAdding(false)}>Отмена</Button>
          </div>
        </div>
      </>
    );
  }

  // Опрос — первый шаг: без него не из чего собирать тест.
  if (s.next_step === 'survey') {
    return (
      <>
        <PageHeader
          title="Опрос"
          subtitle="Три вопроса о направлении – и платформа соберёт персональный тест под заявленный грейд"
        />
        <Survey onDone={status.reload} />
      </>
    );
  }

  const policy = s.policy;

  return (
    <>
      <PageHeader
        title="Категория и тест"
        subtitle={`Отрасль: ${s.specialization_title ?? s.specialization}${
          s.track_title ? `, специализация: ${s.track_title}` : ''
        }. Категорию подтверждает тест, а не анкета`}
      />

      <div className="stack">
        {s.specialization && (profile.data?.grades.length ?? 0) > 0 && (
          <CategorySwitch
            grades={profile.data!.grades}
            current={s.specialization}
            onPick={setSpec}
            onAdd={() => setAdding(true)}
          />
        )}

        {s.active_attempt && (
          <Card title="Тест начат" subtitle={`Время идёт до ${dateTime(s.active_attempt.deadline_at)}`}>
            <Button
              variant="primary"
              onClick={() => navigate(`/candidate/assessment/attempt/${s.active_attempt!.id}`)}
            >
              Продолжить тест {levelTitle(s.active_attempt.declared_level)}
            </Button>
          </Card>
        )}

        {s.recommendation && (
          <Card title="Нужно ваше решение">
            <Alert tone="warn">{s.recommendation.message}</Alert>
            <ErrorNote error={decide.error} />
            <div className="row-wrap" style={{ marginTop: 'var(--sp-4)' }}>
              <Button variant="primary" busy={decide.busy} onClick={() => void decide.run(true)}>
                Принять уровень {levelTitle(s.recommendation.level)}
              </Button>
              <Button busy={decide.busy} onClick={() => void decide.run(false)}>
                Отказаться и пройти тест этого уровня
              </Button>
              <Button variant="ghost" onClick={() => setOpenAttempt(s.recommendation!.attempt_id)}>
                Посмотреть разбор попытки
              </Button>
            </div>
          </Card>
        )}

        {s.grade && (
          <Card
            title="Текущая категория"
            actions={<Badge tone="solid">{s.grade.category}</Badge>}
            subtitle={`Подтверждена ${date(s.grade.assigned_at)}. Это то, что видит работодатель`}
          >
            {policy && (
              <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
                Менять грейд можно не чаще раза в {policy.grade_change_cooldown_days} дней, повторять
                тест того же уровня – раз в {policy.same_level_retry_days} дней. Повышение – только
                отдельным тестом более высокого уровня
              </p>
            )}
          </Card>
        )}

        {s.grade?.promotion_offer && (
          <Alert tone="success" title={`Можно сразу пройти тест ${levelTitle(s.grade.promotion_offer.level)}`}>
            Ваш результат был выше текущего грейда. Чтобы повысить его, пройдите тест уровня{' '}
            {levelTitle(s.grade.promotion_offer.level)} – без ожидания смены грейда, до{' '}
            {date(s.grade.promotion_offer.until)}
          </Alert>
        )}

        {!s.active_attempt && (
          <Card
            title={s.grade ? 'Пройти тест другого уровня' : 'Выберите уровень теста'}
            subtitle={
              policy
                ? `${policy.test_size} заданий, ${policy.attempt_time_limit_minutes} минут. Ответы сохраняются сразу, попытка переживает перезагрузку страницы`
                : undefined
            }
          >
            <ErrorNote error={start.error} />
            <div className="grid-3">
              {(s.availability ?? []).map((a) => (
                <LevelCard
                  key={a.level}
                  item={a}
                  specialization={s.specialization_title ?? s.specialization ?? ''}
                  busy={start.busy}
                  onStart={(level) => void start.run(level)}
                />
              ))}
            </div>
          </Card>
        )}

        {!!s.competencies?.length && (
          <Card
            title="Компетенции"
            subtitle="Накопленная оценка по всем попыткам. Её же видит работодатель в карточке"
          >
            <CompetencyList items={s.competencies} />
          </Card>
        )}

        {!!s.attempts?.length && (
          <Card title="История попыток">
            <table className="table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Уровень</th>
                  <th className="table-num">Балл</th>
                  <th>Итог</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {s.attempts.map((a) => (
                  <tr key={a.id}>
                    <td>{date(a.finished_at ?? a.started_at)}</td>
                    <td>{levelTitle(a.declared_level)}</td>
                    <td className="table-num">{a.score ?? '–'}</td>
                    <td className="muted">{a.applied?.message ?? a.outcome ?? '–'}</td>
                    <td style={{ textAlign: 'right' }}>
                      <Button size="sm" variant="ghost" onClick={() => setOpenAttempt(a.id)}>
                        Разбор
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}

        {!!s.grade_history?.length && (
          <Card title="История грейда">
            <ul className="stack-sm" style={{ fontSize: 'var(--text-sm)' }}>
              {s.grade_history.map((h, i) => (
                <li key={i} className="row" style={{ gap: 'var(--sp-3)' }}>
                  <span className="mono faint" style={{ fontSize: 'var(--text-xs)' }}>
                    {date(h.at)}
                  </span>
                  <span>
                    {h.from_level ? `${levelTitle(h.from_level)} → ` : ''}
                    {levelTitle(h.to_level)}
                  </span>
                  <span className="muted">{GRADE_REASON[h.reason] ?? h.reason}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      {ref?.demo_mode && !!s.attempts?.length && (
        <div style={{ marginTop: 'var(--sp-5)' }}>
          <Card
            title="Демо-режим для жюри"
            subtitle="Сбросить попытки и грейд, чтобы пройти тест заново без ожидания и проверить воспроизводимость. Опрос сохранится"
          >
            <Button size="sm" busy={reset.busy} onClick={() => void reset.run()}>
              Сбросить попытки и грейд
            </Button>
            <ErrorNote error={reset.error} />
          </Card>
        </div>
      )}

      {openAttempt && <AttemptModal attemptId={openAttempt} onClose={() => setOpenAttempt(null)} />}
    </>
  );
}
