import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { CabinetLayout } from '../../components/Layout';
import type { Invitation } from '../../api/types';

/** Боковое меню кабинета кандидата. Счётчик — новые приглашения. */
export default function CandidateCabinet() {
  const invitations = useAsync(() => api.get<Invitation[]>('/candidate/invitations'), []);
  const unread = invitations.data?.filter((i) => i.status === 'sent').length ?? 0;

  return (
    <CabinetLayout
      groups={[
        {
          items: [
            { to: '/candidate', label: 'Обзор', end: true },
            { to: '/candidate/invitations', label: 'Приглашения', badge: unread || null },
          ],
        },
        {
          caption: 'Профиль',
          items: [
            { to: '/candidate/profile', label: 'Анкета и резюме' },
            { to: '/candidate/assessment', label: 'Категория и тест' },
            { to: '/candidate/fsp', label: 'ФСП ID' },
          ],
        },
        {
          caption: 'Работа',
          items: [
            { to: '/candidate/vacancies', label: 'Вакансии' },
            { to: '/candidate/applications', label: 'Мои отклики' },
            { to: '/candidate/tasks', label: 'Задания' },
          ],
        },
        {
          caption: 'Аккаунт',
          items: [{ to: '/candidate/settings', label: 'Приватность и данные' }],
        },
      ]}
    />
  );
}
