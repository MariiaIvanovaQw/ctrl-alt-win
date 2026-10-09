import { useState } from 'react';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAsync } from '../../lib/useAsync';
import { levelTitle, percent, salaryRange } from '../../lib/format';
import {
  Alert,
  Badge,
  Card,
  Chip,
  ErrorNote,
  Field,
  Loading,
  Meter,
  Select,
  Tabs,
} from '../../components/ui';
import type { Level } from '../../api/types';

type TopCompetency = { competency: string; title: string; weight: number; sources: string[] };

type Variant = {
  seed: number;
  test_label: string;
  points_total: number;
  by_type: Record<string, number>;
  competencies: string[];
  items: {
    position: number;
    item_id: string;
    variant_id: string;
    type: string;
    competency: string;
    difficulty: number;
    score: number;
  }[];
};

type ProfileDetail = {
  category: { specialization: string; level: Level };
  role_profile: {
    title: string;
    summary: string;
    responsibilities: string[];
    typical_stack: string[];
  };
  competency_profile: { top_competencies: TopCompetency[]; competency_weights: Record<string, number> };
  blueprint: { type: string; difficulty_from: number; difficulty_to: number; count: number }[];
  mandatory_competencies: string[];
  rules: {
    test_size: number;
    competency_cap: number;
    min_competencies: number;
    grade_rules: Record<string, Record<string, number>>;
  };
  variants: Variant[];
  /** Доля общих заданий у двух разных кандидатов одной категории. */
  overlap_first_two: number;
  coverage: {
    seeds_simulated: number;
    competencies: {
      competency: string;
      title: string;
      weight: number;
      mandatory_in_test: boolean;
      share_of_attempts: number;
      items_per_attempt: number;
    }[];
  };
};

type DemoVacancy = {
  title: string;
  specialization: string;
  level: Level;
  description: string;
  stack: string[];
  city: string | null;
  salary_from: number;
  salary_to: number;
  profile: { top_competencies: TopCompetency[]; skills: string[]; skills_from_text: string[] };
};

const TYPE_TITLE: Record<string, string> = {
  theory: 'Теория',
  situational: 'Ситуация',
  practical: 'Практика',
};

