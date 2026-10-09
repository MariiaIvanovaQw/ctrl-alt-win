import { Suspense, lazy } from 'react';
import type { ComponentType } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthLayout, FocusLayout, PublicLayout, RequireRole } from './components/Layout';
import { Empty, Loading } from './components/ui';

/**
 * Экраны подгружаются по требованию.
 *
 * Кабинеты кандидата и работодателя почти не пересекаются, и грузить оба
 * сразу незачем: посетитель публичной страницы получает только её код.
 * Для именованных экспортов нужен переходник к `default` — этого требует
 * `React.lazy`.
 */
function page<M extends Record<string, unknown>>(load: () => Promise<M>, name: keyof M & string) {
  return lazy(() => load().then((m) => ({ default: m[name] as ComponentType })));
}

// ---- публичная часть
const Home = lazy(() => import('./pages/public/Home'));
const Login = lazy(() => import('./pages/public/Login'));
const Register = lazy(() => import('./pages/public/Register'));
const FspLoginCallback = lazy(() => import('./pages/public/FspLoginCallback'));
const ForgotPassword = lazy(() => import('./pages/public/ForgotPassword'));
const ResetPassword = lazy(() => import('./pages/public/ResetPassword'));
const Consent = lazy(() => import('./pages/public/Consent'));
const GuardianConsent = lazy(() => import('./pages/public/GuardianConsent'));
const HowTestingWorks = lazy(() => import('./pages/public/HowTestingWorks'));
const VacancyList = page(() => import('./pages/public/Vacancies'), 'VacancyList');
const VacancyDetail = page(() => import('./pages/public/Vacancies'), 'VacancyDetail');

// ---- кабинет кандидата
const CandidateCabinet = lazy(() => import('./pages/candidate/CandidateCabinet'));
const CandidateOverview = lazy(() => import('./pages/candidate/Overview'));
const CandidateProfile = lazy(() => import('./pages/candidate/Profile'));
const Assessment = lazy(() => import('./pages/candidate/Assessment'));
const AttemptPage = lazy(() => import('./pages/candidate/Attempt'));
const CandidateTasks = lazy(() => import('./pages/candidate/Tasks'));
const Fsp = lazy(() => import('./pages/candidate/Fsp'));
const Settings = lazy(() => import('./pages/candidate/Settings'));
const InvitationList = page(() => import('./pages/candidate/Invitations'), 'InvitationList');
const InvitationDetail = page(() => import('./pages/candidate/Invitations'), 'InvitationDetail');
const CandidateVacancies = page(() => import('./pages/candidate/Vacancies'), 'CandidateVacancies');
const CandidateApplications = page(
  () => import('./pages/candidate/Vacancies'),
  'CandidateApplications',
);

// ---- кабинет работодателя
const EmployerCabinet = lazy(() => import('./pages/employer/EmployerCabinet'));
const SelectionPage = lazy(() => import('./pages/employer/Selection'));
const Categories = lazy(() => import('./pages/employer/Categories'));
const Search = lazy(() => import('./pages/employer/Search'));
const CandidateCardPage = lazy(() => import('./pages/employer/CandidateCardPage'));
const CompanyPage = lazy(() => import('./pages/employer/CompanyPage'));
const EmployerApplications = lazy(() => import('./pages/employer/Applications'));
const EmployerTasks = lazy(() => import('./pages/employer/Tasks'));
const Webhooks = lazy(() => import('./pages/employer/Webhooks'));
const NeedList = page(() => import('./pages/employer/Needs'), 'NeedList');
const NeedForm = page(() => import('./pages/employer/Needs'), 'NeedForm');
const EmployerInvitationList = page(
  () => import('./pages/employer/Invitations'),
  'EmployerInvitationList',
);
const EmployerInvitationDetail = page(
  () => import('./pages/employer/Invitations'),
  'EmployerInvitationDetail',
);

// ---- модерация
const AdminCompanies = lazy(() => import('./pages/admin/Companies'));
const AdminCabinet = page(() => import('./pages/admin/Companies'), 'AdminCabinet');

function NotFound() {
  return (
    <Empty title="Страница не найдена">
      Проверьте адрес или вернитесь на <a href="/">главную</a>
    </Empty>
  );
}

export default function App() {
  return (
    <Suspense
      fallback={
        <div className="pub">
          <Loading rows={3} label="Загрузка страницы" />
        </div>
      }
    >
      <Routes>
        {/* ---- публичная часть */}
        <Route element={<PublicLayout />}>
          <Route index element={<Home />} />
          <Route path="/vacancies" element={<VacancyList />} />
          <Route path="/vacancies/:id" element={<VacancyDetail />} />
          <Route path="/how-testing-works" element={<HowTestingWorks />} />
          <Route path="/consent" element={<Consent />} />
          <Route path="/guardian-consent" element={<GuardianConsent />} />
          <Route path="*" element={<NotFound />} />
        </Route>

        <Route element={<AuthLayout />}>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/login/fsp" element={<FspLoginCallback />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
        </Route>

        {/* ---- кабинет кандидата */}
        <Route element={<RequireRole role="candidate" />}>
          {/* Экран теста — вне кабинета, чтобы не уводить с попытки. */}
          <Route element={<FocusLayout />}>
            <Route path="/candidate/assessment/attempt/:id" element={<AttemptPage />} />
          </Route>

          <Route element={<CandidateCabinet />}>
            <Route path="/candidate" element={<CandidateOverview />} />
            <Route path="/candidate/profile" element={<CandidateProfile />} />
            <Route path="/candidate/assessment" element={<Assessment />} />
            <Route path="/candidate/invitations" element={<InvitationList />} />
            <Route path="/candidate/invitations/:id" element={<InvitationDetail />} />
            <Route path="/candidate/vacancies" element={<CandidateVacancies />} />
            <Route path="/candidate/applications" element={<CandidateApplications />} />
            <Route path="/candidate/tasks" element={<CandidateTasks />} />
            <Route path="/candidate/fsp" element={<Fsp />} />
            <Route path="/candidate/settings" element={<Settings />} />
          </Route>
        </Route>

        {/* ---- кабинет работодателя */}
        <Route element={<RequireRole role="employer" />}>
          <Route element={<EmployerCabinet />}>
            <Route path="/employer" element={<Navigate to="/employer/selection" replace />} />
            <Route path="/employer/selection" element={<SelectionPage />} />
            <Route path="/employer/categories" element={<Categories />} />
            <Route path="/employer/search" element={<Search />} />
            <Route path="/employer/needs" element={<NeedList />} />
            <Route path="/employer/needs/new" element={<NeedForm />} />
            <Route path="/employer/needs/:id" element={<NeedForm />} />
            <Route path="/employer/candidates/:id" element={<CandidateCardPage />} />
            <Route path="/employer/invitations" element={<EmployerInvitationList />} />
            <Route path="/employer/invitations/:id" element={<EmployerInvitationDetail />} />
            <Route path="/employer/applications" element={<EmployerApplications />} />
            <Route path="/employer/tasks" element={<EmployerTasks />} />
            <Route path="/employer/webhooks" element={<Webhooks />} />
            <Route path="/employer/company" element={<CompanyPage />} />
          </Route>
        </Route>

        {/* ---- модерация */}
        <Route element={<RequireRole role="admin" />}>
          <Route element={<AdminCabinet />}>
            <Route path="/admin" element={<Navigate to="/admin/companies" replace />} />
            <Route path="/admin/companies" element={<AdminCompanies />} />
          </Route>
        </Route>

        <Route path="/home" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
