import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction, useAsync } from '../../lib/useAsync';
import { candidateLink } from '../../lib/links';
import { count, levelTitle, money, percent, salaryRange, years } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Chip,
  Empty,
  ErrorNote,
  Field,
  Input,
  Loading,
  PageHeader,
  Select,
} from '../../components/ui';
import { cx } from '../../lib/cx';
import { MatchBreakdown, MatchNotes, ScoreDial } from '../../components/domain';
import InviteModal from './InviteModal';
import type { CandidateCard, Need, SearchFilters, Selection, SelectionRow } from '../../api/types';

/** Человеческая подпись фильтра для «хлебных крошек» цепочки уточнений. */
function describeFilters(p: SearchFilters): string {
  const parts: string[] = [];
  if (p.has_fsp) parts.push('с достижениями ФСП');
  if (p.confirmed_only) parts.push('только подтверждённые');
  if (p.levels?.length) parts.push(p.levels.map(levelTitle).join(', '));
  if (p.stack_all?.length) parts.push(`стек: ${p.stack_all.join(', ')}`);
  if (p.city) parts.push(p.city);
  if (p.work_format) parts.push(p.work_format);  // слаг: короче в цепочке
  if (p.within_budget) parts.push('в рамках вилки');
  if (p.salary_max) parts.push(`до ${money(p.salary_max)}`);
  if (p.min_score) parts.push(`балл от ${p.min_score}`);
  if (p.text) parts.push(`«${p.text}»`);
  return parts.length ? parts.join(' · ') : 'Исходная подборка';
}

