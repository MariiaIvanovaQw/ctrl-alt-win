/** Склейка CSS-классов: ложные значения пропускаются. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}
