/** Форматирование значений для показа: деньги, даты, доли, склонения. */

const RUB = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

/** `230000` → `230 000 ₽`. Деньги в API — целые рубли. */
export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  return `${RUB.format(value)} ₽`;
}

/** Вилка зарплаты. Обе границы обязательны по ТЗ, но подстрахуемся. */
export function salaryRange(from?: number | null, to?: number | null): string {
  if (from && to) return `${RUB.format(from)} – ${RUB.format(to)} ₽`;
  if (from) return `от ${money(from)}`;
  if (to) return `до ${money(to)}`;
  return 'не указана';
}

const DATE = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
const DATE_TIME = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

/** Время от бэкенда приходит в UTC, показываем в местном поясе. */
export function date(iso: string | null | undefined): string {
  if (!iso) return '–';
  return DATE.format(new Date(iso));
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '–';
  return DATE_TIME.format(new Date(iso));
}

/** «3 дня назад», «сегодня» — для отметок активности. */
export function ago(iso: string | null | undefined): string {
  if (!iso) return '–';
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return 'сегодня';
  if (days === 1) return 'вчера';
  if (days < 30) return `${days} ${plural(days, 'день', 'дня', 'дней')} назад`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} ${plural(months, 'месяц', 'месяца', 'месяцев')} назад`;
  return date(iso);
}

/** Доля `0.837` → `84%`. */
export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '–';
  return `${(value * 100).toFixed(digits)}%`;
}

/** Балл `68.1` → `68`. */
export function score(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  return String(Math.round(value));
}

export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

/** «5 кандидатов», «1 кандидат». */
export function count(n: number, one: string, few: string, many: string): string {
  return `${n} ${plural(n, one, few, many)}`;
}

/** Опыт `3.7` → `3,7 года`. */
export function years(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'не указан';
  const rounded = Math.round(value * 10) / 10;
  const whole = Math.round(rounded);
  return `${rounded.toLocaleString('ru-RU')} ${plural(whole, 'год', 'года', 'лет')}`;
}

/** Остаток времени попытки `MM:SS` или `H:MM:SS`. */
export function clock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}

const LEVEL_TITLES: Record<string, string> = {
  junior: 'Junior',
  middle: 'Middle',
  senior: 'Senior',
};

export function levelTitle(level: string | null | undefined): string {
  if (!level) return '–';
  return LEVEL_TITLES[level] ?? level;
}

/** Сколько дней осталось до даты: «3 дня», «истекло». */
export function daysLeft(iso: string | null | undefined): string {
  if (!iso) return '–';
  const days = Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
  if (days <= 0) return 'истекло';
  return count(days, 'день', 'дня', 'дней');
}

/**
 * Ответ на регулярное задание приходит объектом: `{text}`, `{option}` или
 * `{number}` — в зависимости от вида задачи. Сводим к строке для показа.
 */
export function taskAnswer(
  answer: { text?: string | null; option?: string | null; number?: number | string | null } | null | undefined,
): string {
  if (!answer) return '–';
  if (answer.text) return answer.text;
  if (answer.option) return `Вариант ${answer.option}`;
  if (answer.number !== null && answer.number !== undefined) return String(answer.number);
  return '–';
}
