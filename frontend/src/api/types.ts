/**
 * Типы предметной области.
 *
 * Описаны вручную по фактическим ответам API: так экраны читаются понятнее,
 * чем через сгенерированный `schema.ts` с ключами-путями. Полная машинная
 * спецификация лежит рядом в `schema.ts` (обновляется командой
 * `npm run api:types`) и служит источником правды при расхождениях.
 */

export type Role = 'candidate' | 'employer' | 'admin';
export type Level = 'junior' | 'middle' | 'senior';

export type Ref = { slug: string; title: string };
export type SkillRef = Ref & { specializations?: string[] };

export type Direction = Ref & { available: boolean };

export type Reference = {
  /** Правила для кандидатов младше 18 лет: тест — с min_age, показ работодателям и отклики — с work_age. */
  minors?: { min_age: number; work_age?: number; adult_age: number; note: string };
  /** Демо-стенд: открыты служебные методы для жюри (сброс попыток, экспресс-режим теста). */
  demo_mode?: boolean;
  /** IT-направления, по которым есть тест (backend, frontend, qa) — «отрасль» в ТЗ. */
  specializations: Ref[];
  /** Все IT-направления: готовые и запланированные. */
  directions?: Direction[];
  /** Специализации внутри направления: Python, React, автоматизация… */
  tracks?: Record<string, Ref[]>;
  salary?: { basis: string; note: string };
  levels: Ref[];
  /** Предметная область (финтех, госсектор…) — необязательна. */
  industries: Ref[];
  work_formats: Ref[];
  team_roles: Ref[];
  soft_skills: Ref[];
  skills: SkillRef[];
  competencies: Record<string, unknown>;
  decline_reasons: Ref[];
  fsp: Record<string, Ref[] | unknown>;
};

export type Me = {
  id: string;
  email: string;
  role: Role;
  public_id: string | null;
  email_verified: boolean;
  auth_mode: string;
  /** Демо-учётная запись: удалить её и сменить ей пароль нельзя. */
  demo_account?: boolean;
  /** Пароля нет (вход был через ФСП ID): задать его можно восстановлением. */
  has_password?: boolean;
};

/** Ответ регистрации; ссылка подтверждения приходит только в демо-режиме. */
export type RegisterResult = {
  message: string;
  email_verification_required: boolean;
  dev_verification_link?: string | null;
};

export type TokenPair = {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
  refresh_expires_in: number;
};

// ----------------------------------------------------------- кандидат

export type Privacy = {
  show_full_name: boolean;
  show_city: boolean;
  show_about: boolean;
  show_fsp: boolean;
  show_experience: boolean;
};

export type CandidateProfile = {
  public_id: string;
  full_name: string | null;
  email: string | null;
  contact_email: string | null;
  phone: string | null;
  telegram: string | null;
  city: string | null;
  about: string | null;
  relocation: boolean;
  experience_years: number | null;
  stack: string[];
  roles: string[];
  soft_skills: string[];
  work_formats: string[];
  salary_expectation: number | null;
  open_to_offers: boolean;
  industry: string | null;
  /** Дата рождения (YYYY-MM-DD); работодатель видит только отметку «до 18 лет». */
  birth_date?: string | null;
  age?: number | null;
  /** Младше 18 лет: профиль показывается после согласия законного представителя. */
  minor?: boolean;
  /** Младше 15 лет: доступны только тест и категория, без показа работодателям и откликов. */
  below_work_age?: boolean;
  guardian?: Guardian | null;
  primary_specialization: string | null;
  primary_track?: string | null;
  privacy: Privacy;
  resume_filename: string | null;
  resume_uploaded_at: string | null;
  grades: { specialization: string; level: Level; assigned_at: string }[];
  completeness: number;
};

export type Guardian = {
  status: 'pending' | 'granted' | 'declined' | 'revoked';
  guardian_name: string;
  guardian_email: string;
  requested_at: string;
  decided_at: string | null;
  expires_at: string;
};

/** Страница законного представителя по ссылке из письма. */
export type GuardianView = {
  candidate_name: string;
  candidate_age: number | null;
  guardian_name: string;
  status: Guardian['status'];
  expires_at: string;
  link_expired: boolean;
  what: string[];
  /** После отказа или отзыва ссылка больше не действует: нужен новый запрос кандидата. */
  link_closed?: boolean;
};

export type Consent = {
  kind: string;
  title: string;
  granted: boolean;
  version: string | null;
  updated_at: string | null;
};

