import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useAction } from '../../lib/useAsync';
import { Alert, Button, Card, ErrorNote, Field, Input } from '../../components/ui';

/**
 * Новый пароль по ссылке из письма (`/reset-password?token=…`). Переход по
 * ссылке подтверждает почту; все прежние сессии пользователя завершаются.
 */
export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token') ?? '';
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');

  const submit = useAction(async () => {
    await api.anon.post('/auth/password/reset', { token, password });
    navigate('/login?reset=1', { replace: true });
  });

  if (!token) {
    return (
      <div className="auth-card">
        <Alert tone="warn" title="Нет ссылки">
          Откройте страницу по ссылке из письма или <Link to="/forgot-password">запросите новую</Link>
        </Alert>
      </div>
    );
  }

  const mismatch = repeat !== '' && repeat !== password;
  const expired = submit.error?.code === 'invalid_reset_token';

  return (
    <div className="auth-card">
      <Card title="Новый пароль">
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            if (!mismatch) void submit.run();
          }}
        >
          <Field label="Новый пароль" required hint="Не короче 8 символов, хотя бы одна буква и одна цифра">
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
          <Field label="Повторите пароль" required error={mismatch ? 'Пароли не совпадают' : undefined}>
            {(p) => (
              <Input
                {...p}
                type="password"
                autoComplete="new-password"
                required
                value={repeat}
                onChange={(e) => setRepeat(e.target.value)}
              />
            )}
          </Field>
          {expired ? (
            <Alert tone="warn" title="Ссылка устарела">
              Она одноразовая и действует час. <Link to="/forgot-password">Запросите новую</Link>
            </Alert>
          ) : (
            <ErrorNote error={submit.error} />
          )}
          <Button type="submit" variant="primary" block busy={submit.busy} disabled={mismatch || !password}>
            Сохранить пароль
          </Button>
        </form>
      </Card>
    </div>
  );
}
