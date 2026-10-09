import { levelTitle, percent } from '../../lib/format';
import { Alert, Badge, Card, Meter } from '../../components/ui';
import type { AttemptResult } from '../../api/types';

const BUCKET_TITLE: Record<string, string> = {
  easy: 'Лёгкие',
  mid: 'Средние',
  hard: 'Сложные',
  top: 'Самые сложные',
};

/** Достоверность оценки компетенции приходит из банка заданий на английском. */
const CONFIDENCE_TITLE: Record<string, string> = {
  low: 'низкая',
  normal: 'средняя',
  high: 'высокая',
};

const OUTCOME_TONE: Record<string, 'success' | 'warn' | 'danger' | 'accent'> = {
  confirmed: 'success',
  promoted: 'success',
  recommended: 'warn',
  downgraded: 'warn',
  failed: 'danger',
};

/**
 * Разбор попытки для кандидата.
 *
 * Правильные ответы намеренно не показываются: иначе банк заданий утекал бы
 * через скриншоты результатов, а это ровно та проблема, от которой защищает
 * вся механика тестирования.
 */
const FINISH_REASON: Record<string, string> = {
  submitted: 'Завершена кандидатом',
  expired: 'Истекло время',
  demo_autofill: 'Демо-режим: оставшиеся ответы подставлены автоматически',
};

export default function AttemptResultView({
  result,
  declaredLevel,
}: {
  result: AttemptResult;
  declaredLevel: string;
}) {
  const buckets = Object.entries(result.difficulty_buckets).filter(([, b]) => b.items > 0);
  const flags = result.flags ?? [];

  return (
    <div className="stack">
      {flags.length > 0 && (
        <Alert tone="neutral" title="Признаки для разбора">
          {flags.map((f) => f.message).join('. ')}. На грейд они не влияют; работодатель увидит их в
          карточке рядом с результатом
        </Alert>
      )}
      <Card>
        <div className="row-top" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <div className="stack-sm">
            <Badge tone={OUTCOME_TONE[result.outcome] ?? 'accent'}>{result.outcome_title}</Badge>
            <h2>Заявленный уровень: {levelTitle(declaredLevel)}</h2>
            {result.applied?.message && (
              <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
                {result.applied.message}
              </p>
            )}
          </div>

          <div style={{ textAlign: 'center' }}>
            <div
              className="display"
              style={{ fontSize: 'var(--text-2xl)', fontWeight: 800, color: 'var(--violet-600)' }}
            >
              {result.score}
            </div>
            <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
              из 100
            </div>
          </div>
        </div>

        <div className="divider" style={{ margin: 'var(--sp-4) 0' }} />

        <dl className="kv">
          <dt>Набрано баллов</dt>
          <dd className="mono">
            {result.points_earned} из {result.points_possible}
          </dd>
          <dt>Случайное угадывание дало бы</dt>
          <dd className="mono">{result.chance_baseline}</dd>
          {result.finish_reason && (
            <>
              <dt>Как завершена</dt>
              <dd>{FINISH_REASON[result.finish_reason] ?? result.finish_reason}</dd>
            </>
          )}
        </dl>
      </Card>

      <Card
        title="По сложности заданий"
        subtitle="Грейд подтверждает не общий балл, а то, какой сложности задания вы решаете"
      >
        <table className="table">
          <thead>
            <tr>
              <th>Сложность</th>
              <th style={{ width: '38%' }}>Доля решённого</th>
              <th className="table-num">Решено</th>
              <th className="table-num">Баллы</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map(([key, b]) => (
              <tr key={key}>
                <td>{BUCKET_TITLE[key] ?? key}</td>
                <td>
                  <div className="row" style={{ gap: 'var(--sp-3)' }}>
                    <span className="mono" style={{ minWidth: 40 }}>
                      {percent(b.rate)}
                    </span>
                    <div style={{ flex: 1 }}>
                      <Meter value={b.rate} label={BUCKET_TITLE[key] ?? key} />
                    </div>
                  </div>
                </td>
                <td className="table-num">
                  {b.correct} / {b.items}
                </td>
                <td className="table-num">
                  {b.points_earned} / {b.points_possible}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {result.competencies.length > 0 && (
        <Card title="Компетенции" subtitle="Достоверность зависит от числа заданий по компетенции">
          <table className="table">
            <thead>
              <tr>
                <th>Компетенция</th>
                <th style={{ width: '38%' }}>Оценка</th>
                <th className="table-num">Заданий</th>
                <th>Достоверность</th>
              </tr>
            </thead>
            <tbody>
              {result.competencies.map((c) => (
                <tr key={c.competency}>
                  <td>{c.title}</td>
                  <td>
                    <div className="row" style={{ gap: 'var(--sp-3)' }}>
                      <span className="mono" style={{ minWidth: 40 }}>
                        {c.score}
                      </span>
                      <div style={{ flex: 1 }}>
                        <Meter value={c.score / 100} label={c.title} />
                      </div>
                    </div>
                  </td>
                  <td className="table-num">{c.items}</td>
                  <td className="muted">{CONFIDENCE_TITLE[c.confidence] ?? c.confidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {Object.entries(result.checks).map(([level, checks]) => (
        <Card
          key={level}
          title={`Проверки для уровня ${levelTitle(level)}`}
          subtitle="Все условия должны выполняться одновременно"
        >
          <ul className="stack-sm">
            {checks.map((c) => (
              <li key={c.check} className="row-top" style={{ gap: 'var(--sp-3)' }}>
                <span
                  aria-hidden
                  style={{
                    color: c.passed ? 'var(--green-500)' : 'var(--text-faint)',
                    fontWeight: 700,
                  }}
                >
                  {c.passed ? '✓' : '✕'}
                </span>
                <div>
                  <div style={{ fontSize: 'var(--text-sm)' }}>{c.title}</div>
                  <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                    {c.detail}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ))}

      <Alert tone="neutral">
        Правильные ответы по заданиям не раскрываются
      </Alert>
    </div>
  );
}
