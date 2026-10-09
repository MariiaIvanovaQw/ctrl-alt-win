import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { levelTitle, salaryRange } from '../../lib/format';
import HeroArt from '../../components/HeroArt';
import type { Paged, Reference, Vacancy } from '../../api/types';

type Health = { status: string; bank_version: string; bank_items: number };

const STEPS = [
  {
    n: 'Шаг 01',
    title: 'Опрос и тест',
    text: 'Выберите IT-направление, специализацию и грейд, на который претендуете. Тест из 26 заданий собирается персонально: у каждого кандидата свой набор одинаковой трудности',
  },
  {
    n: 'Шаг 02',
    title: 'Категория в профиле',
    text: 'По результату вы получаете специализацию и подтверждённый грейд, а вместе с ними – оценку по каждой компетенции. Это и видит работодатель',
  },
  {
    n: 'Шаг 03',
    title: 'Приглашения с зарплатой',
    text: 'Компании находят вашу категорию и присылают предложения с указанной вилкой. Контакты открываются после того, как вы приняли приглашение',
  },
];

const FOR_CANDIDATE = [
  'Категория и грейд, подтверждённые заданиями',
  'Оценка по каждой компетенции с указанием достоверности',
  'Достижения соревнований подтягиваются из реестра ФСП',
  'Зарплата до вычета НДФЛ известна до начала общения',
  'Вопросы компании – в переписке на платформе, контакты остаются скрытыми',
  'Контакты открываются только по вашему решению',
];

const FOR_EMPLOYER = [
  'Подборка по описанию задачи, а не по совпадению ключевых слов',
  'У каждого кандидата видно, из чего сложился балл соответствия',
  'Фильтры по специализации, грейду, стеку и достижениям ФСП',
  'Приглашение напрямую, без публикации вакансии',
  'Выгрузка кандидата в ATS и подписка на события',
];