export type Competency = {
  competency: string;
  title: string;
  estimate: number;
  raw_rate: number;
  items: number;
  confidence: number;
  confidence_label: string;
};

export type Availability = {
  level: Level;
  allowed: boolean;
  reason?: string | null;
  message?: string | null;
  available_at?: string | null;
};

export type AttemptSummary = {
  id: string;
  specialization: string;
  declared_level: Level;
  status: 'in_progress' | 'finished' | 'expired';
  started_at: string;
  finished_at: string | null;
  score: number | null;
  outcome: string | null;
  evidence_level: Level | null;
  applied: { action: string; level: Level | null; message: string } | null;
};

export type GradeInfo = {
  level: Level;
  assigned_at: string;
  last_change_at: string;
  category: string;
  /** Результат был выше уровня: тест этого уровня доступен без ожидания до даты until. */
  promotion_offer?: { level: Level; until: string } | null;
};

/**
 * Статус тестирования. До прохождения опроса бэкенд отдаёт укороченный
 * ответ (только `specialization`, `next_step` и `message`), поэтому
 * остальные поля помечены необязательными.
 */
export type AssessmentStatus = {
  specialization: string | null;
  specialization_title?: string | null;
  /** «Отрасль» в ТЗ — IT-направление. */
  direction_title?: string | null;
  track?: string | null;
  track_title?: string | null;
  /** Предметная область (необязательно). */
  industry?: string | null;
  self_level?: Level | null;
  next_step: 'survey' | 'take_test' | 'continue_attempt' | 'decide_recommendation' | 'done';
  message?: string;
  grade?: GradeInfo | null;
  recommendation?: {
    level: Level;
    attempt_id: string;
    created_at: string;
    message: string;
  } | null;
  active_attempt?: { id: string; declared_level: Level; deadline_at: string } | null;
  availability?: Availability[];
  competencies?: Competency[];
  attempts?: AttemptSummary[];
  grade_history?: { from_level: Level | null; to_level: Level; reason: string; at: string }[];
  policy?: {
    attempt_time_limit_minutes: number;
    grade_change_cooldown_days: number;
    same_level_retry_days: number;
    recommendation_clean_days: number;
    promotion_offer_days?: number;
    test_size: number;
  };
};

export type ValidationType = 'single_choice' | 'multiple_choice' | 'numeric' | 'exact_match';

export type AttemptItem = {
  position: number;
  type: 'theory' | 'situational' | 'practical' | string;
  validation_type: ValidationType;
  question: string;
  code?: string | null;
  language?: string | null;
  options?: { id: string; text: string }[] | null;
};

/** Разбивка результата по сложности заданий. */
export type DifficultyBucket = {
  points_earned: number;
  points_possible: number;
  items: number;
  correct: number;
  rate: number;
};

/** Компетенция в результате попытки: балл 0–100, достоверность словом. */
export type ResultCompetency = {
  competency: string;
  title: string;
  score: number;
  points_earned: number;
  points_possible: number;
  items: number;
  confidence: string;
};

export type GradeCheck = {
  check: string;
  title: string;
  passed: boolean;
  detail: string;
};

export type AttemptResult = {
  score: number;
  points_earned: number;
  points_possible: number;
  /** Балл, который набрал бы случайный ответ — точка отсчёта. */
  chance_baseline: number;
  outcome: string;
  outcome_title: string;
  evidence_level: string | null;
  applied: {
    action: string;
    level: Level | null;
    message: string;
    promotion_offer?: { level: Level; until: string } | null;
  } | null;
  difficulty_buckets: Record<string, DifficultyBucket>;
  competencies: ResultCompetency[];
  /** Проверки правил грейда, сгруппированные по уровню. */
  checks: Record<string, GradeCheck[]>;
  finish_reason: string | null;
  /** Признаки для разбора (быстрые ответы, уход со вкладки, копирование). На грейд не влияют. */
  flags?: AttemptFlag[];
};

export type AttemptFlag = { code: string; message: string; count?: number };

export type Attempt = {
  id: string;
  specialization: string;
  declared_level: Level;
  test_label: string;
  status: 'in_progress' | 'finished' | 'expired';
  started_at: string;
  deadline_at: string;
  seconds_left: number;
  items: AttemptItem[];
  answers: Record<string, string | string[] | null>;
  answered: number;
  result: AttemptResult | null;
};

