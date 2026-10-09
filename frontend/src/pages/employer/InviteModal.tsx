import { useState } from 'react';
import { api } from '../../api/client';
import { useReference } from '../../api/ReferenceContext';
import { useAction } from '../../lib/useAsync';
import { money } from '../../lib/format';
import {
  Alert,
  Button,
  Checkbox,
  ErrorNote,
  Field,
  Input,
  Modal,
  Select,
  Textarea,
} from '../../components/ui';
import type { CandidateCard, Need } from '../../api/types';

/**
 * Приглашение конкретному кандидату — главное действие работодателя.
 *
 * Вакансия не обязательна: приглашение живёт само по себе. Если указать
 * потребность и подборку, кандидат увидит обоснование «почему вы».
 */
export default function InviteModal({
  candidate,
  need,
  selectionId,
  onClose,
  onSent,
}: {
  candidate: Pick<CandidateCard, 'candidate_id' | 'display_name' | 'salary_expectation' | 'minor'>;
  need?: Need | null;
  selectionId?: string | null;
  onClose: () => void;
  onSent: () => void;
}) {
  const { ref } = useReference();

  const [title, setTitle] = useState(need?.title ?? '');
  const [description, setDescription] = useState(need?.description ?? '');
  const [salaryFrom, setSalaryFrom] = useState(need ? String(need.salary_from) : '');
  const [salaryTo, setSalaryTo] = useState(need ? String(need.salary_to) : '');
  const [workFormat, setWorkFormat] = useState(need?.work_format ?? '');
  const [contact, setContact] = useState('');
  const [suitable, setSuitable] = useState(Boolean(need?.suitable_for_minors));
  const [sent, setSent] = useState(false);

  const send = useAction(async () => {
    await api.post('/employer/invitations', {
      candidate_id: candidate.candidate_id,
      need_id: need?.id ?? null,
      selection_id: selectionId ?? null,
      title,
      description,
      salary_from: Number(salaryFrom),
      salary_to: Number(salaryTo),
      work_format: workFormat || null,
      contact_method: contact,
      suitable_for_minors: suitable,
    });
    setSent(true);
    onSent();
  });

  const errs = send.error?.fieldErrors ?? {};
  // кандидату меньше 18 лет можно предложить только лёгкий труд с сокращённым временем
  const ready =
    title && description.length >= 20 && salaryFrom && salaryTo && contact && (!candidate.minor || suitable);

  // Предупреждаем заранее: ожидания выше вилки — частая причина отказа.
  const expectation = candidate.salary_expectation;
  const belowExpectation = expectation && Number(salaryTo) > 0 && Number(salaryTo) < expectation;

  if (sent) {
    return (
      <Modal
        title="Приглашение отправлено"
        onClose={onClose}
        footer={
          <Button variant="primary" onClick={onClose}>
            Готово
          </Button>
        }
      >
        <Alert tone="success">
          {candidate.display_name} увидит предложение с указанной вилкой. Контакты откроются вам
          после того, как кандидат примет приглашение
        </Alert>
      </Modal>
    );
  }

  return (
    <Modal
      title={`Пригласить: ${candidate.display_name}`}
      onClose={onClose}
      wide
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" busy={send.busy} disabled={!ready} onClick={() => void send.run()}>
            Отправить приглашение
          </Button>
        </>
      }
    >
      <div className="stack">
        <Field label="Название позиции" required error={errs.title}>
          {(p) => <Input {...p} value={title} onChange={(e) => setTitle(e.target.value)} />}
        </Field>

        <Field
          label="Предложение"
          required
          hint="Не короче 20 символов. Кандидат читает именно этот текст"
          error={errs.description}
        >
          {(p) => (
            <Textarea
              {...p}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Чем предстоит заниматься, что за команда, почему интересно…"
            />
          )}
        </Field>

        <div className="grid-2">
          <Field label="Зарплата от, ₽" required error={errs.salary_from}>
            {(p) => (
              <Input
                {...p}
                type="number"
                min="0"
                value={salaryFrom}
                onChange={(e) => setSalaryFrom(e.target.value)}
              />
            )}
          </Field>
          <Field label="Зарплата до, ₽" required error={errs.salary_to}>
            {(p) => (
              <Input
                {...p}
                type="number"
                min="0"
                value={salaryTo}
                onChange={(e) => setSalaryTo(e.target.value)}
              />
            )}
          </Field>
        </div>

        {belowExpectation && (
          <Alert tone="warn">
            Кандидат ожидает {money(expectation)} – это выше верхней границы вашей вилки. Приглашение
            отправить можно, но вероятность отказа выше
          </Alert>
        )}

        <div className="grid-2">
          <Field label="Формат работы" error={errs.work_format}>
            {(p) => (
              <Select {...p} value={workFormat} onChange={(e) => setWorkFormat(e.target.value)}>
                <option value="">Не указан</option>
                {ref?.work_formats.map((w) => (
                  <option key={w.slug} value={w.slug}>
                    {w.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field
            label="Способ связи"
            required
            hint="Как кандидату с вами связаться после принятия"
            error={errs.contact_method}
          >
            {(p) => (
              <Input
                {...p}
                value={contact}
                placeholder="Telegram @hr, почта hr@company.ru"
                onChange={(e) => setContact(e.target.value)}
              />
            )}
          </Field>
        </div>

        {candidate.minor && (
          <Alert tone="warn" title="Кандидату меньше 18 лет">
            Пригласить можно только на работу с лёгким трудом, сокращённым рабочим временем и без вредных
            условий. Согласие законного представителя кандидата уже получено
          </Alert>
        )}
        <Checkbox
          checked={suitable}
          onChange={setSuitable}
          label="Подходит для несовершеннолетних (15–17 лет): лёгкий труд, сокращённое время, без вредных и опасных условий"
        />

        {need && selectionId && (
          <Alert tone="info">
            Приглашение привязано к потребности «{need.title}» – кандидат увидит обоснование, почему
            подборка выбрала именно его
          </Alert>
        )}

        <ErrorNote error={send.error} />
      </div>
    </Modal>
  );
}
