import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { homeFor } from '../../lib/links';
import { Alert, Loading } from '../../components/ui';
import type { TokenPair } from '../../api/types';

/**
 * Возврат после входа через ФСП ID: одноразовый код из адреса меняется на
 * токены. Код живёт две минуты и срабатывает один раз, поэтому обмен
 * запускается ровно один раз даже при повторном рендере.
 */
export default function FspLoginCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { loginWithTokens } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const code = params.get('code');

  useEffect(() => {
    if (started.current || !code) return;
    started.current = true;
    api.anon
      .post<TokenPair>('/auth/fsp/exchange', { code })
      .then(loginWithTokens)
      .then((me) => {
        const next = params.get('next');
        // только путь этого сайта: «//host» браузер понял бы как другой сайт
        const safe = next && /^\/(?![/\\])/.test(next);
        navigate(safe ? next : homeFor(me.role), { replace: true });
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Нет связи с сервером'));
  }, [code, params, navigate, loginWithTokens]);

  const problem = code ? error : 'В адресе нет кода входа';
  if (problem) {
    return (
      <div className="auth-card stack">
        <Alert tone="warn" title="Не удалось войти через ФСП ID">
          {problem} <Link to="/login">Попробовать снова</Link>
        </Alert>
      </div>
    );
  }
  return (
    <div className="auth-card">
      <Loading rows={2} label="Входим через ФСП ID" />
    </div>
  );
}
