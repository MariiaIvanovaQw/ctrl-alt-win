import { api } from '../../api/client';
import { useAsync } from '../../lib/useAsync';
import { CabinetLayout } from '../../components/Layout';
import { Alert } from '../../components/ui';
import type { Company } from '../../api/types';

/**
 * Кабинет работодателя. Главное действие — «Подборка», а не «опубликовать
 * вакансию»: инициатива в продукте принадлежит работодателю.
 */
export default function EmployerCabinet() {
  const company = useAsync(() => api.get<Company>('/employer/company'), []);
  const onReview = company.data?.review_status === 'on_review';

  return (
    <CabinetLayout
      banner={
        onReview ? (
          <Alert tone="warn" title="Компания на проверке">
            После жалоб кандидатов приглашения и публикация вакансий временно недоступны. Модератор
            свяжется с вами
          </Alert>
        ) : null
      }
      groups={[
        {
          items: [
            { to: '/employer/selection', label: 'Подборка', end: true },
            { to: '/employer/categories', label: 'Категории' },
            { to: '/employer/search', label: 'Поиск по банку' },
          ],
        },
        {
          caption: 'Контакт',
          items: [
            { to: '/employer/invitations', label: 'Приглашения' },
            { to: '/employer/applications', label: 'Отклики' },
            { to: '/employer/tasks', label: 'Задания' },
          ],
        },
        {
          caption: 'Настройка',
          items: [
            { to: '/employer/needs', label: 'Потребности' },
            { to: '/employer/company', label: 'Компания' },
            { to: '/employer/webhooks', label: 'Интеграции' },
          ],
        },
      ]}
    />
  );
}