export default function Home() {
  const health = useAsync(() => api.anon.get<Health>('/health'), []);
  const reference = useAsync(() => api.anon.get<Reference>('/reference'), []);
  const vacancies = useAsync(() => api.anon.get<Paged<Vacancy>>('/vacancies'), []);

  const categories = reference.data
    ? reference.data.specializations.length * reference.data.levels.length
    : null;

  return (
    <>
      {/* ---------- обложка ---------- */}
      <section className="ink bleed hero">
        <div className="hero-in">
          <div className="hero-copy">
            <p className="eyebrow">Федерация спортивного программирования</p>

            <h1 className="hero-h">
              ИТ-таланты
              <br />
              с подтверждёнными
              <br />
              <span className="hero-h-accent">достижениями</span>
            </h1>

            <p className="hero-sub">
              Платформа для подбора ИТ-специалистов с объективной оценкой навыков и данными о
              реальных достижениях от Федерации спортивного программирования
            </p>

            <div className="hero-cta">
              <Link className="btn btn-primary btn-lg btn-arrow" to="/register?role=candidate">
                Я ищу работу
                <span className="btn-arrow-i" aria-hidden>
                  <svg viewBox="0 0 16 16" fill="none">
                    <path
                      d="M3 8h9m0 0-3.5-3.5M12 8l-3.5 3.5"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
              </Link>
              <Link className="btn btn-secondary btn-lg" to="/register?role=employer">
                Я ищу специалистов
              </Link>
            </div>
          </div>

          <HeroArt />
        </div>

        {/* Цифры приходят из API, а не вписаны в вёрстку. */}
        <div className="hero-facts-wrap">
          <dl className="hero-facts">
            <div className="hero-fact">
              <span className="hero-fact-i" aria-hidden>
                <svg viewBox="0 0 20 20" fill="none">
                  <path
                    d="M3 16V9m5 7V4m5 12v-5m5 5V7"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
              </span>
              <div>
                <dt className="hero-fact-n">{health.data?.bank_items ?? '–'}</dt>
                <dd className="hero-fact-l">заданий в банке</dd>
              </div>
            </div>

            <div className="hero-fact">
              <span className="hero-fact-i" aria-hidden>
                <svg viewBox="0 0 20 20" fill="none">
                  <rect x="2.5" y="2.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
                  <rect x="11.5" y="2.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
                  <rect x="2.5" y="11.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
                  <rect x="11.5" y="11.5" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
                </svg>
              </span>
              <div>
                <dt className="hero-fact-n">{categories ?? '–'}</dt>
                <dd className="hero-fact-l">категорий специалистов</dd>
              </div>
            </div>

            <div className="hero-fact">
              <span className="hero-fact-i" aria-hidden>
                <svg viewBox="0 0 20 20" fill="none">
                  <circle cx="10" cy="10.5" r="7" stroke="currentColor" strokeWidth="1.8" />
                  <path d="M10 6.5v4l2.5 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
              </span>
              <div>
                <dt className="hero-fact-n">26 / 60</dt>
                <dd className="hero-fact-l">заданий в тесте и минут на него</dd>
              </div>
            </div>

            <div className="hero-fact">
              <span className="hero-fact-i" aria-hidden>
                <svg viewBox="0 0 20 20" fill="none">
                  <path
                    d="M10 2.5 16.5 5v5c0 3.6-2.6 6.4-6.5 7.5C6.1 16.4 3.5 13.6 3.5 10V5L10 2.5Z"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <div>
                <dt className="hero-fact-n">Реестр ФСП</dt>
                <dd className="hero-fact-l">источник данных о достижениях</dd>
              </div>
            </div>

            <div className="hero-fact">
              <span className="hero-fact-i" aria-hidden>
                <svg viewBox="0 0 20 20" fill="none">
                  <rect x="2.5" y="5.5" width="15" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" />
                  <path d="M7 5.5V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1.5" stroke="currentColor" strokeWidth="1.8" />
                </svg>
              </span>
              <div>
                <dt className="hero-fact-n">{vacancies.data ? vacancies.data.total : '–'}</dt>
                <dd className="hero-fact-l">открытых вакансий</dd>
              </div>
            </div>
          </dl>
        </div>
      </section>

      {/* ---------- путь кандидата ---------- */}
      <section className="section">
        <p className="eyebrow">Как это работает</p>
        <h2 className="section-title">Три шага до первого приглашения</h2>

        <div className="how">
          <ol className="track">
            {STEPS.map((s) => (
              <li className="track-step" key={s.n}>
                <div className="track-n">{s.n}</div>
                <h3 className="track-h">{s.title}</h3>
                <p className="track-p">{s.text}</p>
              </li>
            ))}
          </ol>

          <aside className="how-aside">
            <div className="card how-demo">
              <p className="eyebrow" style={{ marginBottom: 'var(--sp-4)' }}>
                Карточка в подборке
              </p>
              <div className="how-row">
                <span className="how-rank">1</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="how-name">Соколова М</div>
                  <div className="how-meta">Бэкенд-разработка · Middle · Москва</div>
                  <div className="contrib" style={{ marginTop: 'var(--sp-3)' }}>
                    <div className="contrib-seg" style={{ width: '43%', background: 'var(--violet-500)' }} />
                    <div className="contrib-seg" style={{ width: '29%', background: 'var(--violet-300)' }} />
                    <div className="contrib-seg" style={{ width: '13%', background: 'var(--brand-ink)' }} />
                    <div className="contrib-seg" style={{ width: '5%', background: 'var(--brand-red)' }} />
                    <div className="contrib-seg" style={{ width: '10%', background: 'var(--brand-gray)' }} />
                  </div>
                  <div className="how-why">
                    Базы данных 93% · SQL 92% · призёр региональных соревнований ФСП
                  </div>
                </div>
                <div className="how-score">
                  <span className="figure figure-sm figure-accent">68</span>
                  <span className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                    из 100
                  </span>
                </div>
              </div>
              <p className="how-note">
                Балл складывается из компетенций под задачу, результата теста, стека, достижений
                ФСП и свежести профиля. <Link to="/how-testing-works">Как формируется тест</Link>
              </p>
            </div>
          </aside>
        </div>
      </section>

      {/* ---------- что даёт платформа каждой стороне ---------- */}
      <section className="section">
        <p className="eyebrow">Возможности</p>
        <div className="sides">
          <article className="side-col">
            <h3 className="side-h">Кандидату</h3>
            <ul className="side-list">
              {FOR_CANDIDATE.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
            <Link className="btn btn-secondary" to="/register?role=candidate">
              Создать профиль
            </Link>
          </article>

          <article className="side-col">
            <h3 className="side-h">Работодателю</h3>
            <ul className="side-list">
              {FOR_EMPLOYER.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
            <Link className="btn btn-secondary" to="/register?role=employer">
              Описать потребность
            </Link>
          </article>
        </div>
      </section>

      {/* ---------- живые вакансии ---------- */}
      {!!vacancies.data?.items.length && (
        <section className="section">
          <div className="vac-head">
            <div>
              <p className="eyebrow">Открытые вакансии</p>
              <h2 className="section-title">Можно откликнуться самому</h2>
            </div>
            <Link className="btn btn-secondary btn-sm" to="/vacancies">
              Все вакансии
            </Link>
          </div>

          <div className="vac-grid">
            {vacancies.data.items.slice(0, 3).map((v) => (
              <Link key={v.id} to={`/vacancies/${v.id}`} className="vac-card card card-interactive">
                <div className="vac-salary">{salaryRange(v.salary_from, v.salary_to)}</div>
                <h3 className="vac-title">{v.title}</h3>
                <div className="vac-meta">
                  {v.company.name} · {v.city ?? 'город не указан'}
                  {v.work_format_title ? ` · ${v.work_format_title}` : ''}
                </div>
                <div className="row-wrap" style={{ marginTop: 'var(--sp-4)' }}>
                  <span className="badge badge-accent">
                    {v.specialization_title} · {levelTitle(v.level)}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* ---------- профиль участника ФСП ---------- */}
      <section className="ink bleed geo">
        <div className="geo-in">
          <div>
            <p className="eyebrow">Профиль участника ФСП</p>
            <h2 className="section-title">Соревновательный опыт – часть профиля</h2>
            <p className="section-lede">
              Войдите через ФСП ID или привяжите его к профилю – в карточке появятся подтверждённые
              реестром результаты и спортивный разряд. При ранжировании внутри категории учитываются
              число соревнований и результативность: победы и призовые места весят больше участия
            </p>
            <div className="geo-figures">
              <div>
                <div className="figure figure-sm figure-accent">
                  {reference.data?.specializations.length ?? '–'}
                </div>
                <div className="figure-label">направления подготовки</div>
              </div>
              <div>
                <div className="figure figure-sm figure-accent">
                  {health.data?.bank_version ? `v${health.data.bank_version}` : '–'}
                </div>
                <div className="figure-label">версия банка заданий</div>
              </div>
            </div>
          </div>
          <img className="art-map geo-map" src="/brand/map1.png" alt="" aria-hidden />
        </div>
      </section>

      {/* ---------- призыв ---------- */}
      <section className="section cta">
        <div>
          <h2 className="section-title">Начните с теста</h2>
          <p className="section-lede">
            {reference.data
              ? `Доступные направления: ${reference.data.specializations
                  .map((s) => s.title.toLowerCase())
                  .join(', ')}`
              : 'Выберите направление и подтвердите грейд'}
          </p>
        </div>
        <div className="row-wrap">
          <Link className="btn btn-primary btn-lg" to="/register?role=candidate">
            Создать профиль
          </Link>
          <Link className="btn btn-secondary btn-lg" to="/vacancies">
            Смотреть вакансии
          </Link>
        </div>
      </section>
    </>
  );
}
