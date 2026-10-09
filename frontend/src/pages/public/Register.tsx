import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useAction } from '../../lib/useAsync';
import { Alert, Button, Card, Checkbox, ErrorNote, Field, Input, Select } from '../../components/ui';
import type { RegisterResult, Role } from '../../api/types';

/**
 * Ссылка подтверждения на демо-стенде. В демо-режиме API возвращает её в
 * ответе регистрации (`dev_verification_link`): подтверждение почты на
 * демонстрации не обязательно. Вне демо-режима поле пустое — письмо приходит
 * только на почту.
 */
function DemoVerification({ link }: { link: string }) {
  return (
    <Card title="Письмо подтверждения (демо-стенд)" subtitle="Ссылка из письма продублирована здесь">
      <a className="btn btn-primary btn-block" href={link}>
        Подтвердить адрес
      </a>
    </Card>
  );
}

/** Регистрация только на почте в российском домене .ru (152-ФЗ, локализация данных). */
function isRuEmail(value: string): boolean {
  return /^[^@\s]+@[^@\s]+\.ru$/i.test(value.trim());
}

export default function Register() {
  const [params] = useSearchParams();
  const initialRole = params.get('role') === 'employer' ? 'employer' : 'candidate';

  const [role, setRole] = useState<Role>(initialRole);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [consent, setConsent] = useState(false);
  const [sent, setSent] = useState(false);
  const [demoLink, setDemoLink] = useState<string | null>(null);

  const submit = useAction(async () => {
    const res = await api.anon.post<RegisterResult>('/auth/register', {
      email: email.trim(),
      password,
      role,
      consent_pd_processing: consent,
    });
    setDemoLink(res.dev_verification_link ?? null);
    setSent(true);
  });

  const resend = useAction(async () => {
    const res = await api.anon.post<RegisterResult>('/auth/resend-verification', { email: email.trim() });
    if (res.dev_verification_link) setDemoLink(res.dev_verification_link);
  });

  if (sent) {
    return (
      <div className="auth-card stack">
        <Alert tone="success" title="Проверьте почту">
          Мы отправили ссылку для подтверждения на {email}. После подтверждения можно войти
        </Alert>
        {demoLink && <DemoVerification link={demoLink} />}
        <Card>
          <div className="stack-sm">
            <ErrorNote error={resend.error} />
            <Button block onClick={() => void resend.run()} busy={resend.busy}>
              Отправить письмо ещё раз
            </Button>
            <Link className="btn btn-ghost btn-block" to="/login">
              Перейти ко входу
            </Link>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="auth-card">
      <Card title="Регистрация">
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            void submit.run();
          }}
        >
          <Field label="Я регистрируюсь как" required>
            {(p) => (
              <Select {...p} value={role} onChange={(e) => setRole(e.target.value as Role)}>
                <option value="candidate">Кандидат – ищу работу</option>
                <option value="employer">Работодатель – нанимаю</option>
              </Select>
            )}
          </Field>

          <Field
            label="Электронная почта"
            required
            hint="Только почта в домене .ru, например name@mail.ru или name@company.ru"
            error={
              submit.error?.fieldErrors.email ??
              (email.includes('@') && email.includes('.') && !isRuEmail(email)
                ? 'Регистрация доступна только с почтой в домене .ru'
                : undefined)
            }
          >
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

          <Field
            label="Пароль"
            required
            hint="Не короче 8 символов, хотя бы одна буква и одна цифра"
            error={submit.error?.fieldErrors.password}
          >
            {(p) => (
              <Input
                {...p}
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            )}
          </Field>

          <Checkbox
            checked={consent}
            onChange={setConsent}
            label={
              <>
                Согласен на обработку персональных данных в соответствии с{' '}
                <Link to="/consent" target="_blank">
                  условиями обработки
                </Link>{' '}
                (152-ФЗ)
              </>
            }
          />

          {submit.error && !Object.keys(submit.error.fieldErrors).length && (
            <ErrorNote error={submit.error} />
          )}

          <Button
            type="submit"
            variant="primary"
            block
            busy={submit.busy}
            disabled={!consent || !isRuEmail(email)}
          >
            Зарегистрироваться
          </Button>

          {role === 'candidate' && (
            <p className="muted" style={{ fontSize: 'var(--text-sm)', textAlign: 'center' }}>
              Участник ФСП? <Link to="/login#fsp">Войти через ФСП ID</Link> – профиль и достижения
              подтянутся сами
            </p>
          )}

          <p className="muted" style={{ fontSize: 'var(--text-sm)', textAlign: 'center' }}>
            Уже есть аккаунт? <Link to="/login">Войти</Link>
          </p>
        </form>
      </Card>
    </div>
  );
}
