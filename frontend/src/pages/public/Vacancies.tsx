import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAsync } from '../../lib/useAsync';
import { date, levelTitle } from '../../lib/format';
import { Salary, TrustPanel } from '../../components/domain';
import {
  Badge,
  Card,
  Chip,
  Empty,
  ErrorNote,
  Field,
  Input,
  Loading,
  PageHeader,
  Select,
} from '../../components/ui';
import type { Paged, Vacancy } from '../../api/types';

export function VacancyList() {
  const { ref } = useReference();
  const [text, setText] = useState('');
  const [specialization, setSpecialization] = useState('');
  const [level, setLevel] = useState('');
  const [salaryMin, setSalaryMin] = useState('');

  const { data, loading, error } = useAsync(
    () =>
      api.anon.get<Paged<Vacancy>>('/vacancies', {
        text: text || undefined,
        specialization: specialization || undefined,
        level: level || undefined,
        salary_min: salaryMin || undefined,
      }),
    [text, specialization, level, salaryMin],
  );

  return (
    <>
      <PageHeader
        title="Открытые вакансии"
        subtitle="Вилка зарплаты указана в каждой вакансии. Откликнуться можно самостоятельно, не дожидаясь приглашения"
      />

      <Card className="stack">
        <div className="grid-3">
          <Field label="Поиск по тексту">
            {(p) => (
              <Input
                {...p}
                value={text}
                placeholder="Python, платежи…"
                onChange={(e) => setText(e.target.value)}
              />
            )}
          </Field>
          <Field label="Специализация">
            {(p) => (
              <Select {...p} value={specialization} onChange={(e) => setSpecialization(e.target.value)}>
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
              <Select {...p} value={level} onChange={(e) => setLevel(e.target.value)}>
                <option value="">Любой</option>
                {ref?.levels.map((l) => (
                  <option key={l.slug} value={l.slug}>
                    {levelTitle(l.slug)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
        <Field label="Зарплата от, ₽">
          {(p) => (
            <Input
              {...p}
              type="number"
              inputMode="numeric"
              value={salaryMin}
              placeholder="150000"
              onChange={(e) => setSalaryMin(e.target.value)}
            />
          )}
        </Field>
      </Card>

      <div style={{ marginTop: 'var(--sp-5)' }}>
        <ErrorNote error={error} />
        {loading && <Loading rows={3} />}
        {data && !data.items.length && (
          <Empty title="Ничего не найдено">Попробуйте ослабить фильтры</Empty>
        )}
        <div className="stack">
          {data?.items.map((v) => (
            <Link
              key={v.id}
              to={`/vacancies/${v.id}`}
              style={{ color: 'inherit', textDecoration: 'none' }}
            >
              <article className="card card-interactive">
                <div className="row-top" style={{ justifyContent: 'space-between' }}>
                  <div className="stack-sm" style={{ minWidth: 0 }}>
                    <h3>{v.title}</h3>
                    <div className="row-wrap muted" style={{ fontSize: 'var(--text-sm)' }}>
                      <span>{v.company.name}</span>
                      <span>·</span>
                      <span>{v.city ?? 'город не указан'}</span>
                      {v.work_format_title && (
                        <>
                          <span>·</span>
                          <span>{v.work_format_title}</span>
                        </>
                      )}
                    </div>
                  </div>
                  <Salary from={v.salary_from} to={v.salary_to} size="md" />
                </div>

                <div className="row-wrap" style={{ marginTop: 'var(--sp-3)' }}>
                  <Badge tone="accent">
                    {v.specialization_title} · {levelTitle(v.level)}
                  </Badge>
                  {v.suitable_for_minors && <Badge tone="neutral">Подходит для 15–17 лет</Badge>}
                  {v.stack.slice(0, 6).map((s) => (
                    <Chip key={s.slug}>{s.title}</Chip>
                  ))}
                </div>
              </article>
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}

export function VacancyDetail() {
  const { id } = useParams<{ id: string }>();
  const { data, loading, error } = useAsync(() => api.anon.get<Vacancy>(`/vacancies/${id}`), [id]);

  if (loading) return <Loading rows={4} />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  return (
    <div className="pub-narrow stack">
      <Link to="/vacancies" className="muted" style={{ fontSize: 'var(--text-sm)' }}>
        ← Все вакансии
      </Link>

      <Card>
        <div className="row-top" style={{ justifyContent: 'space-between' }}>
          <div className="stack-sm">
            <h1 className="page-title">{data.title}</h1>
            <div className="row-wrap muted">
              <span>{data.company.name}</span>
              <span>·</span>
              <span>{data.city ?? 'город не указан'}</span>
              {data.work_format_title && (
                <>
                  <span>·</span>
                  <span>{data.work_format_title}</span>
                </>
              )}
              {data.published_at && (
                <>
                  <span>·</span>
                  <span>опубликована {date(data.published_at)}</span>
                </>
              )}
            </div>
          </div>
          <Salary
            from={data.salary_from}
            to={data.salary_to}
            size="lg"
            warnings={data.salary_warnings}
          />
        </div>
      </Card>

      <Card title="Категория и стек">
        <div className="row-wrap">
          <Badge tone="accent">
            {data.specialization_title} · {levelTitle(data.level)}
          </Badge>
          {data.suitable_for_minors && <Badge tone="neutral">Подходит для 15–17 лет</Badge>}
          {data.stack.map((s) => (
            <Chip key={s.slug}>{s.title}</Chip>
          ))}
        </div>
      </Card>

      <Card title="Задача">
        <p style={{ whiteSpace: 'pre-line' }}>{data.description}</p>
      </Card>

      {data.team_description && (
        <Card title="Команда">
          <p style={{ whiteSpace: 'pre-line' }}>{data.team_description}</p>
        </Card>
      )}

      {data.company_trust && (
        <Card title="О компании">
          <TrustPanel trust={data.company_trust} />
        </Card>
      )}

      <Card>
        <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
          Чтобы откликнуться, <Link to="/login">войдите</Link> как кандидат. С подтверждённой
          категорией работодатели находят вас сами и присылают предложения с указанной вилкой
        </p>
      </Card>
    </div>
  );
}