export type Survey = {
  id: string;
  industry: string | null;
  specialization: string;
  specialization_title?: string;
  track?: string | null;
  track_title?: string | null;
  self_level: Level;
  experience_years: number | null;
  stack: string[];
  roles: string[];
  work_formats: string[];
  goals: string | null;
  created_at: string;
};

export type FspAchievement = {
  event_name: string;
  discipline: string;
  discipline_title: string;
  event_level: string;
  event_level_title: string;
  result: string;
  result_title: string;
  place: number | null;
  team_role: string | null;
  team_name: string | null;
  event_date: string;
  verified: boolean;
  certificate_url: string | null;
};

/** Число соревнований и результативность — то, что учитывается в весе ФСП. */
export type FspStats = { competitions: number; wins: number; podiums: number; finals: number };

export type FspProfile = {
  linked: boolean;
  fsp_id?: string | null;
  display_name?: string | null;
  region?: string | null;
  linked_at?: string | null;
  last_sync_at?: string | null;
  sync_error?: string | null;
  score?: number;
  /** Спортивный разряд из реестра. */
  sport_rank?: string | null;
  sport_rank_title?: string | null;
  stats?: FspStats;
  achievements: FspAchievement[];
  /** Текст для случая «истории ФСП нет» — показываем как есть, нейтрально. */
  note?: string | null;
  hidden_by_candidate?: boolean;
};

export type InvitationStatus =
  | 'sent'
  | 'viewed'
  | 'accepted'
  | 'declined'
  | 'expired'
  | 'withdrawn';

export type TimelineEvent = {
  actor: 'candidate' | 'employer' | 'system' | string;
  event: string;
  note: string | null;
  at: string;
};

/** Показатели компании: что кандидат должен знать до ответа на приглашение. */
export type CompanyTrust = {
  verified: boolean;
  review_status: 'active' | 'on_review' | 'blocked' | string;
  days_on_platform: number;
  invitations_sent: number;
  acceptance_rate: number | null;
  complaints_recent: number;
  warnings: string[];
};

export type Invitation = {
  id: string;
  status: InvitationStatus;
  title: string;
  description: string;
  salary_from: number;
  salary_to: number;
  /** «до вычета НДФЛ» — основа всех сумм на платформе. */
  salary_note?: string;
  work_format: string | null;
  contact_method: string;
  /** Предложение подходит для несовершеннолетних (15–17 лет). */
  suitable_for_minors?: boolean;
  company: {
    id?: string;
    name: string;
    industry?: string | null;
    city?: string | null;
    website?: string | null;
    description?: string | null;
  };
  company_trust?: CompanyTrust | null;
  salary_warnings?: string[];
  /** Пункты «почему вы» — готовый текст с бэкенда. */
  why_you?: string[] | null;
  need?: { id: string; title: string; level: Level } | null;
  created_at: string;
  viewed_at: string | null;
  responded_at: string | null;
  expires_at: string | null;
  timeline: TimelineEvent[];
  decline_reason?: string | null;
  decline_reason_title?: string | null;
  decline_comment?: string | null;
  /** Поля со стороны работодателя. */
  candidate_id?: string;
  candidate_name?: string;
  need_id?: string | null;
  match?: Match | null;
  /** Принято и не отозвано: сами контакты — в карточке кандидата. */
  contacts_visible?: boolean;
  /** Со стороны кандидата: видит ли компания сейчас контакты. */
  contacts_shared?: boolean;
  contacts_revoked_at?: string | null;
  unread_messages?: number;
};

export type Message = {
  id: string;
  sender: 'candidate' | 'employer';
  mine: boolean;
  body: string;
  created_at: string;
  read_at: string | null;
};

export type Vacancy = {
  id: string;
  title: string;
  specialization: string;
  specialization_title: string;
  level: Level;
  description: string;
  team_description?: string | null;
  stack: Ref[];
  work_format: string | null;
  work_format_title?: string | null;
  city: string | null;
  salary_from: number;
  salary_to: number;
  salary_note?: string;
  status: string;
  /** Подходит для несовершеннолетних (15–17 лет): лёгкий труд, сокращённое время, без вредных условий. */
  suitable_for_minors?: boolean;
  company: { id?: string; name: string; industry?: string | null; city?: string | null };
  company_trust?: CompanyTrust | null;
  salary_warnings?: string[];
  published_at: string | null;
  /** Поля из рекомендаций кандидату. */
  fits_my_category?: boolean;
  salary_fits?: boolean;
  applied?: boolean;
};

