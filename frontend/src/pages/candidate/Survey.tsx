import { useState } from 'react';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction, useAsync } from '../../lib/useAsync';
import { levelTitle } from '../../lib/format';
import {
  Alert,
  Button,
  Card,
  ChipSelect,
  ErrorNote,
  Field,
  Input,
  Select,
  Textarea,
} from '../../components/ui';
import type { CandidateProfile, Level } from '../../api/types';

/**
 * Опрос перед тестом: отрасль, специализация и предполагаемый грейд.
 *
 * «Отрасль» в ТЗ — IT-направление (бэкенд, фронтенд, тестирование), по нему
 * собирается тест и строится категория. «Специализация» уточняет профиль
 * внутри направления (Python, React, автоматизация…). Предметная область
 * (финтех, госсектор…) необязательна и на тест не влияет.
 */
/** Верхняя граница даты рождения в форме (дата загрузки страницы). */
const TODAY = new Date().toISOString().slice(0, 10);

export default function Survey({ onDone }: { onDone: () => void }) {
  const { ref, skillsFor } = useReference();

  const [industry, setIndustry] = useState('');
  const [specialization, setSpecialization] = useState('');
  const [track, setTrack] = useState('');
  const [selfLevel, setSelfLevel] = useState<Level | ''>('');
  const [experience, setExperience] = useState('');
  const [stack, setStack] = useState<string[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [formats, setFormats] = useState<string[]>([]);
  const [goals, setGoals] = useState('');
  // дата рождения обязательна, если её ещё нет в профиле: от неё зависят правила для 14–17 лет
  const profile = useAsync(() => api.get<CandidateProfile>('/candidate/profile'), []);
  // пока кандидат не ввёл своё значение, в поле — дата из профиля
  const [typedBirthDate, setBirthDate] = useState<string | null>(null);
  const birthDate = typedBirthDate ?? profile.data?.birth_date ?? '';
  const birthRequired = !profile.data?.birth_date;

  const submit = useAction(async () => {
    await api.post('/candidate/survey', {
      industry: industry || null,
      specialization,
      track: track || null,
      self_level: selfLevel,
      experience_years: experience === '' ? null : Number(experience),
      stack,
      roles,
      work_formats: formats,
      goals: goals || null,
      birth_date: birthDate || null,
    });
    onDone();
  });

  const ready = specialization && track && selfLevel && (!birthRequired || birthDate);
  const tracks = (specialization && ref?.tracks?.[specialization]) || [];
  const planned = ref?.directions?.filter((d) => !d.available) ?? [];
  const errs = submit.error?.fieldErrors ?? {};

  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        void submit.run();
      }}
    >
      <Alert tone="info" title="Зачем этот опрос">
        По специализации и заявленному грейду соберётся персональный тест. Если тест не подтвердит
        уровень, грейд не понизится принудительно – решение останется за вами
      </Alert>

      <Card title="Направление">
        <div className="grid-3">
          <Field
            label="Отрасль (IT-направление)"
            required
            hint="По направлению собирается тест и строится категория"
            error={errs.specialization}
          >
            {(p) => (
              <Select
                {...p}
                value={specialization}
                onChange={(e) => {
                  setSpecialization(e.target.value);
                  setTrack('');
                  setStack([]);
                }}
                required
              >
                <option value="">Выберите…</option>
                {ref?.specializations.map((s) => (
                  <option key={s.slug} value={s.slug}>
                    {s.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Field label="Специализация" required hint="Основной язык или профиль работы" error={errs.track}>
            {(p) => (
              <Select
                {...p}
                value={track}
                onChange={(e) => setTrack(e.target.value)}
                required
                disabled={!specialization}
              >
                <option value="">{specialization ? 'Выберите…' : 'Сначала выберите направление'}</option>
                {tracks.map((t) => (
                  <option key={t.slug} value={t.slug}>
                    {t.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Field
            label="Предполагаемый грейд"
            required
            hint="Тест будет на этот уровень"
            error={errs.self_level}
          >
            {(p) => (
              <Select
                {...p}
                value={selfLevel}
                onChange={(e) => setSelfLevel(e.target.value as Level)}
                required
              >
                <option value="">Выберите…</option>
                {ref?.levels.map((l) => (
                  <option key={l.slug} value={l.slug}>
                    {l.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>

        {planned.length > 0 && (
          <p className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 'var(--sp-3)' }}>
            Скоро: {planned.map((d) => d.title).join(', ')}
          </p>
        )}

        <div className="grid-3" style={{ marginTop: 'var(--sp-4)' }}>
          <Field label="Предметная область" hint="Необязательно, на тест не влияет" error={errs.industry}>
            {(p) => (
              <Select {...p} value={industry} onChange={(e) => setIndustry(e.target.value)}>
                <option value="">Не важно</option>
                {ref?.industries.map((i) => (
                  <option key={i.slug} value={i.slug}>
                    {i.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>

        <div className="grid-3" style={{ marginTop: 'var(--sp-4)' }}>
          <Field label="Опыт, лет" error={errs.experience_years}>
            {(p) => (
              <Input
                {...p}
                type="number"
                step="0.5"
                min="0"
                max="60"
                value={experience}
                onChange={(e) => setExperience(e.target.value)}
              />
            )}
          </Field>
          <Field
            label="Дата рождения"
            required={birthRequired}
            hint="Нужна для правил для кандидатов до 18 лет; работодатель видит только отметку «до 18 лет»"
            error={
              errs.birth_date ?? (submit.error?.code === 'birth_date_required' ? submit.error.message : undefined)
            }
          >
            {(p) => (
              <Input
                {...p}
                type="date"
                required={birthRequired}
                max={TODAY}
                value={birthDate}
                onChange={(e) => setBirthDate(e.target.value)}
              />
            )}
          </Field>
        </div>
      </Card>

      <Card title="Стек" subtitle="С какими технологиями работали">
        <ChipSelect
          options={skillsFor(specialization)}
          value={stack}
          onChange={setStack}
          emptyHint="Сначала выберите специализацию"
        />
      </Card>

      <Card title="Роль в команде">
        <ChipSelect options={ref?.team_roles ?? []} value={roles} onChange={setRoles} />
      </Card>

      <Card title="Формат работы">
        <ChipSelect options={ref?.work_formats ?? []} value={formats} onChange={setFormats} />
      </Card>

      <Card title="Что ищете" subtitle="Необязательно. Поможет работодателю понять ваши ожидания">
        <Field label="">
          {(p) => (
            <Textarea
              {...p}
              maxLength={1000}
              value={goals}
              placeholder="Хочу продуктовые задачи и сильную команду…"
              onChange={(e) => setGoals(e.target.value)}
            />
          )}
        </Field>
      </Card>

      <ErrorNote error={submit.error} />

      <div className="row">
        <Button type="submit" variant="primary" size="lg" busy={submit.busy} disabled={!ready}>
          Сохранить и перейти к тесту
        </Button>
        {selfLevel && (
          <span className="muted">
            Тест будет на уровень {levelTitle(selfLevel)}
          </span>
        )}
      </div>
    </form>
  );
}
