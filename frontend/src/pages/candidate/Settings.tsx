import { useState } from 'react';
import { api, saveJson } from '../../api/client';
import { useAction, useAsync } from '../../lib/useAsync';
import { useDraft } from '../../lib/useDraft';
import { dateTime } from '../../lib/format';
import { ChangePasswordCard, DeleteAccountCard } from '../../components/account';
import { Alert, Button, Card, Checkbox, ErrorNote, Loading, PageHeader } from '../../components/ui';
import type { Consent, Privacy } from '../../api/types';

const PRIVACY_LABEL: Record<keyof Privacy, string> = {
  show_full_name: 'Показывать ФИО (иначе работодатель видит фамилию и инициал)',
  show_city: 'Показывать город',
  show_about: 'Показывать блок «О себе»',
  show_fsp: 'Показывать достижения ФСП (скрытые не видны работодателю и не дают бонуса в подборке)',
  show_experience: 'Показывать опыт в годах',
};

export default function Settings() {
  const privacy = useAsync(() => api.get<Privacy>('/candidate/privacy'), []);
  const consents = useAsync(() => api.get<Consent[]>('/candidate/consents'), []);

  const [form, setForm] = useDraft<Privacy, Privacy | null>(privacy.data, (p) => p, null);
  const [saved, setSaved] = useState(false);

  const savePrivacy = useAction(async (next: Privacy) => {
    const updated = await api.put<Privacy>('/candidate/privacy', next);
    setForm(updated);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  });

  const setConsent = useAction(async (kind: string, granted: boolean) => {
    await api.post('/candidate/consents', { kind, granted });
    consents.reload();
  });

  const exportData = useAction(async () => {
    const data = await api.get<unknown>('/candidate/data-export');
    saveJson(data, 'my-data.json');
  });

  if (privacy.loading) return <Loading rows={4} />;
  if (privacy.error) return <ErrorNote error={privacy.error} />;
  if (!form) return null;

  return (
    <>
      <PageHeader
        title="Приватность и данные"
        subtitle="Вы управляете тем, что видит работодатель. Контакты в любом случае закрыты до принятия приглашения"
      />

      <div className="stack">
        {saved && <Alert tone="success">Настройки сохранены</Alert>}

        <Card
          title="Согласия"
          subtitle="Без согласия на показ профиля вы не попадаете в подборки работодателей"
        >
          {consents.loading && <Loading rows={1} />}
          <ErrorNote error={setConsent.error} />
          <div className="stack">
            {consents.data?.map((c) => (
              <div key={c.kind} className="row-top" style={{ justifyContent: 'space-between' }}>
                <Checkbox
                  checked={c.granted}
                  onChange={(v) => void setConsent.run(c.kind, v)}
                  label={
                    <>
                      {c.title}
                      {c.updated_at && (
                        <div className="faint" style={{ fontSize: 'var(--text-xs)' }}>
                          обновлено {dateTime(c.updated_at)}
                          {c.version ? ` · редакция ${c.version}` : ''}
                        </div>
                      )}
                    </>
                  }
                />
              </div>
            ))}
          </div>
        </Card>

        <Card title="Что видит работодатель" subtitle="Категория, грейд и компетенции показываются всегда – они подтверждены тестом">
          <ErrorNote error={savePrivacy.error} />
          <div className="stack">
            {(Object.keys(PRIVACY_LABEL) as (keyof Privacy)[]).map((key) => (
              <Checkbox
                key={key}
                checked={form[key]}
                label={PRIVACY_LABEL[key]}
                onChange={(v) => {
                  const next = { ...form, [key]: v };
                  setForm(next);
                  void savePrivacy.run(next);
                }}
              />
            ))}
          </div>
        </Card>

        <Card
          title="Выгрузка данных"
          subtitle="Все данные профиля, попыток и взаимодействий одним файлом JSON (152-ФЗ)"
        >
          <ErrorNote error={exportData.error} />
          <Button busy={exportData.busy} onClick={() => void exportData.run()}>
            Скачать мои данные
          </Button>
        </Card>

        <ChangePasswordCard />

        <DeleteAccountCard
          endpoint="/candidate/account"
          subtitle="Профиль перестанет показываться работодателям, персональные данные будут удалены"
          consequences={[
            'анкета, контакты, дата рождения и резюме',
            'достижения ФСП, ваши сообщения и согласие представителя',
            'копии писем на ваш адрес в базе платформы, тексты сопроводительных писем и ответов на задания',
            'в подборках работодателей вы больше не покажетесь',
            'результаты тестов остаются без привязки к вам — для статистики качества заданий',
          ]}
        />
      </div>
    </>
  );
}
