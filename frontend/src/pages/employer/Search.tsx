import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction } from '../../lib/useAsync';
import { candidateLink } from '../../lib/links';
import { count, levelTitle, salaryRange, years } from '../../lib/format';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Chip,
  Empty,
  ErrorNote,
  Field,
  Input,
  PageHeader,
  Select,
} from '../../components/ui';
import { MatchBreakdown, MatchNotes, ScoreDial } from '../../components/domain';
import InviteModal from './InviteModal';
import type { CandidateCard, Paged, RankedCandidate, SearchFilters } from '../../api/types';

/**
 * Поиск по всему банку кандидатов. В отличие от подборки здесь нет
 * потребности, поэтому ранжирование идёт по силе профиля, а не по
 * соответствию конкретной задаче.
 */
export default function Search() {
  const { ref, skillsFor } = useReference();
  const [filters, setFilters] = useState<SearchFilters>({ limit: 30 });
  const [result, setResult] = useState<Paged<RankedCandidate> | null>(null);
  const [inviting, setInviting] = useState<CandidateCard | null>(null);

  const run = useAction(async () => {
    setResult(await api.post<Paged<RankedCandidate>>('/employer/candidates/search', filters));
  });

  const set = (patch: Partial<SearchFilters>) => setFilters((f) => ({ ...f, ...patch }));

  return (
    <>
      <PageHeader
        title="Поиск по банку кандидатов"
        subtitle="Вся база: сначала кандидаты с подтверждённым тестом грейдом, ниже – с заявленным. Фильтры – по отрасли, специализации, грейду, стеку и достижениям ФСП"
      />

      <div className="stack">
        <Card>
          <div className="stack">
            <div className="grid-3">
              <Field label="Отрасль (IT-направление)">
                {(p) => (
                  <Select
                    {...p}
                    value={filters.specialization ?? ''}
                    onChange={(e) => set({ specialization: e.target.value || null, stack_all: null, track: null })}
                  >
                    <option value="">Любая</option>
                    {ref?.specializations.map((s) => (
                      <option key={s.slug} value={s.slug}>
                        {s.title}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>

              <Field label="Грейд">
                {(p) => (
                  <Select
                    {...p}
                    value={filters.levels?.[0] ?? ''}
                    onChange={(e) => set({ levels: e.target.value ? [e.target.value] : null })}
                  >
                    <option value="">Любой</option>
                    {ref?.levels.map((l) => (
                      <option key={l.slug} value={l.slug}>
                        {levelTitle(l.slug)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>

              <Field label="Формат работы">
                {(p) => (
                  <Select
                    {...p}
                    value={filters.work_format ?? ''}
                    onChange={(e) => set({ work_format: e.target.value || null })}
                  >
                    <option value="">Любой</option>
                    {ref?.work_formats.map((w) => (
                      <option key={w.slug} value={w.slug}>
                        {w.title}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>

              <Field label="Город" hint="И кандидаты из других городов, готовые к переезду">
                {(p) => (
                  <Input
                    {...p}
                    value={filters.city ?? ''}
                    onChange={(e) => set({ city: e.target.value || null })}
                  />
                )}
              </Field>

              <Field label="Ожидания не выше, ₽">
                {(p) => (
                  <Input
                    {...p}
                    type="number"
                    min="0"
                    value={filters.salary_max ?? ''}
                    onChange={(e) => set({ salary_max: e.target.value ? Number(e.target.value) : null })}
                  />
                )}
              </Field>

              <Field label="Поиск по тексту">
                {(p) => (
                  <Input
                    {...p}
                    value={filters.text ?? ''}
                    placeholder="Kafka, платежи…"
                    onChange={(e) => set({ text: e.target.value || null })}
                  />
                )}
              </Field>
            </div>

            {filters.specialization && !!ref?.tracks?.[filters.specialization]?.length && (
              <div style={{ maxWidth: 320 }}>
                <Field label="Специализация">
                  {(p) => (
                    <Select {...p} value={filters.track ?? ''} onChange={(e) => set({ track: e.target.value || null })}>
                      <option value="">Любая</option>
                      {(ref?.tracks?.[filters.specialization!] ?? []).map((t) => (
                        <option key={t.slug} value={t.slug}>
                          {t.title}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              </div>
            )}

            <div className="row-wrap" style={{ gap: 'var(--sp-5)' }}>
              <Checkbox
                checked={Boolean(filters.has_fsp)}
                onChange={(v) => set({ has_fsp: v || null })}
                label="Только с подтверждёнными достижениями ФСП"
              />
              <Checkbox
                checked={Boolean(filters.confirmed_only)}
                onChange={(v) => set({ confirmed_only: v })}
                label="Только с грейдом, подтверждённым тестом"
              />
              <Checkbox
                checked={Boolean(filters.hide_minors)}
                onChange={(v) => set({ hide_minors: v })}
                label="Скрыть кандидатов младше 18 лет"
              />
            </div>

            <div>
              <div className="field-label" style={{ marginBottom: 'var(--sp-2)' }}>
                Обязательный стек
              </div>
              <div className="row-wrap">
                {skillsFor(filters.specialization)
                  .slice(0, 28)
                  .map((s) => {
                    const on = filters.stack_all?.includes(s.slug) ?? false;
                    return (
                      <Chip
                        key={s.slug}
                        active={on}
                        onClick={() =>
                          set({
                            stack_all: on
                              ? (filters.stack_all ?? []).filter((x) => x !== s.slug)
                              : [...(filters.stack_all ?? []), s.slug],
                          })
                        }
                      >
                        {s.title}
                      </Chip>
                    );
                  })}
              </div>
            </div>

            <div className="row">
              <Button variant="primary" busy={run.busy} onClick={() => void run.run()}>
                Найти
              </Button>
              <Button variant="ghost" onClick={() => setFilters({ limit: 30 })}>
                Сбросить
              </Button>
            </div>
          </div>
        </Card>

        <ErrorNote error={run.error} />

        {result && (
          <>
            <p className="muted">
              Найдено {count(result.total, 'кандидат', 'кандидата', 'кандидатов')}
              {result.total > result.items.length ? `, показано ${result.items.length}` : ''}
            </p>

            {!result.items.length && (
              <Empty title="Никого не нашли">Ослабьте фильтры и попробуйте ещё раз</Empty>
            )}

            {result.items.map((row) => (
              <article key={row.candidate.candidate_id} className="card">
                <div className="row-top" style={{ gap: 'var(--sp-4)' }}>
                  <div className="stack-sm" style={{ flex: 1, minWidth: 0 }}>
                    <div className="row-wrap">
                      <Link
                        to={candidateLink(row.candidate)}
                        style={{
                          fontFamily: 'var(--font-display)',
                          fontWeight: 600,
                          color: 'inherit',
                        }}
                      >
                        {row.candidate.display_name}
                      </Link>
                      {row.candidate.category && (
                        <Badge tone="accent">
                          {row.candidate.category.specialization_title} ·{' '}
                          {levelTitle(row.candidate.category.level)}
                        </Badge>
                      )}
                      {row.candidate.fsp?.linked && row.candidate.fsp.achievements.length > 0 && (
                        <Badge tone="solid">ФСП</Badge>
                      )}
                    </div>

                    <div className="row-wrap muted" style={{ fontSize: 'var(--text-sm)' }}>
                      {row.candidate.city && <span>{row.candidate.city}</span>}
                      {row.candidate.relocation && <span>· готов к переезду</span>}
                      <span>· опыт {years(row.candidate.experience_years)}</span>
                      {row.candidate.salary_expectation && (
                        <span>· ожидает {salaryRange(row.candidate.salary_expectation, null)}</span>
                      )}
                    </div>

                    <MatchBreakdown match={row.ranking} compact />
                    <MatchNotes match={row.ranking} />

                    <div className="row-wrap" style={{ marginTop: 'var(--sp-2)' }}>
                      <Button size="sm" variant="primary" onClick={() => setInviting(row.candidate)}>
                        Пригласить
                      </Button>
                      <Link
                        className="btn btn-secondary btn-sm"
                        to={candidateLink(row.candidate)}
                      >
                        Карточка
                      </Link>
                    </div>
                  </div>

                  <ScoreDial value={row.ranking.score} caption="сила профиля" />
                </div>
              </article>
            ))}
          </>
        )}
      </div>

      {inviting && (
        <InviteModal
          candidate={inviting}
          onClose={() => setInviting(null)}
          onSent={() => undefined}
        />
      )}
    </>
  );
}
