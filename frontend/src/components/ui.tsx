import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react';
import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { ApiError } from '../api/client';
import { cx } from '../lib/cx';

// ------------------------------------------------------------------ кнопка

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'ink';
  size?: 'sm' | 'md' | 'lg';
  block?: boolean;
  busy?: boolean;
};

export function Button({
  variant = 'secondary',
  size = 'md',
  block,
  busy,
  disabled,
  children,
  className,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      className={cx(
        'btn',
        `btn-${variant}`,
        size !== 'md' && `btn-${size}`,
        block && 'btn-block',
        className,
      )}
      disabled={disabled || busy}
      {...rest}
    >
      {busy && <span className="spinner" aria-hidden />}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------- поля

type FieldProps = {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  children: (props: { id: string; 'aria-invalid'?: boolean; 'aria-describedby'?: string }) => ReactNode;
};

/** Обёртка поля: подпись, подсказка и сообщение об ошибке с нужными aria. */
export function Field({ label, hint, error, required, children }: FieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined;

  return (
    <div className="field">
      {label && (
        <label className="field-label" htmlFor={id}>
          {label}
          {required && (
            <span className="req" aria-hidden>
              {' '}
              *
            </span>
          )}
        </label>
      )}
      {children({ id, 'aria-invalid': error ? true : undefined, 'aria-describedby': describedBy })}
      {hint && !error && (
        <span className="field-hint" id={`${id}-hint`}>
          {hint}
        </span>
      )}
      {error && (
        <span className="field-error" id={`${id}-err`} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx('input', props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx('textarea', props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx('select', props.className)} />;
}

export function Checkbox({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="check">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

// ----------------------------------------------------------------- карточка

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  flush,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={cx('card', flush && 'card-flush', className)}>
      {(title || actions) && (
        <header className="card-hd">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <div className="card-sub">{subtitle}</div>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

// ------------------------------------------------------------- бейдж и чип

export function Badge({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'solid';
  children: ReactNode;
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Chip({
  children,
  active,
  onClick,
  onRemove,
  title,
}: {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
  onRemove?: () => void;
  title?: string;
}) {
  const content = (
    <>
      {children}
      {onRemove && (
        <span
          className="chip-x"
          role="button"
          tabIndex={-1}
          aria-hidden
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        >
          ×
        </span>
      )}
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        title={title}
        aria-pressed={active}
        className={cx('chip', 'chip-btn', active && 'chip-on')}
        onClick={onClick}
      >
        {content}
      </button>
    );
  }
  return (
    <span className={cx('chip', active && 'chip-on')} title={title}>
      {content}
    </span>
  );
}

/** Множественный выбор чипами: стек, роли, софт-скиллы, форматы работы. */
export function ChipSelect({
  options,
  value,
  onChange,
  emptyHint,
}: {
  options: { slug: string; title: string }[];
  value: string[];
  onChange: (next: string[]) => void;
  emptyHint?: string;
}) {
  if (!options.length) return <span className="muted">{emptyHint ?? 'Справочник загружается…'}</span>;

  return (
    <div className="row-wrap">
      {options.map((o) => {
        const on = value.includes(o.slug);
        return (
          <Chip
            key={o.slug}
            active={on}
            onClick={() => onChange(on ? value.filter((v) => v !== o.slug) : [...value, o.slug])}
          >
            {o.title}
          </Chip>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- сообщения

export function Alert({
  tone = 'info',
  title,
  children,
}: {
  tone?: 'info' | 'success' | 'warn' | 'danger' | 'neutral';
  title?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className={`alert alert-${tone}`} role={tone === 'danger' ? 'alert' : undefined}>
      <div>
        {title && <div className="alert-title">{title}</div>}
        {children}
      </div>
    </div>
  );
}

/** Показ ошибки API: текст уже на русском, выдумывать свой не нужно. */
export function ErrorNote({ error }: { error: ApiError | undefined | null }) {
  if (!error) return null;
  return <Alert tone="danger">{error.message}</Alert>;
}

// -------------------------------------------------------------- состояния

export function Loading({ rows = 3, label = 'Загрузка' }: { rows?: number; label?: string }) {
  return (
    <div className="stack" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ height: i === 0 ? 28 : 68 }} />
      ))}
    </div>
  );
}

export function Empty({
  title,
  children,
  action,
}: {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children && <p>{children}</p>}
      {action && <div style={{ marginTop: 'var(--sp-4)' }}>{action}</div>}
    </div>
  );
}

// ------------------------------------------------------------------- шкалы

export function Meter({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div
      className="meter"
      role="meter"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div className="meter-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

// ------------------------------------------------------------ модальное окно

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const boxRef = useRef<HTMLDivElement>(null);

  // Esc закрывает, фокус уходит внутрь окна, фон не прокручивается.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    boxRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={cx('modal', wide && 'modal-wide')}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        tabIndex={-1}
        ref={boxRef}
      >
        <header className="modal-hd">
          <h2 className="card-title">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Закрыть">
            ✕
          </Button>
        </header>
        {children}
        {footer && <footer className="modal-ft">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

// ------------------------------------------------------------------ вкладки

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: ReactNode }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={t.id === value}
          className={cx('tab', t.id === value && 'tab-on')}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------ шапка страницы

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  /** Короткая надстрочная метка: задаёт раздел, не утяжеляя заголовок. */
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-hd">
      <div style={{ minWidth: 0 }}>
        {eyebrow && <p className="eyebrow page-eyebrow">{eyebrow}</p>}
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-sub">{subtitle}</p>}
      </div>
      {actions && <div className="row-wrap">{actions}</div>}
    </header>
  );
}
