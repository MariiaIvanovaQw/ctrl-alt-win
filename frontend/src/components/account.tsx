import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api, saveTokens } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useAction } from '../lib/useAsync';
import type { TokenPair } from '../api/types';
import { Alert, Button, Card, ErrorNote, Field, Input, Modal } from './ui';

/**
 * Учётная запись: смена пароля и удаление. Общие для кабинетов кандидата и
 * работодателя. Демо-учётной записи эти действия недоступны — ею
 * пользуются все посетители стенда.
 */

const DEMO_NOTE = 'Демо-учётная запись: сменить пароль и удалить её нельзя, ею пользуются все посетители стенда';

export function ChangePasswordCard() {
  const { me } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [done, setDone] = useState(false);

  const change = useAction(async () => {
    // остальные сессии завершаются, текущая получает новую пару токенов
    const pair = await api.post<TokenPair>('/auth/password/change', { current_password: current, new_password: next });
    saveTokens(pair);
    setCurrent('');
    setNext('');
    setRepeat('');
    setDone(true);
  });

  if (!me) return null;
  if (me.demo_account) {
    return (
      <Card title="Пароль">
        <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
          {DEMO_NOTE}
        </p>
      </Card>
    );
  }
  if (me.has_password === false) {
    return (
      <Card title="Пароль">
        <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
          Вы входите через ФСП ID, пароля у учётной записи нет. Задать его можно через{' '}
          <Link to="/forgot-password">восстановление пароля</Link> — ссылка придёт на {me.email}
        </p>
      </Card>
    );
  }

  const mismatch = repeat !== '' && repeat !== next;
  return (
    <Card title="Смена пароля" subtitle="После смены остальные сеансы входа завершатся">
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (!mismatch) void change.run();
        }}
      >
        {done && <Alert tone="success">Пароль изменён</Alert>}
        <Field label="Текущий пароль" required>
          {(p) => (
            <Input
              {...p}
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          )}
        </Field>
        <div className="grid-2">
          <Field label="Новый пароль" required hint="Не короче 8 символов, буква и цифра">
            {(p) => (
              <Input
                {...p}
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
            )}
          </Field>
          <Field label="Повторите новый пароль" required error={mismatch ? 'Пароли не совпадают' : undefined}>
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
        </div>
        <ErrorNote error={change.error} />
        <div>
          <Button type="submit" busy={change.busy} disabled={mismatch || !current || !next}>
            Сменить пароль
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function DeleteAccountCard({
  endpoint,
  subtitle,
  consequences,
}: {
  /** `/candidate/account` или `/employer/account`. */
  endpoint: string;
  subtitle: string;
  /** Что будет удалено — показывается в окне подтверждения. */
  consequences: string[];
}) {
  const { me, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');

  const remove = useAction(async () => {
    await api.del(endpoint);
    await logout();
  });

  if (!me) return null;
  if (me.demo_account) {
    return (
      <Card title="Удаление учётной записи">
        <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
          {DEMO_NOTE}
        </p>
      </Card>
    );
  }

  return (
    <>
      <Card title="Удаление учётной записи" subtitle={subtitle}>
        <Button variant="danger" onClick={() => setOpen(true)}>
          Удалить учётную запись
        </Button>
      </Card>

      {open && (
        <Modal
          title="Удалить учётную запись?"
          onClose={() => setOpen(false)}
          footer={
            <>
              <Button onClick={() => setOpen(false)}>Отмена</Button>
              <Button
                variant="danger"
                busy={remove.busy}
                disabled={confirmText !== 'УДАЛИТЬ'}
                onClick={() => void remove.run()}
              >
                Удалить навсегда
              </Button>
            </>
          }
        >
          <div className="stack">
            <Alert tone="danger" title="Действие необратимо">
              <ul className="stack-sm" style={{ marginTop: 'var(--sp-2)' }}>
                {consequences.map((line) => (
                  <li key={line}>– {line}</li>
                ))}
              </ul>
            </Alert>
            <Field label="Введите слово УДАЛИТЬ, чтобы подтвердить">
              {(p) => <Input {...p} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />}
            </Field>
            <ErrorNote error={remove.error} />
          </div>
        </Modal>
      )}
    </>
  );
}
