import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from './client';
import type { Reference, Ref, SkillRef } from './types';

/**
 * Справочники (специализации, грейды, навыки, причины отказа) берём с
 * бэкенда один раз на сессию и держим в контексте: ТЗ прямо запрещает
 * хардкодить их во фронтенде.
 */

type ReferenceValue = {
  ref: Reference | null;
  /** Название по слагу с запасным вариантом — сам слаг. */
  title: (kind: keyof Reference, slug: string | null | undefined) => string;
  skills: SkillRef[];
  /** Навыки, относящиеся к специализации (для подсказок в формах). */
  skillsFor: (specialization: string | null | undefined) => SkillRef[];
};

const ReferenceContext = createContext<ReferenceValue | null>(null);

const EMPTY: Ref[] = [];

export function ReferenceProvider({ children }: { children: ReactNode }) {
  const [ref, setRef] = useState<Reference | null>(null);

  useEffect(() => {
    let alive = true;
    api.anon
      .get<Reference>('/reference')
      .then((r) => {
        if (alive) setRef(r);
      })
      .catch(() => {
        // Справочник недоступен — экраны покажут слаги вместо названий.
      });
    return () => {
      alive = false;
    };
  }, []);

  const value = useMemo<ReferenceValue>(() => {
    const lists = ref as unknown as Record<string, Ref[]> | null;

    return {
      ref,
      title: (kind, slug) => {
        if (!slug) return '–';
        const list = lists?.[kind as string] ?? EMPTY;
        return list.find((x) => x.slug === slug)?.title ?? slug;
      },
      skills: ref?.skills ?? [],
      skillsFor: (specialization) => {
        const all = ref?.skills ?? [];
        if (!specialization) return all;
        const scoped = all.filter((s) => s.specializations?.includes(specialization));
        return scoped.length ? scoped : all;
      },
    };
  }, [ref]);

  return <ReferenceContext.Provider value={value}>{children}</ReferenceContext.Provider>;
}

export function useReference(): ReferenceValue {
  const ctx = useContext(ReferenceContext);
  if (!ctx) throw new Error('useReference вызван вне ReferenceProvider');
  return ctx;
}
