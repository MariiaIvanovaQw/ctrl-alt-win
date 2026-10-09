import type { ReactNode } from 'react';
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { homeFor } from '../lib/links';
import type { Role } from '../api/types';
import HeroArt from './HeroArt';
import { Button, Loading } from './ui';
import { cx } from '../lib/cx';

/** Логотип ФСП в версии для светлого фона плюс название продукта. */
export function BrandMark({ to = '/' }: { to?: string }) {
  return (
    <Link className="hdr-logo" to={to} aria-label="ФСП Талант – на главную">
      <img src="/brand/logo_01.svg" alt="Федерация спортивного программирования" />
      <span className="hdr-product">Талант</span>
    </Link>
  );
}

function navClass({ isActive }: { isActive: boolean }) {
  return cx('hdr-link', isActive && 'hdr-link-on');
}

function Header({ children }: { children?: ReactNode }) {
  const { me, logout } = useAuth();

  return (
    <header className="hdr">
      <div className="hdr-in">
        <BrandMark to={me ? homeFor(me.role) : '/'} />
        {children}
        <div className="spacer" />
        {me ? (
          <div className="row">
            <span className="muted mono hdr-user" style={{ fontSize: 'var(--text-xs)' }}>
              {me.email}
            </span>
            <Button size="sm" variant="ink" onClick={() => void logout()}>
              Выйти
            </Button>
          </div>
        ) : (
          <div className="row" style={{ gap: 'var(--sp-2)' }}>
            <Link className="hdr-link" to="/login">
              Войти
            </Link>
            <Link className="btn btn-primary btn-sm" to="/register">
              Регистрация
            </Link>
          </div>
        )}
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="ftr">
      <div className="ftr-in">
        <span>Платформа подбора ИТ-специалистов ФСП</span>
        <span>·</span>
        <Link to="/how-testing-works">Как формируется тест</Link>
        <span>·</span>
        <Link to="/vacancies">Вакансии</Link>
        <div className="spacer" />
        <span className="faint">Демонстрационные данные: компании и кандидаты вымышлены</span>
      </div>
    </footer>
  );
}

/** Публичные страницы: шапка с навигацией, контент, подвал. */
export function PublicLayout() {
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        К содержимому
      </a>
      <Header>
        <nav className="hdr-nav">
          <NavLink to="/vacancies" className={navClass}>
            Вакансии
          </NavLink>
          <NavLink to="/how-testing-works" className={navClass}>
            Как формируется тест
          </NavLink>
        </nav>
      </Header>
      <main id="main" className="pub">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}

/** Вход и регистрация: фирменный разворот слева, форма справа. */
export function AuthLayout() {
  return (
    <div className="app">
      <Header />
      <div className="auth-wrap">
        <aside className="auth-side" aria-hidden>
          <p className="eyebrow">Платформа подбора ФСП</p>
          <div className="auth-side-in">
            <div className="auth-copy">
              <p className="auth-claim">
                Квалификация, <em>подтверждённая заданиями</em>
              </p>
              <p className="auth-note">
                Один тест вместо десятков собеседований вслепую. Работодатели видят категорию,
                подтверждённую на заданиях, и приходят сами – с указанной зарплатой
              </p>
            </div>
            <div className="auth-art">
              <HeroArt />
            </div>
          </div>
        </aside>
        <main id="main" className="auth-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

/**
 * Сосредоточенный режим: шапка без навигации и широкое поле.
 * Используется на экране теста, чтобы не уводить кандидата со страницы,
 * пока идёт время попытки.
 */
export function FocusLayout() {
  return (
    <div className="app">
      <header className="hdr">
        <div className="hdr-in">
          <div className="hdr-logo">
            <img src="/brand/logo_01.svg" alt="ФСП" />
            <span className="hdr-product">Тестирование</span>
          </div>
        </div>
      </header>
      <main id="main" className="pub pub-narrow">
        <Outlet />
      </main>
    </div>
  );
}

export type SideItem = { to: string; label: string; end?: boolean; badge?: ReactNode };
export type SideGroup = { caption?: string; items: SideItem[] };

/** Кабинет: боковое меню слева, содержимое справа. */
export function CabinetLayout({ groups, banner }: { groups: SideGroup[]; banner?: ReactNode }) {
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        К содержимому
      </a>
      <Header />
      <div className="cab">
        <nav className="side rail" aria-label="Разделы кабинета">
          {groups.map((g, i) => (
            <div className="side-group" key={g.caption ?? i}>
              {g.caption && <div className="side-cap">{g.caption}</div>}
              {g.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => cx('side-link', isActive && 'side-link-on')}
                >
                  <span>{item.label}</span>
                  {item.badge !== undefined && item.badge !== null && (
                    <span className="side-count">{item.badge}</span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <main id="main" className="main">
          {banner && <div style={{ marginBottom: 'var(--sp-5)' }}>{banner}</div>}
          <Outlet />
        </main>
      </div>
      <Footer />
    </div>
  );
}

/**
 * Защита маршрутов по роли. Пока проверяем сохранённую сессию, показываем
 * заглушку: иначе на обновлении страницы кабинет мигает формой входа.
 */
export function RequireRole({ role }: { role: Role }) {
  const { me, booting } = useAuth();
  const location = useLocation();

  if (booting) {
    return (
      <div className="pub">
        <Loading rows={4} label="Проверяем сессию" />
      </div>
    );
  }
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (me.role !== role) return <Navigate to={homeFor(me.role)} replace />;
  return <Outlet />;
}