export type Paged<T> = { total: number; items: T[] };

// -------------------------------------------------------- работодатель

export type Company = {
  id?: string;
  name: string | null;
  inn: string | null;
  industry: string | null;
  description: string | null;
  website: string | null;
  city: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  /** Добровольная метка «Компания проверена»: модератор сверил ИНН и название с ЕГРЮЛ. */
  verified?: boolean;
  verification_status?: 'none' | 'requested' | 'verified' | 'rejected';
  verification_title?: string;
  /** Причина отказа или почему метка снята. */
  verification_comment?: string | null;
  review_status?: 'active' | 'on_review' | 'blocked' | string | null;
  review_reason?: string | null;
  complaints?: number;
  created_at?: string;
};

export type NeedProfile = {
  competency_weights: Record<string, number>;
  top_competencies: { competency: string; title: string; weight: number; sources: string[] }[];
  skills: string[];
  skills_from_text: string[];
  role_profile: string;
};

export type Need = {
  id: string;
  title: string;
  specialization: string;
  level: Level;
  description: string;
  team_description: string | null;
  stack: string[];
  work_format: string | null;
  city: string | null;
  salary_from: number;
  salary_to: number;
  is_published: boolean;
  status: string;
  suitable_for_minors?: boolean;
  profile: NeedProfile;
  created_at: string;
  published_at: string | null;
};

export type CandidateCard = {
  candidate_id: string;
  display_name: string;
  city: string | null;
  relocation: boolean;
  category: {
    specialization: string;
    specialization_title: string;
    track?: string | null;
    track_title?: string | null;
    level: Level;
    /** false — грейд заявлен, но не подтверждён тестом; такие кандидаты идут ниже. */
    confirmed?: boolean;
    status?: 'confirmed' | 'not_tested' | 'not_confirmed' | 'decision_pending' | string;
    status_title?: string;
    confirmed_at: string | null;
  } | null;
  test: {
    score: number;
    declared_level: Level;
    finished_at: string;
    level_band_rate: number;
    level_band_detail?: {
      band: string;
      rate: number;
      points: number[];
      smoothed: number;
      category_average: number;
    }[];
    percentile_in_category: number;
    attempts_total: number;
    grade_decision?: string | null;
    /** Признаки для разбора по определяющей попытке; на грейд не влияют. */
    flags?: AttemptFlag[];
  } | null;
  competencies: Competency[];
  stack: Ref[];
  experience_years: number | null;
  roles: Ref[];
  soft_skills?: Ref[];
  work_formats: Ref[];
  salary_expectation: number | null;
  open_to_offers: boolean;
  /** Кандидату меньше 18 лет (дата рождения не раскрывается). */
  minor?: boolean;
  minor_note?: string | null;
  last_active_at: string | null;
  fsp: {
    linked: boolean;
    hidden_by_candidate: boolean;
    score: number;
    headline: string | null;
    sport_rank?: string | null;
    sport_rank_title?: string | null;
    stats?: FspStats;
    achievements: FspAchievement[];
    note: string | null;
  };
  about?: string | null;
  /** Сводка по регулярным заданиям: свежий сигнал о кандидате. */
  regular_tasks?: {
    total?: number;
    solved?: number;
    last_at?: string | null;
    recent?: { title: string; status: string; score: number | null; at: string | null }[];
  } | null;
  contacts_visible?: boolean;
  contacts?: Record<string, string | null> | null;
  /** Текст-заглушка вместо контактов, пока они закрыты. */
  contacts_note?: string | null;
  /** Категории в других направлениях — только в карточке кандидата. */
  other_categories?: NonNullable<CandidateCard['category']>[];
};

export type MatchFactor = {
  factor: string;
  title: string;
  value: number;
  weight: number;
  contribution: number;
  text: string;
};

/**
 * Разложение балла. В подборке заполнены все поля, в списках категории и
 * поиска по банку — только то, что считается без потребности работодателя.
 */
/** Одна причина снижения балла и её цена в баллах. */
export type PenaltyReason = { title: string; points: number };

export type Match = {
  score: number;
  base_score: number | null;
  penalty: number | null;
  penalty_reasons: PenaltyReason[];
  factors: MatchFactor[];
  highlights: string[];
  warnings: string[];
  category_role: string | null;
};

export type RankedCandidate = { candidate: CandidateCard; ranking: Match };

export type SelectionRow = {
  rank: number;
  candidate_id: string;
  candidate: CandidateCard;
  match: Match;
};

