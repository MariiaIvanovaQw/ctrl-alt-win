import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api, clearTokens, getTokens, onTokensChange, saveTokens } from '../api/client';
import type { Me, TokenPair } from '../api/types';

type AuthValue = {
  me: Me | null;
  /** true, пока проверяем сохранённую сессию при старте приложения. */
  booting: boolean;
  login: (email: string, password: string) => Promise<Me>;
  /** Вход по уже полученной паре токенов — после входа через ФСП ID. */
  loginWithTokens: (pair: TokenPair) => Promise<Me>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  // Пока проверяется сохранённая сессия, экраны ждут; без токенов проверять нечего.
  const [booting, setBooting] = useState(() => Boolean(getTokens()));

  const loadMe = useCallback(async () => {
    if (!getTokens()) {
      setMe(null);
      return;
    }
    try {
      setMe(await api.get<Me>('/auth/me'));
    } catch {
      // Токен недействителен — выходим молча, пользователь увидит форму входа.
      clearTokens();
      setMe(null);
    }
  }, []);

  // Восстановление сессии при загрузке страницы: синхронизация с хранилищем
  // токенов, состояние меняется только после ответа API.
  useEffect(() => {
    if (!getTokens()) return;
    // oxlint-disable-next-line react/set-state-in-effect
    void loadMe().finally(() => setBooting(false));
  }, [loadMe]);

  // Вход или выход в соседней вкладке должен отражаться и здесь.
  useEffect(
    () =>
      onTokensChange((tokens) => {
        if (!tokens) setMe(null);
        else void loadMe();
      }),
    [loadMe],
  );

  const login = useCallback(async (email: string, password: string) => {
    const pair = await api.anon.post<TokenPair>('/auth/login', { email, password });
    saveTokens(pair);
    const profile = await api.get<Me>('/auth/me');
    setMe(profile);
    return profile;
  }, []);

  const loginWithTokens = useCallback(async (pair: TokenPair) => {
    saveTokens(pair);
    const profile = await api.get<Me>('/auth/me');
    setMe(profile);
    return profile;
  }, []);

  const logout = useCallback(async () => {
    const refresh = getTokens()?.refresh_token;
    // Сервер гасит refresh-токен; даже если запрос не прошёл, локально выходим.
    if (refresh) await api.post('/auth/logout', { refresh_token: refresh }).catch(() => undefined);
    clearTokens();
    setMe(null);
  }, []);

  const value = useMemo<AuthValue>(
    () => ({ me, booting, login, loginWithTokens, logout, refreshMe: loadMe }),
    [me, booting, login, loginWithTokens, logout, loadMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth вызван вне AuthProvider');
  return ctx;
}
