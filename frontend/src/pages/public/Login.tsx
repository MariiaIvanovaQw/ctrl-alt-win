import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { homeFor } from '../../lib/links';
import { useAction, useAsync } from '../../lib/useAsync';
import { Alert, Button, Card, Checkbox, ErrorNote, Field, Input } from '../../components/ui';

type DemoAccounts = {
  password: string | null;
  candidates: { email: string; note: string }[];
  employers: { email: string; company: string }[];
  /** Пароль модератора по сети не отдаётся: он в data/demo_accounts.json на сервере. */
  moderator?: { email: string; note: string } | null;
  jury?: { email: string; note: string }[];
};

/** Почему не получился вход через ФСП ID — по коду ошибки с бэкенда. */
const FSP_ERRORS: Record<string, string> = {
  consent_required:
    'Это первый вход через ФСП ID: отметьте согласия ниже, чтобы мы создали профиль кандидата',
  email_domain_not_allowed: 'Вход доступен только с почтой в домене .ru',
  fsp_id_taken: 'К профилю с этой почтой уже привязан другой ФСП ID',
  fsp_login_candidates_only: 'Вход через ФСП ID доступен соискателям. Работодатели входят по почте',
  fsp_email_missing: 'ФСП ID не передал подтверждённый адрес почты',
  fsp_state_invalid: 'Сеанс входа устарел. Попробуйте ещё раз',
};

/**
 * Вход через ФСП ID — единую точку входа на ресурсы Федерации. При первом
 * входе создаётся профиль кандидата, и ФСП ID сразу привязывается: нужны
 * согласия на обработку данных и на получение сведений из реестра ФСП.
 */
function FspLoginCard() {
  const [consentPd, setConsentPd] = useState(false);
  const [consentFsp, setConsentFsp] = useState(false);
  const start = useAction(async () => {
    const { authorization_url } = await api.anon.post<{ authorization_url: string }>('/auth/fsp/start', {
      consent_pd_processing: consentPd,
      consent_fsp_data: consentFsp,
      redirect_after: '/candidate',
    });
    window.location.assign(authorization_url);
  });

  return (
    <Card
      title="Участник ФСП?"
      subtitle="Войдите через ФСП ID – профиль и подтверждённые достижения подтянутся сами"
    >
      <div className="stack-sm" id="fsp">
        <Checkbox
          checked={consentPd}
          onChange={setConsentPd}
          label={
            <>
              Согласен на обработку персональных данных (
              <Link to="/consent" target="_blank">
                условия
              </Link>
              ) – нужно при первом входе
            </>
          }
        />
        <Checkbox
          checked={consentFsp}
          onChange={setConsentFsp}
          label="Согласен на получение сведений о моих достижениях из реестра ФСП"
        />
        <ErrorNote error={start.error} />
        <Button variant="primary" block busy={start.busy} onClick={() => void start.run()}>
          Войти через ФСП ID
        </Button>
      </div>
    </Card>
  );
}

/**
 * Демо-учётные записи. Эндпоинт доступен только при APP_ENV=dev, поэтому
 * блок просто не показывается на боевом стенде.
 */
function DemoAccountsPanel({ onPick }: { onPick: (email: string, password: string) => void }) {
  const { data } = useAsync(() => api.anon.get<DemoAccounts>('/dev/demo-accounts'), []);
  if (!data) return null;

  const shared = data.password ?? '';
  const rows = [
    ...(data.candidates ?? []).map((c) => ({ email: c.email, note: c.note, kind: 'Кандидат', password: shared })),
    ...(data.employers ?? []).map((e) => ({ email: e.email, note: e.company, kind: 'Работодатель', password: shared })),
    ...(data.jury ?? []).map((j) => ({ email: j.email, note: j.note, kind: 'Жюри', password: shared })),
    // у модератора свой пароль: подставляем только адрес
    ...(data.moderator?.email
      ? [{ email: data.moderator.email, note: data.moderator.note, kind: 'Модератор', password: '' }]
      : []),
  ];
  if (!rows.length) return null;

  return (
    <Card title="Демо-доступы" subtitle={`Общий пароль – ${shared}. Нажмите, чтобы подставить`}>
      <div className="stack-sm">
        {rows.map((r) => (
          <button
            key={r.email}
            type="button"
            className="side-link"
            style={{ textAlign: 'left', border: '1px solid var(--border)', cursor: 'pointer' }}
            onClick={() => onPick(r.email, r.password)}
          >
            <span>
              <span className="mono" style={{ fontSize: 'var(--text-xs)' }}>
                {r.email}
              </span>
              <br />
              <span className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                {r.note}
              </span>
            </span>
            <span className="side-count">{r.kind}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

export default function Login() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { login } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const submit = useAction(async () => {
    const me = await login(email.trim(), password);
    navigate(homeFor(me.role), { replace: true });
  });

  return (
    <div className="auth-card stack">
      {params.get('verified') === '1' && (
        <Alert tone="success" title="Адрес подтверждён">
          Теперь можно войти
        </Alert>
      )}
      {params.get('reset') === '1' && (
        <Alert tone="success" title="Пароль изменён">
          Войдите с новым паролем
        </Alert>
      )}
      {params.get('fsp') === 'error' && (
        <Alert tone="warn" title="Не удалось войти через ФСП ID">
          {FSP_ERRORS[params.get('reason') ?? ''] ?? 'Попробуйте ещё раз'}
        </Alert>
      )}
      {params.get('fsp') === 'cancelled' && <Alert tone="info">Вход через ФСП ID отменён</Alert>}

      <Card title="Вход">
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            void submit.run();
          }}
        >
          <Field label="Электронная почта" error={submit.error?.fieldErrors.email}>
            {(p) => (
              <Input
                {...p}
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            )}
          </Field>

          <Field label="Пароль" error={submit.error?.fieldErrors.password}>
            {(p) => (
              <Input
                {...p}
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            )}
          </Field>

          {submit.error && !Object.keys(submit.error.fieldErrors).length && (
            <ErrorNote error={submit.error} />
          )}
          {submit.error?.status === 429 && typeof submit.error.details?.retry_after_seconds === 'number' && (
            <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
              Повторите через {Math.ceil(submit.error.details.retry_after_seconds / 60)} мин.
            </p>
          )}

          <Button type="submit" variant="primary" block busy={submit.busy}>
            Войти
          </Button>

          <p className="muted" style={{ fontSize: 'var(--text-sm)', textAlign: 'center' }}>
            <Link to="/forgot-password">Забыли пароль?</Link>
          </p>
          <p className="muted" style={{ fontSize: 'var(--text-sm)', textAlign: 'center' }}>
            Нет аккаунта? <Link to="/register">Зарегистрироваться</Link>
          </p>
        </form>
      </Card>

      <FspLoginCard />

      <DemoAccountsPanel
        onPick={(e, p) => {
          setEmail(e);
          setPassword(p);
        }}
      />
    </div>
  );
}