/** Карта заданий одного варианта: цвет — тип, высота — сложность. */
function VariantMap({ variant }: { variant: Variant }) {
  const color: Record<string, string> = {
    theory: 'var(--violet-300)',
    situational: 'var(--violet-500)',
    practical: 'var(--brand-ink)',
  };

  return (
    <div className="stack-sm">
      <div className="row-wrap" style={{ gap: 'var(--sp-3)' }}>
        <span className="mono" style={{ fontSize: 'var(--text-xs)' }}>
          {variant.test_label}
        </span>
        <Badge tone="neutral">сид {variant.seed}</Badge>
        <Badge tone="accent">{variant.points_total} баллов</Badge>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: 2,
          height: 64,
          padding: 'var(--sp-2)',
          background: 'var(--paper-100)',
          borderRadius: 'var(--radius)',
        }}
      >
        {variant.items.map((it) => (
          <div
            key={it.position}
            title={`№${it.position + 1} · ${TYPE_TITLE[it.type] ?? it.type} · сложность ${it.difficulty} · ${it.score} балла`}
            style={{
              flex: 1,
              height: `${(it.difficulty / 10) * 100}%`,
              minHeight: 4,
              background: color[it.type] ?? 'var(--brand-gray)',
              borderRadius: 2,
            }}
          />
        ))}
      </div>

      <div className="row-wrap" style={{ fontSize: 'var(--text-xs)' }}>
        {Object.entries(variant.by_type).map(([t, n]) => (
          <span key={t} className="row" style={{ gap: 6 }}>
            <span
              aria-hidden
              style={{ width: 8, height: 8, borderRadius: 2, background: color[t] ?? 'var(--brand-gray)' }}
            />
            <span className="muted">
              {TYPE_TITLE[t] ?? t}: {n} баллов
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

function ProfileExplainer({ specialization, level }: { specialization: string; level: Level }) {
  const { data, loading, error } = useAsync(
    () => api.anon.get<ProfileDetail>(`/assessment/profiles/${specialization}/${level}`),
    [specialization, level],
  );

  if (loading) return <Loading rows={4} />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  const [v1, v2] = data.variants;
  const shared = v1 && v2 ? v1.items.filter((a) => v2.items.some((b) => b.item_id === a.item_id)) : [];

  return (
    <div className="stack">
      <Card title="1. Ролевой профиль" subtitle={data.role_profile.title}>
        <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
          {data.role_profile.summary}
        </p>
        <ul className="stack-sm" style={{ marginTop: 'var(--sp-3)', fontSize: 'var(--text-sm)' }}>
          {data.role_profile.responsibilities.map((r) => (
            <li key={r} className="row-top" style={{ gap: 'var(--sp-2)' }}>
              <span style={{ color: 'var(--violet-500)' }} aria-hidden>
                –
              </span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
        <div className="row-wrap" style={{ marginTop: 'var(--sp-4)' }}>
          {data.role_profile.typical_stack.map((s) => (
            <Chip key={s}>{s}</Chip>
          ))}
        </div>
      </Card>

      <Card
        title="2. Веса компетенций"
        subtitle="Профиль роли задаёт, что именно надо измерить и насколько это важно"
      >
        <table className="table">
          <thead>
            <tr>
              <th>Компетенция</th>
              <th style={{ width: '32%' }}>Вес</th>
              <th>Откуда взялся вес</th>
            </tr>
          </thead>
          <tbody>
            {data.competency_profile.top_competencies.map((c) => (
              <tr key={c.competency}>
                <td>
                  {c.title}
                  {data.mandatory_competencies.includes(c.competency) && (
                    <>
                      {' '}
                      <Badge tone="accent">обязательна</Badge>
                    </>
                  )}
                </td>
                <td>
                  <div className="row" style={{ gap: 'var(--sp-3)' }}>
                    <span className="mono" style={{ minWidth: 40 }}>
                      {percent(c.weight)}
                    </span>
                    <div style={{ flex: 1 }}>
                      <Meter value={c.weight} label={c.title} />
                    </div>
                  </div>
                </td>
                <td className="muted" style={{ fontSize: 'var(--text-xs)' }}>
                  {c.sources.join(' · ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        title="3. План теста"
        subtitle={`${data.rules.test_size} заданий: сколько и какой сложности берём по каждому типу`}
      >
        <table className="table">
          <thead>
            <tr>
              <th>Тип задания</th>
              <th>Сложность</th>
              <th className="table-num">Количество</th>
            </tr>
          </thead>
          <tbody>
            {data.blueprint.map((b, i) => (
              <tr key={i}>
                <td>{TYPE_TITLE[b.type] ?? b.type}</td>
                <td className="mono">
                  {b.difficulty_from}–{b.difficulty_to}
                </td>
                <td className="table-num">{b.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted" style={{ fontSize: 'var(--text-xs)', marginTop: 'var(--sp-3)' }}>
          Не более {data.rules.competency_cap} заданий на одну компетенцию, минимум{' '}
          {data.rules.min_competencies} компетенций в тесте
        </p>
      </Card>

      <Card
        title="4. Два кандидата – два разных набора"
        subtitle="План один, задания разные. Сумма баллов совпадает, поэтому результаты сопоставимы"
      >
        <div className="grid-2">
          {data.variants.map((v) => (
            <VariantMap key={v.seed} variant={v} />
          ))}
        </div>

        <Alert tone="info" title={`Пересечение: ${percent(data.overlap_first_two)}`}>
          Из {v1?.items.length ?? 0} заданий у двух кандидатов совпали {shared.length}. Максимальная
          сумма баллов при этом одна и та же – {v1?.points_total}
        </Alert>
      </Card>

      <Card
        title="5. Что измеряет тест"
        subtitle={`Симуляция на ${data.coverage.seeds_simulated} сидах: как часто компетенция попадает в тест`}
      >
        <table className="table">
          <thead>
            <tr>
              <th>Компетенция</th>
              <th className="table-num">Вес</th>
              <th style={{ width: '28%' }}>Доля попыток</th>
              <th className="table-num">Заданий в попытке</th>
            </tr>
          </thead>
          <tbody>
            {data.coverage.competencies.map((c) => (
              <tr key={c.competency}>
                <td>
                  {c.title}
                  {c.mandatory_in_test && (
                    <>
                      {' '}
                      <Badge tone="accent">всегда</Badge>
                    </>
                  )}
                </td>
                <td className="table-num">{percent(c.weight)}</td>
                <td>
                  <div className="row" style={{ gap: 'var(--sp-3)' }}>
                    <span className="mono" style={{ minWidth: 40 }}>
                      {percent(c.share_of_attempts)}
                    </span>
                    <div style={{ flex: 1 }}>
                      <Meter value={c.share_of_attempts} label={c.title} />
                    </div>
                  </div>
                </td>
                <td className="table-num">{c.items_per_attempt.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        title="6. Когда грейд подтверждён"
        subtitle="Пороги проверяются по итогам попытки. Понизить грейд принудительно нельзя – только с согласия кандидата"
      >
        <div className="grid-2">
          {Object.entries(data.rules.grade_rules).map(([lvl, rules]) => (
            <div key={lvl} className="card" style={{ padding: 'var(--sp-4)' }}>
              <h4 style={{ marginBottom: 'var(--sp-3)' }}>{levelTitle(lvl)}</h4>
              <dl className="kv">
                {Object.entries(rules).map(([k, v]) => (
                  <div key={k} style={{ display: 'contents' }}>
                    <dt style={{ fontSize: 'var(--text-xs)' }}>{RULE_TITLE[k] ?? k}</dt>
                    <dd className="mono">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

const RULE_TITLE: Record<string, string> = {
  overall_min: 'Минимальный балл',
  chance_margin_min: 'Отрыв от угадывания',
  mid_plus_rate_min: 'Доля решённых средних и сложных',
  mid_plus_solved_min: 'Решено средних и сложных, шт.',
  easy_rate_min: 'Доля решённых лёгких',
  mid_rate_min: 'Доля решённых средних',
  key_floor: 'Порог по ключевой компетенции',
  key_below_allowed: 'Сколько ключевых можно провалить',
};

function DemoVacancies() {
  const { data, loading, error } = useAsync(
    () => api.anon.get<DemoVacancy[]>('/assessment/demo-vacancies'),
    [],
  );

  if (loading) return <Loading rows={3} />;
  if (error) return <ErrorNote error={error} />;

  return (
    <div className="stack">
      <Alert tone="info">
        Описание вакансии разбирается автоматически: из текста извлекаются навыки, к ним добавляется
        профиль роли – получается набор весов компетенций, по которому и строится подборка
      </Alert>

      {data?.map((v) => (
        <Card
          key={v.title}
          title={v.title}
          subtitle={`${v.city ?? 'город не указан'} · ${salaryRange(v.salary_from, v.salary_to)}`}
        >
          <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
            {v.description}
          </p>

          <div className="grid-2" style={{ marginTop: 'var(--sp-4)' }}>
            <div className="stack-sm">
              <h4>Навыки</h4>
              <div className="row-wrap">
                {v.profile.skills.map((s) => (
                  <Chip key={s}>{s}</Chip>
                ))}
              </div>
              {v.profile.skills_from_text.length > 0 && (
                <>
                  <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                    распознано прямо из текста вакансии:
                  </div>
                  <div className="row-wrap">
                    {v.profile.skills_from_text.map((s) => (
                      <Chip key={s} active>
                        {s}
                      </Chip>
                    ))}
                  </div>
                </>
              )}
            </div>

            <div className="stack-sm">
              <h4>Что будем искать</h4>
              {v.profile.top_competencies.slice(0, 5).map((c) => (
                <div key={c.competency} className="row" style={{ gap: 'var(--sp-3)' }}>
                  <span style={{ flex: 1, fontSize: 'var(--text-sm)' }}>{c.title}</span>
                  <span className="mono" style={{ fontSize: 'var(--text-xs)', minWidth: 36 }}>
                    {percent(c.weight)}
                  </span>
                  <div style={{ width: 90 }}>
                    <Meter value={c.weight} label={c.title} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

export default function HowTestingWorks() {
  const { ref } = useReference();
  const [tab, setTab] = useState<'test' | 'vacancies'>('test');
  const [specialization, setSpecialization] = useState('backend');
  const [level, setLevel] = useState<Level>('middle');

  return (
    <div className="pub-narrow">
      {/* Тёмный разворот: здесь объясняется главная механика продукта,
          и начинать её с обычного заголовка было бы слабо. */}
      <section className="ink bleed howto-hero">
        <div className="howto-hero-in">
          <p className="eyebrow">Механика тестирования</p>
          <h1 className="howto-h">Один план теста, у каждого свой набор заданий</h1>
          <div className="howto-cols">
            <p>
              Для каждой категории – своей связки специализации и грейда – задан план теста:
              сколько заданий какого типа и какой сложности в него входит. Задания берутся из
              банка, где у каждого измерены сложность и вес
            </p>
            <p>
              По плану тест собирается лично под кандидата. Наборы у двух человек одной категории
              почти не совпадают, но трудность и максимальный балл одинаковые – поэтому результаты
              сравнимы между собой
            </p>
          </div>
        </div>
      </section>

      <Tabs<'test' | 'vacancies'>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'test', label: 'Сборка теста' },
          { id: 'vacancies', label: 'Разбор вакансий' },
        ]}
      />

      <div style={{ marginTop: 'var(--sp-5)' }}>
        {tab === 'test' ? (
          <div className="stack">
            <Card>
              <div className="grid-2">
                <Field label="Специализация">
                  {(p) => (
                    <Select
                      {...p}
                      value={specialization}
                      onChange={(e) => setSpecialization(e.target.value)}
                    >
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
                    <Select {...p} value={level} onChange={(e) => setLevel(e.target.value as Level)}>
                      {ref?.levels.map((l) => (
                        <option key={l.slug} value={l.slug}>
                          {levelTitle(l.slug)}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              </div>
            </Card>

            <ProfileExplainer specialization={specialization} level={level} />
          </div>
        ) : (
          <DemoVacancies />
        )}
      </div>
    </div>
  );
}