function ResultRow({
  row,
  onInvite,
}: {
  row: SelectionRow;
  onInvite: (c: CandidateCard) => void;
}) {
  const c = row.candidate;
  const [open, setOpen] = useState(false);

  return (
    <article className="card">
      <div className="row-top" style={{ gap: 'var(--sp-4)' }}>
        <div
          className="display faint"
          style={{ fontSize: 'var(--text-md)', fontWeight: 700, minWidth: 28 }}
        >
          {row.rank}
        </div>

        <div className="stack-sm" style={{ flex: 1, minWidth: 0 }}>
          <div className="row-wrap">
            <Link
              to={candidateLink(c)}
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 'var(--text-md)',
                fontWeight: 600,
                color: 'inherit',
              }}
            >
              {c.display_name}
            </Link>
            <Badge tone="accent">{row.match.category_role}</Badge>
            {c.fsp?.linked && c.fsp.achievements.length > 0 && <Badge tone="solid">ФСП</Badge>}
            {!c.open_to_offers && <Badge tone="neutral">не ищет работу</Badge>}
          </div>

          <div className="row-wrap muted" style={{ fontSize: 'var(--text-sm)' }}>
            {c.category && <span>{levelTitle(c.category.level)}</span>}
            {c.city && <span>· {c.city}</span>}
            <span>· опыт {years(c.experience_years)}</span>
            {c.salary_expectation && <span>· ожидает {salaryRange(c.salary_expectation, null)}</span>}
            {c.test && <span>· тест {c.test.score}</span>}
          </div>

          <MatchBreakdown match={row.match} compact={!open} />

          {c.fsp?.headline && (
            <div style={{ fontSize: 'var(--text-sm)', color: 'var(--violet-700)' }}>
              {c.fsp.headline}
            </div>
          )}

          {open && (
            <div className="stack-sm" style={{ marginTop: 'var(--sp-2)' }}>
              <MatchNotes match={row.match} />
              {c.stack.length > 0 && (
                <div className="row-wrap">
                  {c.stack.map((s) => (
                    <Chip key={s.slug}>{s.title}</Chip>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="row-wrap" style={{ marginTop: 'var(--sp-2)' }}>
            <Button size="sm" variant="primary" onClick={() => onInvite(c)}>
              Пригласить
            </Button>
            <Link className="btn btn-secondary btn-sm" to={candidateLink(c)}>
              Открыть карточку
            </Link>
            <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)}>
              {open ? 'Свернуть' : 'Почему в подборке'}
            </Button>
          </div>
        </div>

        <ScoreDial value={row.match.score} caption="соответствие" />
      </div>
    </article>
  );
}

/** Панель уточнения. Уточнение создаёт новую подборку, не теряя прежнюю. */
function RefinePanel({
  filters,
  onChange,
  onApply,
  busy,
  specialization,
}: {
  filters: SearchFilters;
  onChange: (next: SearchFilters) => void;
  onApply: () => void;
  busy: boolean;
  specialization: string | undefined;
}) {
  const { ref, skillsFor } = useReference();

  return (
    <Card title="Уточнить подборку" subtitle="Прежняя подборка сохранится – к ней можно вернуться">
      <div className="stack">
        <div className="grid-3">
          <Field label="Грейд">
            {(p) => (
              <Select
                {...p}
                value={filters.levels?.[0] ?? ''}
                onChange={(e) => onChange({ ...filters, levels: e.target.value ? [e.target.value] : null })}
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

          <Field label="Город">
            {(p) => (
              <Input
                {...p}
                value={filters.city ?? ''}
                onChange={(e) => onChange({ ...filters, city: e.target.value || null })}
              />
            )}
          </Field>

          <Field label="Формат работы">
            {(p) => (
              <Select
                {...p}
                value={filters.work_format ?? ''}
                onChange={(e) => onChange({ ...filters, work_format: e.target.value || null })}
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

          <Field label="Балл соответствия от">
            {(p) => (
              <Input
                {...p}
                type="number"
                min="0"
                max="100"
                value={filters.min_score ?? ''}
                onChange={(e) =>
                  onChange({ ...filters, min_score: e.target.value ? Number(e.target.value) : null })
                }
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
                onChange={(e) =>
                  onChange({ ...filters, salary_max: e.target.value ? Number(e.target.value) : null })
                }
              />
            )}
          </Field>

          <Field label="Поиск по тексту">
            {(p) => (
              <Input
                {...p}
                value={filters.text ?? ''}
                placeholder="Kafka, финтех…"
                onChange={(e) => onChange({ ...filters, text: e.target.value || null })}
              />
            )}
          </Field>
        </div>

        <div className="row-wrap" style={{ gap: 'var(--sp-5)' }}>
          <Checkbox
            checked={Boolean(filters.has_fsp)}
            onChange={(v) => onChange({ ...filters, has_fsp: v || null })}
            label="Только с подтверждёнными достижениями ФСП"
          />
          <Checkbox
            checked={Boolean(filters.within_budget)}
            onChange={(v) => onChange({ ...filters, within_budget: v })}
            label="Ожидания укладываются в вилку"
          />
          <Checkbox
            checked={Boolean(filters.confirmed_only)}
            onChange={(v) => onChange({ ...filters, confirmed_only: v })}
            label="Только с грейдом, подтверждённым тестом"
          />
        </div>

        <div>
          <div className="field-label" style={{ marginBottom: 'var(--sp-2)' }}>
            Обязательный стек
          </div>
          <div className="row-wrap">
            {skillsFor(specialization)
              .slice(0, 24)
              .map((s) => {
                const on = filters.stack_all?.includes(s.slug) ?? false;
                return (
                  <Chip
                    key={s.slug}
                    active={on}
                    onClick={() =>
                      onChange({
                        ...filters,
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
          <Button variant="primary" busy={busy} onClick={onApply}>
            Уточнить
          </Button>
          <Button variant="ghost" onClick={() => onChange({})}>
            Сбросить фильтры
          </Button>
        </div>
      </div>
    </Card>
  );
}

export default function SelectionPage() {
  const [params, setParams] = useSearchParams();
  const needs = useAsync(() => api.get<Need[]>('/employer/needs'), []);

  const needId = params.get('need') ?? '';
  const need = useMemo(() => needs.data?.find((n) => n.id === needId), [needs.data, needId]);

  const [selection, setSelection] = useState<Selection | null>(null);
  const [filters, setFilters] = useState<SearchFilters>({});
  const [inviting, setInviting] = useState<CandidateCard | null>(null);

  // Если потребность не выбрана, берём первую — экран сразу показывает смысл.
  useEffect(() => {
    if (!needId && needs.data?.length) {
      setParams({ need: needs.data[0].id }, { replace: true });
    }
  }, [needs.data, needId, setParams]);

  const build = useAction(async (nid: string, f: SearchFilters) => {
    const s = await api.post<Selection>(`/employer/needs/${nid}/selections`, f);
    setSelection(s);
  });

  const refine = useAction(async (selectionId: string, f: SearchFilters) => {
    const s = await api.post<Selection>(`/employer/selections/${selectionId}/refine`, f);
    setSelection(s);
  });

  const openChainLink = useAction(async (id: string) => {
    const s = await api.get<Selection>(`/employer/selections/${id}`);
    setSelection(s);
    setFilters(s.params as SearchFilters);
  });

  // Первая подборка строится автоматически при выборе потребности.
  useEffect(() => {
    if (!needId) return;
    setSelection(null);
    setFilters({});
    void build.run(needId, {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needId]);

  if (needs.loading) return <Loading rows={4} />;
  if (needs.error) return <ErrorNote error={needs.error} />;

  if (!needs.data?.length) {
    return (
      <>
        <PageHeader title="Подборка кандидатов" />
        <Empty
          title="Сначала опишите потребность"
          action={
            <Link className="btn btn-primary" to="/employer/needs/new">
              Описать потребность
            </Link>
          }
        >
          Подборка строится по профилю компетенций, а он собирается из описания задачи
        </Empty>
      </>
    );
  }

  const busy = build.busy || refine.busy || openChainLink.busy;
  const chain = selection?.chain ?? [];

  return (
    <>
      <PageHeader
        title="Подборка кандидатов"
        subtitle="Выдача построена на категориях, подтверждённых тестом, а не на самоописанном резюме. У каждого места видно, из чего сложился балл"
        actions={
          <Link className="btn btn-secondary btn-sm" to="/employer/needs">
            Все потребности
          </Link>
        }
      />

      <div className="stack">
        <Card title="Потребность">
          <div className="grid-2">
            <Field label="Под какую задачу ищем">
              {(p) => (
                <Select
                  {...p}
                  value={needId}
                  onChange={(e) => setParams({ need: e.target.value })}
                >
                  {needs.data!.map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.title}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {need && (
              <div className="stack-sm">
                <div className="field-label">Вилка</div>
                <div className="salary salary-md">
                  {salaryRange(need.salary_from, need.salary_to)}
                </div>
              </div>
            )}
          </div>

          {need && (
            <div className="row-wrap" style={{ marginTop: 'var(--sp-4)' }}>
              {need.profile.top_competencies.slice(0, 6).map((c) => (
                <Chip key={c.competency} title={c.sources.join(' · ')}>
                  {c.title} {percent(c.weight)}
                </Chip>
              ))}
            </div>
          )}
        </Card>

        <ErrorNote error={build.error} />
        <ErrorNote error={refine.error} />

        {busy && !selection && <Loading rows={4} />}

        {selection && (
          <>
            <Card title="Рекомендованные категории" subtitle="Кого платформа считает подходящим под эту потребность">
              <div className="grid-3">
                {selection.summary.recommended_categories.map((rc) => (
                  <div key={`${rc.level}-${rc.role}`} className="card" style={{ padding: 'var(--sp-4)' }}>
                    <Badge tone="accent">{rc.role}</Badge>
                    <div
                      className="display"
                      style={{ fontSize: 'var(--text-lg)', fontWeight: 700, marginTop: 'var(--sp-2)' }}
                    >
                      {levelTitle(rc.level)}
                    </div>
                    <div className="muted" style={{ fontSize: 'var(--text-sm)' }}>
                      {count(rc.candidates, 'кандидат', 'кандидата', 'кандидатов')}
                    </div>
                  </div>
                ))}
              </div>
              <p className="muted" style={{ fontSize: 'var(--text-sm)', marginTop: 'var(--sp-4)' }}>
                Всего подошло {selection.summary.total_matched}, показано {selection.summary.shown}
                {selection.unavailable
                  ? ` · ${count(selection.unavailable, 'кандидат больше недоступен', 'кандидата больше недоступны', 'кандидатов больше недоступны')} (закрыли профиль или удалили учётную запись)`
                  : ''}
              </p>
            </Card>

            {chain.length > 1 && (
              <Card title="Цепочка уточнений" subtitle="К любой предыдущей подборке можно вернуться">
                <div className="row-wrap">
                  {chain.map((link, i) => (
                    <span key={link.id} className="row" style={{ gap: 'var(--sp-2)' }}>
                      {i > 0 && <span className="faint">→</span>}
                      <Chip
                        active={link.id === selection.id}
                        onClick={() => void openChainLink.run(link.id)}
                        title={`${link.total} кандидатов`}
                      >
                        {describeFilters(link.params)} · {link.total}
                      </Chip>
                    </span>
                  ))}
                  {!chain.some((l) => l.id === selection.id) && (
                    <span className="row" style={{ gap: 'var(--sp-2)' }}>
                      <span className="faint">→</span>
                      <Chip active>
                        {describeFilters(selection.params as SearchFilters)} ·{' '}
                        {selection.summary.total_matched}
                      </Chip>
                    </span>
                  )}
                </div>
              </Card>
            )}

            <RefinePanel
              filters={filters}
              onChange={setFilters}
              busy={busy}
              specialization={need?.specialization}
              onApply={() => void refine.run(selection.id, filters)}
            />

            <div className={cx('stack', busy && 'is-busy')} style={{ opacity: busy ? 0.6 : 1 }}>
              {selection.results.length ? (
                selection.results.map((row) => (
                  <ResultRow key={row.candidate_id} row={row} onInvite={setInviting} />
                ))
              ) : (
                <Empty title="Под эти фильтры никто не подошёл">
                  Ослабьте условия или вернитесь к предыдущей подборке в цепочке выше
                </Empty>
              )}
            </div>

            {selection.results.length > 0 && (
              <Alert tone="neutral">
                Контакты кандидата откроются, когда он примет приглашение или откликнется сам
              </Alert>
            )}
          </>
        )}
      </div>

      {inviting && (
        <InviteModal
          candidate={inviting}
          need={need}
          selectionId={selection?.id}
          onClose={() => setInviting(null)}
          onSent={() => undefined}
        />
      )}
    </>
  );
}
