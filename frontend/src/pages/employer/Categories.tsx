import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { candidateLink } from '../../lib/links';
import { count, levelTitle, salaryRange, years } from '../../lib/format';
import {
  Badge,
  Card,
  Empty,
  ErrorNote,
  Loading,
  Meter,
  PageHeader,
} from '../../components/ui';
import { cx } from '../../lib/cx';
import { MatchBreakdown, MatchNotes, ScoreDial } from '../../components/domain';
import type { CategoryCell, Paged, RankedCandidate } from '../../api/types';

const LEVELS = ['junior', 'middle', 'senior'] as const;

/** Список кандидатов выбранной категории, ранжированный по силе профиля. */
function CategoryCandidates({ specialization, level }: { specialization: string; level: string }) {
  const { data, loading, error } = useAsync(
    () => api.get<Paged<RankedCandidate>>(`/employer/categories/${specialization}/${level}/candidates`),
    [specialization, level],
  );

  if (loading) return <Loading rows={3} />;
  if (error) return <ErrorNote error={error} />;
  if (!data?.items.length) return <Empty title="В этой категории пока нет кандидатов" />;

  return (
    <div className="stack">
      <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
        Внутри категории выше те, у кого сильнее подтверждённый профиль: результат теста и
        достижения ФСП
      </p>

      {data.items.map((row, i) => (
        <article key={row.candidate.candidate_id} className="card">
          <div className="row-top" style={{ gap: 'var(--sp-4)' }}>
            <div className="display faint" style={{ fontWeight: 700, minWidth: 24 }}>
              {i + 1}
            </div>

            <div className="stack-sm" style={{ flex: 1, minWidth: 0 }}>
              <div className="row-wrap">
                <Link
                  to={candidateLink(row.candidate)}
                  style={{ fontFamily: 'var(--font-display)', fontWeight: 600, color: 'inherit' }}
                >
                  {row.candidate.display_name}
                </Link>
                {row.candidate.fsp?.linked && row.candidate.fsp.achievements.length > 0 && (
                  <Badge tone="solid">ФСП</Badge>
                )}
              </div>

              <div className="row-wrap muted" style={{ fontSize: 'var(--text-sm)' }}>
                {row.candidate.city && <span>{row.candidate.city}</span>}
                <span>· опыт {years(row.candidate.experience_years)}</span>
                {row.candidate.salary_expectation && (
                  <span>· ожидает {salaryRange(row.candidate.salary_expectation, null)}</span>
                )}
              </div>

              <MatchBreakdown match={row.ranking} compact />
              <MatchNotes match={row.ranking} />
            </div>

            <ScoreDial value={row.ranking.score} caption="сила профиля" />
          </div>
        </article>
      ))}
    </div>
  );
}

export default function Categories() {
  const { data, loading, error } = useAsync(() => api.get<CategoryCell[]>('/employer/categories'), []);
  const [picked, setPicked] = useState<{ specialization: string; level: string } | null>(null);

  const specializations = useMemo(() => {
    const seen = new Map<string, string>();
    for (const c of data ?? []) seen.set(c.specialization, c.specialization_title);
    return [...seen.entries()];
  }, [data]);

  const cellOf = (spec: string, level: string) =>
    data?.find((c) => c.specialization === spec && c.level === level);

  if (loading) return <Loading rows={4} />;
  if (error) return <ErrorNote error={error} />;

  return (
    <>
      <PageHeader
        title="Категории"
        subtitle="Категория – это связка специализации и подтверждённого грейда. Работодатель выбирает категорию, а не перебирает резюме"
      />

      <div className="stack">
        <Card title="Специализация × грейд">
          <div style={{ overflowX: 'auto' }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Специализация</th>
                  {LEVELS.map((l) => (
                    <th key={l}>{levelTitle(l)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {specializations.map(([slug, title]) => (
                  <tr key={slug}>
                    <td style={{ fontWeight: 600 }}>{title}</td>
                    {LEVELS.map((level) => {
                      const cell = cellOf(slug, level);
                      const on = picked?.specialization === slug && picked?.level === level;
                      if (!cell)
                        return (
                          <td key={level} className="faint">
                            –
                          </td>
                        );
                      return (
                        <td key={level}>
                          <button
                            type="button"
                            className={cx('card', 'card-interactive')}
                            aria-pressed={on}
                            style={{
                              padding: 'var(--sp-3)',
                              width: '100%',
                              textAlign: 'left',
                              cursor: 'pointer',
                              borderColor: on ? 'var(--violet-500)' : undefined,
                              background: on ? 'var(--violet-050)' : undefined,
                            }}
                            onClick={() => setPicked({ specialization: slug, level })}
                          >
                            <div className="display" style={{ fontWeight: 700 }}>
                              {cell.candidates}
                            </div>
                            <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                              с ФСП: {cell.with_fsp_achievements}
                            </div>
                            {!!cell.unconfirmed && (
                              <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                                + {cell.unconfirmed} с заявленным грейдом
                              </div>
                            )}
                            <div style={{ marginTop: 6 }}>
                              <Meter
                                value={cell.avg_profile_strength / 100}
                                label={`Средняя сила профиля ${cell.title}`}
                              />
                            </div>
                            <div className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 4 }}>
                              сила {Math.round(cell.avg_profile_strength)}
                            </div>
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {picked && (
          <Card
            title={`${specializations.find(([s]) => s === picked.specialization)?.[1]} · ${levelTitle(picked.level)}`}
            subtitle={count(
              cellOf(picked.specialization, picked.level)?.candidates ?? 0,
              'кандидат',
              'кандидата',
              'кандидатов',
            )}
          >
            <CategoryCandidates specialization={picked.specialization} level={picked.level} />
          </Card>
        )}
      </div>
    </>
  );
}