export type Selection = {
  id: string;
  need_id: string;
  parent_id: string | null;
  params: Record<string, unknown>;
  summary: {
    total_matched: number;
    shown: number;
    by_level: Record<string, number>;
    recommended_categories: { level: Level; role: string; candidates: number }[];
    need_profile: Pick<NeedProfile, 'top_competencies' | 'skills'>;
    created_at: string;
  };
  results: SelectionRow[];
  /** Цепочка уточнений: к любой предыдущей подборке можно вернуться. */
  chain?: SelectionChainLink[];
  /** Сколько кандидатов подборки больше недоступны (закрыли профиль или удалили учётную запись). */
  unavailable?: number;
};

export type SelectionChainLink = {
  id: string;
  params: SearchFilters;
  total: number;
  created_at: string;
};

/** Единый набор фильтров: подборка, уточнение и поиск по банку. */
export type SearchFilters = {
  specialization?: string | null;
  levels?: string[] | null;
  stack_all?: string[] | null;
  has_fsp?: boolean | null;
  city?: string | null;
  work_format?: string | null;
  salary_max?: number | null;
  within_budget?: boolean;
  min_score?: number | null;
  text?: string | null;
  track?: string | null;
  confirmed_only?: boolean;
  hide_minors?: boolean;
  limit?: number;
};

export type CategoryCell = {
  specialization: string;
  specialization_title: string;
  level: Level;
  title: string;
  candidates: number;
  /** Кандидаты с заявленным, но не подтверждённым грейдом. */
  unconfirmed?: number;
  with_fsp_achievements: number;
  avg_profile_strength: number;
};

export type InvitationStats = {
  total: number;
  by_status: Record<string, number>;
  acceptance_rate: number | null;
  decline_reasons: { reason: string; title: string; count: number }[];
};

// ------------------------------------------------- отклики и задания

export type Application = {
  id: string;
  status: 'sent' | 'viewed' | 'invited' | 'rejected' | 'withdrawn' | string;
  cover_letter: string | null;
  employer_comment: string | null;
  contacts_shared?: boolean;
  unread_messages?: number;
  created_at: string;
  updated_at: string;
  timeline: TimelineEvent[];
  vacancy: Vacancy;
  /** Поля со стороны работодателя. */
  candidate_id?: string;
  candidate?: CandidateCard | null;
  match?: Match | null;
};

export type RecommendedVacancies = {
  category: { specialization: string; level: Level } | null;
  /** Кандидат младше 18: показаны только подходящие для несовершеннолетних (15–17 лет). */
  minor?: boolean;
  items: Vacancy[];
};

export type TaskAnswer = {
  text?: string | null;
  option?: string | null;
  number?: number | string | null;
};

export type TaskAssignment = {
  id: string;
  status: 'assigned' | 'submitted' | 'reviewed' | 'expired' | string;
  assigned_at: string;
  due_at: string | null;
  submitted_at: string | null;
  auto_correct: boolean | null;
  employer_score: number | null;
  employer_comment: string | null;
  /** Ответ приходит объектом: ключ зависит от вида задания. */
  answer: TaskAnswer | null;
  task: {
    title: string;
    body: string;
    kind: 'choice' | 'numeric' | 'approach';
    options: { id: string; text: string }[];
    company: string | null;
    level_range: string[];
  };
};

export type EmployerTask = {
  id: string;
  title: string;
  kind: 'choice' | 'numeric' | 'approach';
  specialization: string;
  level_range: string[];
  active: boolean;
  assigned: number;
  submitted: number;
  awaiting_review: number;
};

export type WebhookEvent = { event: string; title: string };

export type WebhookEndpoint = {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  created_at: string;
  last_delivery_at?: string | null;
  secret?: string;
};

export type WebhookDelivery = {
  id: string;
  event: string;
  status: string;
  response_code: number | null;
  attempts: number;
  created_at: string;
  error?: string | null;
};

export type AdminCompany = {
  id: string;
  name: string;
  inn?: string | null;
  website?: string | null;
  verification_status?: string;
  verification_requested_at?: string | null;
  review_status: string;
  review_reason: string | null;
  reviewed_at: string | null;
  complaints: number;
  trust?: CompanyTrust | null;
};

export type AdminComplaint = {
  id: string;
  reason: string;
  reason_title?: string;
  comment: string | null;
  created_at: string;
  invitation_id?: string | null;
  vacancy_id?: string | null;
};
