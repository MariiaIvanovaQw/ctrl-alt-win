import { useState } from 'react';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction, useAsync } from '../../lib/useAsync';
import { useDraft } from '../../lib/useDraft';
import { date } from '../../lib/format';
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorNote,
  Field,
  Input,
  Loading,
  PageHeader,
  Select,
  Textarea,
} from '../../components/ui';
import type { Company } from '../../api/types';
import { ChangePasswordCard, DeleteAccountCard } from '../../components/account';

export default function CompanyPage() {
  const { ref } = useReference();
  const { data, loading, error, set } = useAsync(() => api.get<Company>('/employer/company'), []);
  const [form, setForm] = useDraft<Company, Company | null>(data, (c) => c, null);
  const [saved, setSaved] = useState(false);

  const save = useAction(async () => {
    if (!form) return;
    const updated = await api.put<Company>('/employer/company', {
      name: form.name,
      inn: form.inn || null,
      industry: form.industry || null,
      description: form.description || null,
      website: form.website || null,
      city: form.city || null,
      contact_email: form.contact_email || null,
      contact_phone: form.contact_phone || null,
    });
    set(updated);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  });

  const requestCheck = useAction(async () => {
    const updated = await api.post<Company>('/employer/company/verification');
    set(updated);
    setForm(updated);
  });

  if (loading) return <Loading rows={4} />;
  if (error) return <ErrorNote error={error} />;
  if (!form) return null;

  const set1 = <K extends keyof Company>(k: K, v: Company[K]) =>
    setForm((f) => (f ? { ...f, [k]: v } : f));
  const errs = save.error?.fieldErrors ?? {};

  return (
    <>
      <PageHeader
        title="Компания"
        subtitle="Эти данные видит кандидат в приглашении и в вакансии"
        actions={
          <Button variant="primary" busy={save.busy} onClick={() => void save.run()}>
            Сохранить
          </Button>
        }
      />

      <div className="stack">
        {saved && <Alert tone="success">Данные компании сохранены</Alert>}
        <ErrorNote error={save.error} />

        {data?.review_status === 'on_review' && (
          <Alert tone="warn" title="Компания на проверке">
            {data.review_reason ?? 'После жалоб кандидатов приглашения временно недоступны'}
          </Alert>
        )}
        {data?.review_status === 'blocked' && (
          <Alert tone="danger" title="Компания заблокирована">
            {data.review_reason ?? 'Обратитесь к модератору платформы'}
          </Alert>
        )}

        <Card title="Профиль">
          <div className="grid-2">
            <Field label="Название" required error={errs.name}>
              {(p) => (
                <Input {...p} value={form.name ?? ''} onChange={(e) => set1('name', e.target.value)} />
              )}
            </Field>
            <Field label="ИНН" hint="10 или 12 цифр" error={errs.inn}>
              {(p) => (
                <Input
                  {...p}
                  inputMode="numeric"
                  value={form.inn ?? ''}
                  onChange={(e) => set1('inn', e.target.value)}
                />
              )}
            </Field>
            <Field label="Направление деятельности" error={errs.industry}>
              {(p) => (
                <Select
                  {...p}
                  value={form.industry ?? ''}
                  onChange={(e) => set1('industry', e.target.value)}
                >
                  <option value="">Не выбрано</option>
                  {ref?.industries.map((i) => (
                    <option key={i.slug} value={i.slug}>
                      {i.title}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Город" error={errs.city}>
              {(p) => (
                <Input {...p} value={form.city ?? ''} onChange={(e) => set1('city', e.target.value)} />
              )}
            </Field>
            <Field label="Сайт" error={errs.website}>
              {(p) => (
                <Input
                  {...p}
                  placeholder="https://"
                  value={form.website ?? ''}
                  onChange={(e) => set1('website', e.target.value)}
                />
              )}
            </Field>
          </div>

          <div style={{ marginTop: 'var(--sp-4)' }}>
            <Field label="Чем занимается компания" error={errs.description}>
              {(p) => (
                <Textarea
                  {...p}
                  maxLength={5000}
                  value={form.description ?? ''}
                  onChange={(e) => set1('description', e.target.value)}
                />
              )}
            </Field>
          </div>
        </Card>

        <Card title="Контакты для кандидатов">
          <div className="grid-2">
            <Field label="Почта" error={errs.contact_email}>
              {(p) => (
                <Input
                  {...p}
                  type="email"
                  value={form.contact_email ?? ''}
                  onChange={(e) => set1('contact_email', e.target.value)}
                />
              )}
            </Field>
            <Field label="Телефон" error={errs.contact_phone}>
              {(p) => (
                <Input
                  {...p}
                  value={form.contact_phone ?? ''}
                  onChange={(e) => set1('contact_phone', e.target.value)}
                />
              )}
            </Field>
          </div>
        </Card>

        {data && (
          <Card title="Репутация" subtitle="Эти показатели видит кандидат рядом с приглашением">
            <div className="row-wrap">
              {data.verified ? (
                <Badge tone="success">Компания проверена</Badge>
              ) : (
                <Badge tone={data.verification_status === 'requested' ? 'accent' : 'neutral'}>
                  {data.verification_title ?? 'Не проверена'}
                </Badge>
              )}
              <Badge tone={data.complaints ? 'warn' : 'neutral'}>
                жалоб: {data.complaints ?? 0}
              </Badge>
              {data.created_at && (
                <span className="muted" style={{ fontSize: 'var(--text-sm)' }}>
                  на платформе с {date(data.created_at)}
                </span>
              )}
            </div>

            {!data.verified && (
              <div className="stack-sm" style={{ marginTop: 'var(--sp-4)' }}>
                <p className="muted" style={{ fontSize: 'var(--text-sm)' }}>
                  Проверка добровольная: модератор сверит ИНН и название с ЕГРЮЛ, и рядом с вашими
                  приглашениями появится метка «Компания проверена». Без неё всё работает как обычно.
                  Смена ИНН или названия снимает метку
                </p>
                {data.verification_comment && (
                  <Alert tone="warn">{data.verification_comment}</Alert>
                )}
                {data.verification_status !== 'requested' && (
                  <div>
                    <Button size="sm" busy={requestCheck.busy} onClick={() => void requestCheck.run()}>
                      Запросить проверку компании
                    </Button>
                  </div>
                )}
                <ErrorNote error={requestCheck.error} />
              </div>
            )}
          </Card>
        )}

        <div>
          <Button variant="primary" busy={save.busy} onClick={() => void save.run()}>
            Сохранить
          </Button>
        </div>

        <ChangePasswordCard />

        <DeleteAccountCard
          endpoint="/employer/account"
          subtitle="Право на удаление персональных данных (152-ФЗ) есть и у представителя работодателя"
          consequences={[
            'действующие приглашения будут отозваны, вакансии закрыты, регулярные задания отключены',
            'подписки ATS (вебхуки) удалятся',
            'реквизиты и контакты компании сотрутся; в истории кандидатов останется «Компания удалила учётную запись»',
            'ваши сообщения и копии писем на ваши адреса удалятся',
          ]}
        />
      </div>
    </>
  );
}
