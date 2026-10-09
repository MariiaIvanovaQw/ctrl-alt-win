import type { CandidateCard, Role } from '../api/types';

/** Домашний экран роли — куда вести после входа. */
export function homeFor(role: Role | undefined | null): string {
  if (role === 'employer') return '/employer/selection';
  if (role === 'admin') return '/admin/companies';
  return '/candidate';
}

/**
 * Карточка кандидата в том направлении, где работодатель его нашёл: у
 * кандидата может быть несколько категорий, по одной на направление.
 */
export function candidateLink(c: Pick<CandidateCard, 'candidate_id' | 'category'>): string {
  const spec = c.category?.specialization;
  return `/employer/candidates/${c.candidate_id}${spec ? `?spec=${encodeURIComponent(spec)}` : ''}`;
}
