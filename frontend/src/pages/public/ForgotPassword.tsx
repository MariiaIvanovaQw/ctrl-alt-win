import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { useAction } from '../../lib/useAsync';
import { Alert, Button, Card, ErrorNote, Field, Input } from '../../components/ui';

/**
 * Восстановление пароля: письмо со ссылкой на /reset-password. Ответ API
 * одинаков для любого адреса — по нему нельзя узнать, кто зарегистрирован.
 */
export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);

  const submit = useAction(async () => {
    await api.anon.post('/auth/password/forgot', { email: email.trim() });
    setSent(true);
  });

  if (sent) {
    return (
      <div className="auth-card stack">
        <Alert tone="success" title="Проверьте почту">
          Если адрес {email.trim()} зарегистрирован, мы отправили на него ссылку для нового пароля. Ссылка
          действует час
        </Alert>
        <Link className="btn btn-ghost btn-block" to="/login">
          Перейти ко входу
        </Link>
      </div>
    );
  }

  return (
    <div className="auth-card">
      <Card title="Восстановление пароля" subtitle="Пришлём ссылку, по которой можно задать новый пароль">
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            void submit.run();
          }}
        >
          <Field label="Электронная почта" required error={submit.error?.fieldErrors.email}>
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
          {submit.error && !Object.keys(submit.error.fieldErrors).length && <ErrorNote error={submit.error} />}
          <Button type="submit" variant="primary" block busy={submit.busy}>
            Отправить ссылку
          </Button>
          <p className="muted" style={{ fontSize: 'var(--text-sm)', textAlign: 'center' }}>
            Вспомнили пароль? <Link to="/login">Войти</Link>
          </p>
        </form>
      </Card>
    </div>
  );
}
