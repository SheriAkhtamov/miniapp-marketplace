import Database from 'better-sqlite3';
import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const now = () => new Date().toISOString();

const vacancySeeds = [
  {
    slug: 'office-manager',
    title: 'Офис менеджер',
    description:
      'Офисная роль для местного жителя Ташкента. Опыт работы не требуется. Зарплата: 1 500 000 сум.',
    criteria: [
      {
        key: 'age',
        label: 'Возраст 18-25',
        hard: true,
        sensitive: true,
        expected: '18-25'
      },
      {
        key: 'is_student',
        label: 'Не студент',
        hard: true,
        sensitive: false,
        expected: 'Нет'
      },
      {
        key: 'salary_accepted',
        label: 'Согласен на зарплату 1 500 000 сум',
        hard: true,
        sensitive: false,
        expected: 'Да'
      },
      {
        key: 'lives_in_tashkent',
        label: 'Местный житель Ташкента',
        hard: true,
        sensitive: false,
        expected: 'Да'
      },
      {
        key: 'gender',
        label: 'Девушка',
        hard: true,
        sensitive: true,
        expected: 'female'
      },
      {
        key: 'experience',
        label: 'Без опыта работы допустимо',
        hard: false,
        sensitive: false,
        expected: 'Опыт не обязателен'
      }
    ]
  },
  {
    slug: 'sales-representative',
    title: 'Торговый представитель',
    description:
      'Торговый представитель с опытом от 3 лет и готовностью работать по 100% KPI.',
    criteria: [
      {
        key: 'age',
        label: 'Возраст 22-36',
        hard: true,
        sensitive: true,
        expected: '22-36'
      },
      {
        key: 'is_student',
        label: 'Не студент',
        hard: true,
        sensitive: false,
        expected: 'Нет'
      },
      {
        key: 'work_experience_years',
        label: 'Опыт работы от 3 лет',
        hard: true,
        sensitive: false,
        expected: '>= 3'
      },
      {
        key: 'kpi_ready',
        label: 'Готовность к 100% KPI',
        hard: true,
        sensitive: false,
        expected: 'Да'
      }
    ]
  }
];

export function createDb(databasePath = './data/hr-bot.sqlite') {
  const resolvedPath = path.resolve(databasePath);
  fs.mkdirSync(path.dirname(resolvedPath), { recursive: true });

  const db = new Database(resolvedPath);
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = ON');

  migrate(db);
  normalizeCandidateSchema(db);
  seedVacancies(db);
  disableGlobalQuestionnaireQuestions(db);

  return db;
}

function migrate(db) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS vacancies (
      slug TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      criteria_json TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS candidates (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      telegram_user_id TEXT NOT NULL,
      username TEXT,
      first_name TEXT,
      last_name TEXT,
      language_code TEXT,
      preferred_language TEXT NOT NULL DEFAULT '',
      vacancy_slug TEXT REFERENCES vacancies(slug),
      status TEXT NOT NULL DEFAULT 'new',
      screening_status TEXT NOT NULL DEFAULT 'screening',
      admin_status TEXT,
      fit_score INTEGER NOT NULL DEFAULT 0,
      verdict_reason TEXT NOT NULL DEFAULT '',
      summary TEXT NOT NULL DEFAULT '',
      extracted_json TEXT NOT NULL DEFAULT '{}',
      criteria_json TEXT NOT NULL DEFAULT '[]',
      missing_fields_json TEXT NOT NULL DEFAULT '[]',
      last_question TEXT NOT NULL DEFAULT '',
      current_question_id INTEGER,
      state TEXT NOT NULL DEFAULT 'new',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS questionnaire_questions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      text_ru TEXT NOT NULL,
      text_uz TEXT NOT NULL DEFAULT '',
      type TEXT NOT NULL DEFAULT 'text' CHECK(type IN ('text', 'single_choice')),
      options_json TEXT NOT NULL DEFAULT '[]',
      is_criterion INTEGER NOT NULL DEFAULT 0,
      active INTEGER NOT NULL DEFAULT 1,
      sort_order INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS candidate_answers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
      question_id INTEGER NOT NULL REFERENCES questionnaire_questions(id),
      question_text TEXT NOT NULL,
      answer_text TEXT NOT NULL,
      selected_option_id TEXT,
      is_criterion INTEGER NOT NULL DEFAULT 0,
      passed_criterion INTEGER,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(candidate_id, question_id)
    );

    CREATE TABLE IF NOT EXISTS telegram_profiles (
      telegram_user_id TEXT PRIMARY KEY,
      username TEXT,
      first_name TEXT,
      last_name TEXT,
      language_code TEXT,
      preferred_language TEXT NOT NULL DEFAULT '',
      active_candidate_id INTEGER REFERENCES candidates(id) ON DELETE SET NULL,
      pending_vacancy_slug TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
      role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
      content TEXT NOT NULL,
      raw_json TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS admin_notes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
      note TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
    CREATE INDEX IF NOT EXISTS idx_candidates_vacancy ON candidates(vacancy_slug);
    CREATE INDEX IF NOT EXISTS idx_candidates_telegram ON candidates(telegram_user_id);
    CREATE INDEX IF NOT EXISTS idx_candidate_answers_candidate ON candidate_answers(candidate_id);
    CREATE INDEX IF NOT EXISTS idx_questionnaire_questions_active ON questionnaire_questions(active, sort_order);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_user_vacancy_unique
      ON candidates(telegram_user_id, vacancy_slug)
      WHERE vacancy_slug IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_messages_candidate ON messages(candidate_id, created_at);
  `);
}

function normalizeCandidateSchema(db) {
  const candidateSql = db
    .prepare("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'candidates'")
    .get()?.sql || '';
  let columns = db.prepare('PRAGMA table_info(candidates)').all().map((column) => column.name);

  if (/telegram_user_id\s+TEXT\s+UNIQUE/i.test(candidateSql)) {
    const screeningSource = columns.includes('screening_status')
      ? 'screening_status'
      : columns.includes('ai_status')
        ? 'ai_status'
        : "'screening'";
    const summarySource = columns.includes('summary')
      ? 'summary'
      : columns.includes('ai_summary')
        ? 'ai_summary'
        : "''";

    db.exec(`
      PRAGMA foreign_keys = OFF;

      CREATE TABLE candidates_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_user_id TEXT NOT NULL,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        language_code TEXT,
        preferred_language TEXT NOT NULL DEFAULT '',
        vacancy_slug TEXT REFERENCES vacancies(slug),
        status TEXT NOT NULL DEFAULT 'new',
        screening_status TEXT NOT NULL DEFAULT 'screening',
        admin_status TEXT,
        fit_score INTEGER NOT NULL DEFAULT 0,
        verdict_reason TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        extracted_json TEXT NOT NULL DEFAULT '{}',
        criteria_json TEXT NOT NULL DEFAULT '[]',
        missing_fields_json TEXT NOT NULL DEFAULT '[]',
        last_question TEXT NOT NULL DEFAULT '',
        current_question_id INTEGER,
        state TEXT NOT NULL DEFAULT 'new',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );

      INSERT INTO candidates_new (
        id, telegram_user_id, username, first_name, last_name, language_code, preferred_language,
        vacancy_slug, status, screening_status, admin_status, fit_score, verdict_reason, summary,
        extracted_json, criteria_json, missing_fields_json, last_question, current_question_id, state, created_at, updated_at
      )
      SELECT
        id, COALESCE(telegram_user_id, ''), username, first_name, last_name, language_code, '',
        vacancy_slug, status, ${screeningSource}, admin_status, fit_score, verdict_reason, ${summarySource},
        extracted_json, criteria_json, missing_fields_json, last_question, NULL, state, created_at, updated_at
      FROM candidates
      WHERE COALESCE(telegram_user_id, '') != '';

      DROP TABLE candidates;
      ALTER TABLE candidates_new RENAME TO candidates;
      PRAGMA foreign_keys = ON;
    `);

    columns = db.prepare('PRAGMA table_info(candidates)').all().map((column) => column.name);
  }

  if (!columns.includes('preferred_language')) {
    db.exec("ALTER TABLE candidates ADD COLUMN preferred_language TEXT NOT NULL DEFAULT ''");
    columns.push('preferred_language');
  }

  if (!columns.includes('current_question_id')) {
    db.exec('ALTER TABLE candidates ADD COLUMN current_question_id INTEGER');
    columns.push('current_question_id');
  }

  if (!columns.includes('screening_status')) {
    db.exec("ALTER TABLE candidates ADD COLUMN screening_status TEXT NOT NULL DEFAULT 'screening'");
    if (columns.includes('ai_status')) {
      db.exec("UPDATE candidates SET screening_status = COALESCE(NULLIF(ai_status, ''), status, 'screening')");
    }
    columns.push('screening_status');
  }

  if (!columns.includes('summary')) {
    db.exec("ALTER TABLE candidates ADD COLUMN summary TEXT NOT NULL DEFAULT ''");
    if (columns.includes('ai_summary')) {
      db.exec("UPDATE candidates SET summary = COALESCE(ai_summary, '')");
    }
    columns.push('summary');
  }

  db.exec(`
    CREATE TABLE IF NOT EXISTS telegram_profiles (
      telegram_user_id TEXT PRIMARY KEY,
      username TEXT,
      first_name TEXT,
      last_name TEXT,
      language_code TEXT,
      preferred_language TEXT NOT NULL DEFAULT '',
      active_candidate_id INTEGER REFERENCES candidates(id) ON DELETE SET NULL,
      pending_vacancy_slug TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TEMP TABLE IF NOT EXISTS duplicate_candidate_ids AS
      SELECT id
      FROM candidates
      WHERE vacancy_slug IS NOT NULL
        AND id NOT IN (
          SELECT MAX(id)
          FROM candidates
          WHERE vacancy_slug IS NOT NULL
          GROUP BY telegram_user_id, vacancy_slug
        );

    DELETE FROM messages WHERE candidate_id IN (SELECT id FROM duplicate_candidate_ids);
    DELETE FROM admin_notes WHERE candidate_id IN (SELECT id FROM duplicate_candidate_ids);
    DELETE FROM candidates WHERE id IN (SELECT id FROM duplicate_candidate_ids);
    DROP TABLE duplicate_candidate_ids;

    INSERT INTO telegram_profiles (
      telegram_user_id, username, first_name, last_name, language_code,
      preferred_language, active_candidate_id, created_at, updated_at
    )
    SELECT
      c.telegram_user_id,
      c.username,
      c.first_name,
      c.last_name,
      c.language_code,
      COALESCE(c.preferred_language, ''),
      c.id,
      c.created_at,
      c.updated_at
    FROM candidates c
    JOIN (
      SELECT telegram_user_id, MAX(id) AS id
      FROM candidates
      GROUP BY telegram_user_id
    ) latest ON latest.id = c.id
    ON CONFLICT(telegram_user_id) DO NOTHING;

    CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
    CREATE INDEX IF NOT EXISTS idx_candidates_vacancy ON candidates(vacancy_slug);
    CREATE INDEX IF NOT EXISTS idx_candidates_telegram ON candidates(telegram_user_id);
    CREATE INDEX IF NOT EXISTS idx_candidate_answers_candidate ON candidate_answers(candidate_id);
    CREATE INDEX IF NOT EXISTS idx_questionnaire_questions_active ON questionnaire_questions(active, sort_order);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_user_vacancy_unique
      ON candidates(telegram_user_id, vacancy_slug)
      WHERE vacancy_slug IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_messages_candidate ON messages(candidate_id, created_at);
  `);

  const qqColumns = db.prepare('PRAGMA table_info(questionnaire_questions)').all().map((c) => c.name);
  if (!qqColumns.includes('vacancy_slug')) {
    db.exec(`ALTER TABLE questionnaire_questions ADD COLUMN vacancy_slug TEXT REFERENCES vacancies(slug)`);
    db.exec(`CREATE INDEX IF NOT EXISTS idx_questionnaire_questions_vacancy ON questionnaire_questions(vacancy_slug)`);
  }
}

function seedVacancies(db) {
  const stmt = db.prepare(`
    INSERT INTO vacancies (slug, title, description, criteria_json, updated_at)
    VALUES (@slug, @title, @description, @criteria_json, @updated_at)
    ON CONFLICT(slug) DO UPDATE SET
      title = excluded.title,
      description = excluded.description,
      criteria_json = excluded.criteria_json,
      updated_at = excluded.updated_at
  `);

  for (const vacancy of vacancySeeds) {
    stmt.run({
      ...vacancy,
      criteria_json: JSON.stringify(vacancy.criteria),
      updated_at: now()
    });
  }
}

function disableGlobalQuestionnaireQuestions(db) {
  db.prepare(`
    UPDATE questionnaire_questions
    SET active = 0, updated_at = ?
    WHERE vacancy_slug IS NULL AND active = 1
  `).run(now());
}

export function getVacancies(db) {
  return db
    .prepare('SELECT * FROM vacancies WHERE active = 1 ORDER BY title ASC')
    .all()
    .map(parseVacancy);
}

export function getVacancy(db, slug) {
  const row = db.prepare('SELECT * FROM vacancies WHERE slug = ?').get(slug);
  return row ? parseVacancy(row) : null;
}

export function createVacancy(db, input = {}) {
  const title = cleanString(input.title);
  if (!title) {
    throw new Error('Название вакансии обязательно');
  }

  const baseSlug = slugifyVacancy(input.slug || title);
  let slug = baseSlug;
  let suffix = 2;
  while (vacancySlugExists(db, slug)) {
    slug = `${baseSlug}-${suffix}`;
    suffix += 1;
  }

  const timestamp = now();
  db.prepare(`
    INSERT INTO vacancies (
      slug, title, description, criteria_json, active, created_at, updated_at
    )
    VALUES (?, ?, ?, '[]', 1, ?, ?)
  `).run(slug, title, cleanString(input.description), timestamp, timestamp);

  return getVacancy(db, slug);
}

function vacancySlugExists(db, slug) {
  return Boolean(db.prepare('SELECT 1 FROM vacancies WHERE slug = ? LIMIT 1').get(slug));
}

export function listQuestionnaireQuestions(db, { includeInactive = false, vacancySlug = undefined } = {}) {
  if (vacancySlug === null) return [];

  const conditions = [];
  const params = {};
  if (!includeInactive) conditions.push('active = 1');
  if (vacancySlug !== undefined) {
    conditions.push('vacancy_slug = @vacancy_slug');
    params.vacancy_slug = vacancySlug;
  }
  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  return db
    .prepare(
      `SELECT * FROM questionnaire_questions
       ${where}
       ORDER BY sort_order ASC, id ASC`
    )
    .all(params)
    .map(parseQuestionnaireQuestion);
}

export function listQuestionsForCandidate(db, vacancySlug) {
  if (!vacancySlug) return [];

  return db
    .prepare(
      `SELECT * FROM questionnaire_questions
       WHERE active = 1 AND vacancy_slug = ?
       ORDER BY sort_order ASC, id ASC`
    )
    .all(vacancySlug)
    .map(parseQuestionnaireQuestion);
}

export function getQuestionnaireQuestion(db, id, { includeInactive = false } = {}) {
  const row = db
    .prepare(
      `SELECT * FROM questionnaire_questions
       WHERE id = ? ${includeInactive ? '' : 'AND active = 1'}
       LIMIT 1`
    )
    .get(Number(id));
  return row ? parseQuestionnaireQuestion(row) : null;
}

export function createQuestionnaireQuestion(db, input = {}) {
  const question = normalizeQuestionInput(input);
  const vacancySlug = cleanString(input.vacancySlug);
  if (!vacancySlug || !getVacancy(db, vacancySlug)) {
    throw new Error('Выберите вакансию для вопроса');
  }

  const maxOrder = getMaxQuestionSortOrder(db, vacancySlug);
  const timestamp = now();
  const result = db.prepare(`
    INSERT INTO questionnaire_questions (
      text_ru, text_uz, type, options_json, is_criterion, active, sort_order, vacancy_slug, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
  `).run(
    question.textRu,
    question.textUz,
    question.type,
    JSON.stringify(question.options),
    question.isCriterion ? 1 : 0,
    Number.isFinite(Number(input.sortOrder)) ? Number(input.sortOrder) : Number(maxOrder || 0) + 1,
    vacancySlug,
    timestamp,
    timestamp
  );
  return getQuestionnaireQuestion(db, result.lastInsertRowid);
}

function getMaxQuestionSortOrder(db, vacancySlug) {
  const row = vacancySlug
    ? db
        .prepare(
          `SELECT COALESCE(MAX(sort_order), 0) AS value
           FROM questionnaire_questions
           WHERE active = 1 AND vacancy_slug = ?`
        )
        .get(vacancySlug)
    : db
        .prepare(
          `SELECT COALESCE(MAX(sort_order), 0) AS value
           FROM questionnaire_questions
           WHERE active = 1 AND vacancy_slug IS NULL`
        )
        .get();
  return row?.value || 0;
}

export function updateQuestionnaireQuestion(db, id, input = {}) {
  const existing = getQuestionnaireQuestion(db, id, { includeInactive: true });
  if (!existing) return null;

  const question = normalizeQuestionInput({ ...existing, ...input });
  db.prepare(`
    UPDATE questionnaire_questions
    SET
      text_ru = ?,
      text_uz = ?,
      type = ?,
      options_json = ?,
      is_criterion = ?,
      sort_order = ?,
      updated_at = ?
    WHERE id = ?
  `).run(
    question.textRu,
    question.textUz,
    question.type,
    JSON.stringify(question.options),
    question.isCriterion ? 1 : 0,
    Number.isFinite(Number(input.sortOrder)) ? Number(input.sortOrder) : existing.sortOrder,
    now(),
    Number(id)
  );
  return getQuestionnaireQuestion(db, id, { includeInactive: true });
}

export function deleteQuestionnaireQuestion(db, id) {
  const existing = getQuestionnaireQuestion(db, id, { includeInactive: true });
  if (!existing) return null;

  db.prepare(`
    UPDATE questionnaire_questions
    SET active = 0, updated_at = ?
    WHERE id = ?
  `).run(now(), Number(id));
  return { ...existing, active: false };
}

export function getCandidateAnswers(db, candidateId) {
  return db
    .prepare(
      `SELECT
         a.*,
         q.text_ru AS current_question_text_ru,
         q.text_uz AS current_question_text_uz,
         q.sort_order AS question_sort_order,
         q.active AS question_active
       FROM candidate_answers a
       LEFT JOIN questionnaire_questions q ON q.id = a.question_id
       WHERE a.candidate_id = ?
       ORDER BY COALESCE(q.sort_order, 999999) ASC, a.id ASC`
    )
    .all(Number(candidateId))
    .map(parseCandidateAnswer);
}

export function getCandidateCurrentQuestion(db, candidateId) {
  const candidate = getCandidate(db, candidateId);
  if (!candidate?.currentQuestionId) {
    return getNextQuestionForCandidate(db, candidateId);
  }
  return (
    getQuestionnaireQuestion(db, candidate.currentQuestionId) ||
    getNextQuestionForCandidate(db, candidateId)
  );
}

export function setCandidateCurrentQuestion(db, candidateId, questionId = null) {
  const question = questionId ? getQuestionnaireQuestion(db, questionId) : null;
  db.prepare(`
    UPDATE candidates
    SET current_question_id = ?, last_question = ?, updated_at = ?
    WHERE id = ?
  `).run(question?.id || null, question ? question.textRu : '', now(), Number(candidateId));
  return getCandidate(db, candidateId);
}

export function getNextQuestionForCandidate(db, candidateId) {
  const candidate = getCandidate(db, candidateId);
  const answeredIds = getCandidateAnswers(db, candidateId).map((answer) => answer.questionId);
  const questions = listQuestionsForCandidate(db, candidate?.vacancySlug);
  return questions.find((question) => !answeredIds.includes(question.id)) || null;
}

export function getPreviousAnsweredQuestion(db, candidateId) {
  const candidate = getCandidate(db, candidateId);
  const answers = getCandidateAnswers(db, candidateId);
  if (!answers.length) return null;

  if (!candidate?.currentQuestionId) {
    return answers.at(-1) || null;
  }

  const currentQuestion = getQuestionnaireQuestion(db, candidate.currentQuestionId);
  if (!currentQuestion) return answers.at(-1) || null;

  return [...answers]
    .reverse()
    .find((answer) => Number(answer.questionSortOrder || 0) < currentQuestion.sortOrder) || null;
}

export function removeCandidateAnswer(db, candidateId, questionId) {
  db.prepare('DELETE FROM candidate_answers WHERE candidate_id = ? AND question_id = ?').run(
    Number(candidateId),
    Number(questionId)
  );
  return refreshCandidateQuestionnaireState(db, candidateId);
}

export function saveQuestionnaireAnswer(db, candidateId, question, answerInput = {}) {
  const normalized = normalizeAnswerInput(question, answerInput);
  const timestamp = now();
  db.prepare(`
    INSERT INTO candidate_answers (
      candidate_id, question_id, question_text, answer_text, selected_option_id,
      is_criterion, passed_criterion, created_at, updated_at
    )
    VALUES (
      @candidate_id, @question_id, @question_text, @answer_text, @selected_option_id,
      @is_criterion, @passed_criterion, @created_at, @updated_at
    )
    ON CONFLICT(candidate_id, question_id) DO UPDATE SET
      question_text = excluded.question_text,
      answer_text = excluded.answer_text,
      selected_option_id = excluded.selected_option_id,
      is_criterion = excluded.is_criterion,
      passed_criterion = excluded.passed_criterion,
      updated_at = excluded.updated_at
  `).run({
    candidate_id: Number(candidateId),
    question_id: question.id,
    question_text: question.textRu,
    answer_text: normalized.answerText,
    selected_option_id: normalized.selectedOptionId,
    is_criterion: question.isCriterion ? 1 : 0,
    passed_criterion:
      question.isCriterion && question.type === 'single_choice'
        ? normalized.passedCriterion ? 1 : 0
        : null,
    created_at: timestamp,
    updated_at: timestamp
  });

  return refreshCandidateQuestionnaireState(db, candidateId);
}

export function refreshCandidateQuestionnaireState(db, candidateId) {
  const candidate = getCandidate(db, candidateId);
  const questions = listQuestionsForCandidate(db, candidate?.vacancySlug);
  const answers = getCandidateAnswers(db, candidateId);
  const answeredIds = new Set(answers.map((answer) => answer.questionId));
  const missing = questions.filter((question) => !answeredIds.has(question.id));
  const criteria = buildQuestionnaireCriteria(questions, answers);
  const failedCriteria = criteria.filter((item) => item.hard && item.met === false);
  const completed = questions.length > 0 && missing.length === 0;
  const status = completed ? (failedCriteria.length ? 'not_fit' : 'qualified') : 'screening';
  const nextQuestion = completed ? null : missing[0] || null;
  const summary = buildQuestionnaireSummary(answers);
  const verdictReason = completed
    ? failedCriteria.length
      ? `Не выполнены критерии: ${failedCriteria.map((item) => item.label).join(', ')}.`
      : 'Все обязательные критерии анкеты подтверждены.'
    : missing.length
      ? `Осталось вопросов: ${missing.length}.`
      : 'Анкета в процессе.';

  db.prepare(`
    UPDATE candidates SET
      status = @status,
      screening_status = @status,
      fit_score = @fit_score,
      verdict_reason = @verdict_reason,
      summary = @summary,
      extracted_json = @extracted_json,
      criteria_json = @criteria_json,
      missing_fields_json = @missing_fields_json,
      current_question_id = @current_question_id,
      last_question = @last_question,
      state = @state,
      updated_at = @updated_at
    WHERE id = @id
  `).run({
    id: Number(candidateId),
    status,
    fit_score: calculateQuestionnaireScore(criteria, completed),
    verdict_reason: verdictReason,
    summary,
    extracted_json: JSON.stringify(buildQuestionnaireExtracted(answers)),
    criteria_json: JSON.stringify(criteria),
    missing_fields_json: JSON.stringify(missing.map((question) => String(question.id))),
    current_question_id: nextQuestion?.id || null,
    last_question: nextQuestion?.textRu || '',
    state: completed ? 'completed' : 'screening',
    updated_at: now()
  });

  return getCandidate(db, candidateId);
}

export function upsertTelegramProfile(db, from = {}) {
  const telegramUserId = String(from.id || '');
  if (!telegramUserId) {
    throw new Error('Telegram user id is required');
  }

  db.prepare(`
    INSERT INTO telegram_profiles (
      telegram_user_id, username, first_name, last_name, language_code, updated_at
    )
    VALUES (@telegram_user_id, @username, @first_name, @last_name, @language_code, @updated_at)
    ON CONFLICT(telegram_user_id) DO UPDATE SET
      username = excluded.username,
      first_name = excluded.first_name,
      last_name = excluded.last_name,
      language_code = excluded.language_code,
      updated_at = excluded.updated_at
  `).run({
    telegram_user_id: telegramUserId,
    username: from.username || '',
    first_name: from.first_name || '',
    last_name: from.last_name || '',
    language_code: from.language_code || '',
    updated_at: now()
  });

  db.prepare(`
    UPDATE candidates
    SET
      username = @username,
      first_name = @first_name,
      last_name = @last_name,
      language_code = @language_code,
      updated_at = @updated_at
    WHERE telegram_user_id = @telegram_user_id
  `).run({
    telegram_user_id: telegramUserId,
    username: from.username || '',
    first_name: from.first_name || '',
    last_name: from.last_name || '',
    language_code: from.language_code || '',
    updated_at: now()
  });

  return getTelegramProfile(db, telegramUserId);
}

export function upsertCandidateFromTelegram(db, from = {}) {
  const profile = upsertTelegramProfile(db, from);
  return getActiveCandidateByTelegramId(db, profile.telegramUserId) || getLatestCandidateByTelegramId(db, profile.telegramUserId);
}

export function getTelegramProfile(db, telegramUserId) {
  const row = db
    .prepare('SELECT * FROM telegram_profiles WHERE telegram_user_id = ?')
    .get(String(telegramUserId));
  return row ? parseTelegramProfile(row) : null;
}

export function setProfileLanguage(db, telegramUserId, language) {
  db.prepare(`
    UPDATE telegram_profiles
    SET preferred_language = ?, pending_vacancy_slug = NULL, updated_at = ?
    WHERE telegram_user_id = ?
  `).run(language, now(), String(telegramUserId));

  db.prepare(`
    UPDATE candidates
    SET preferred_language = ?, updated_at = ?
    WHERE telegram_user_id = ?
  `).run(language, now(), String(telegramUserId));

  return getTelegramProfile(db, telegramUserId);
}

export function setPendingVacancy(db, telegramUserId, vacancySlug) {
  db.prepare(`
    UPDATE telegram_profiles
    SET pending_vacancy_slug = ?, updated_at = ?
    WHERE telegram_user_id = ?
  `).run(vacancySlug, now(), String(telegramUserId));
}

export function clearPendingVacancy(db, telegramUserId) {
  db.prepare(`
    UPDATE telegram_profiles
    SET pending_vacancy_slug = NULL, updated_at = ?
    WHERE telegram_user_id = ?
  `).run(now(), String(telegramUserId));
}

export function setActiveCandidate(db, telegramUserId, candidateId = null) {
  db.prepare(`
    UPDATE telegram_profiles
    SET active_candidate_id = ?, updated_at = ?
    WHERE telegram_user_id = ?
  `).run(candidateId, now(), String(telegramUserId));
}

export function getCandidateByTelegramId(db, telegramUserId) {
  return getLatestCandidateByTelegramId(db, telegramUserId);
}

export function getLatestCandidateByTelegramId(db, telegramUserId) {
  const row = db
    .prepare('SELECT * FROM candidates WHERE telegram_user_id = ? ORDER BY datetime(updated_at) DESC, id DESC LIMIT 1')
    .get(String(telegramUserId));
  return row ? parseCandidate(row) : null;
}

export function getActiveCandidateByTelegramId(db, telegramUserId) {
  const profile = getTelegramProfile(db, telegramUserId);
  if (!profile?.activeCandidateId) return null;
  return getCandidate(db, profile.activeCandidateId);
}

export function getCandidateByTelegramAndVacancy(db, telegramUserId, vacancySlug) {
  const row = db
    .prepare('SELECT * FROM candidates WHERE telegram_user_id = ? AND vacancy_slug = ? LIMIT 1')
    .get(String(telegramUserId), vacancySlug);
  return row ? parseCandidate(row) : null;
}

export function getCandidate(db, id) {
  const row = db.prepare('SELECT * FROM candidates WHERE id = ?').get(id);
  return row ? parseCandidate(row) : null;
}

export function createOrGetCandidateForVacancy(db, from = {}, vacancySlug, { reset = false } = {}) {
  const profile = upsertTelegramProfile(db, from);
  const existing = getCandidateByTelegramAndVacancy(db, profile.telegramUserId, vacancySlug);
  const timestamp = now();

  if (!existing) {
    const result = db.prepare(`
      INSERT INTO candidates (
        telegram_user_id, username, first_name, last_name, language_code, preferred_language,
        vacancy_slug, status, screening_status, state, current_question_id, created_at, updated_at
      )
      VALUES (
        @telegram_user_id, @username, @first_name, @last_name, @language_code, @preferred_language,
        @vacancy_slug, 'screening', 'screening', 'screening', NULL, @created_at, @updated_at
      )
    `).run({
      telegram_user_id: profile.telegramUserId,
      username: from.username || profile.username || '',
      first_name: from.first_name || profile.firstName || '',
      last_name: from.last_name || profile.lastName || '',
      language_code: from.language_code || profile.languageCode || '',
      preferred_language: profile.preferredLanguage || '',
      vacancy_slug: vacancySlug,
      created_at: timestamp,
      updated_at: timestamp
    });
    setActiveCandidate(db, profile.telegramUserId, result.lastInsertRowid);
    return getCandidate(db, result.lastInsertRowid);
  }

  db.prepare(`
    UPDATE candidates
    SET
      username = @username,
      first_name = @first_name,
      last_name = @last_name,
      language_code = @language_code,
      preferred_language = @preferred_language,
      updated_at = @updated_at
    WHERE id = @id
  `).run({
    id: existing.id,
    username: from.username || profile.username || '',
    first_name: from.first_name || profile.firstName || '',
    last_name: from.last_name || profile.lastName || '',
    language_code: from.language_code || profile.languageCode || '',
    preferred_language: profile.preferredLanguage || '',
    updated_at: timestamp
  });

  if (reset) {
    resetCandidateForVacancy(db, existing.id);
  }

  setActiveCandidate(db, profile.telegramUserId, existing.id);
  return getCandidate(db, existing.id);
}

export function resetCandidateForVacancy(db, candidateId) {
  db.prepare('DELETE FROM messages WHERE candidate_id = ?').run(candidateId);
  db.prepare('DELETE FROM candidate_answers WHERE candidate_id = ?').run(candidateId);
  db.prepare(`
    UPDATE candidates
    SET
      status = 'screening',
      screening_status = 'screening',
      admin_status = NULL,
      fit_score = 0,
      verdict_reason = '',
      summary = '',
      extracted_json = '{}',
      criteria_json = '[]',
      missing_fields_json = '[]',
      last_question = '',
      current_question_id = NULL,
      state = 'screening',
      updated_at = ?
    WHERE id = ?
  `).run(now(), candidateId);
  return getCandidate(db, candidateId);
}

export function setCandidateVacancy(db, candidateId, vacancySlug) {
  db.prepare('UPDATE candidates SET vacancy_slug = ?, updated_at = ? WHERE id = ?').run(
    vacancySlug,
    now(),
    candidateId
  );
  return resetCandidateForVacancy(db, candidateId);
}

export function updateCandidateTelegramInfo(db, candidateId, from = {}) {
  const profile = upsertTelegramProfile(db, from);
  db.prepare(`
    UPDATE candidates
    SET
      username = @username,
      first_name = @first_name,
      last_name = @last_name,
      language_code = @language_code,
      preferred_language = @preferred_language,
      updated_at = @updated_at
    WHERE id = @id
  `).run({
    id: candidateId,
    username: from.username || profile.username || '',
    first_name: from.first_name || profile.firstName || '',
    last_name: from.last_name || profile.lastName || '',
    language_code: from.language_code || profile.languageCode || '',
    preferred_language: profile.preferredLanguage || '',
    updated_at: now()
  });
  return getCandidate(db, candidateId);
}

export function addMessage(db, candidateId, role, content, rawJson = null) {
  db.prepare(`
    INSERT INTO messages (candidate_id, role, content, raw_json, created_at)
    VALUES (?, ?, ?, ?, ?)
  `).run(candidateId, role, content, rawJson ? JSON.stringify(rawJson) : null, now());
}

export function getMessages(db, candidateId, limit = 30) {
  return db
    .prepare(
      `SELECT * FROM messages
       WHERE candidate_id = ?
       ORDER BY datetime(created_at) DESC, id DESC
       LIMIT ?`
    )
    .all(candidateId, limit)
    .reverse();
}

export function saveScreeningResult(db, candidateId, result) {
  db.prepare(`
    UPDATE candidates SET
      status = @status,
      screening_status = @screening_status,
      fit_score = @fit_score,
      verdict_reason = @verdict_reason,
      summary = @summary,
      extracted_json = @extracted_json,
      criteria_json = @criteria_json,
      missing_fields_json = @missing_fields_json,
      last_question = @last_question,
      state = @state,
      updated_at = @updated_at
    WHERE id = @id
  `).run({
    id: candidateId,
    status: result.status,
    screening_status: result.screeningStatus || result.status,
    fit_score: clampScore(result.fitScore),
    verdict_reason: result.verdictReason || '',
    summary: result.summary || '',
    extracted_json: JSON.stringify(result.extracted || {}),
    criteria_json: JSON.stringify(result.criteria || []),
    missing_fields_json: JSON.stringify(result.missingFields || []),
    last_question: result.reply || '',
    state: result.status === 'screening' ? 'screening' : 'completed',
    updated_at: now()
  });

  return getCandidate(db, candidateId);
}

export function listCandidates(db, filters = {}) {
  const params = {};
  const where = [];

  if (filters.vacancy && filters.vacancy !== 'all') {
    where.push('c.vacancy_slug = @vacancy');
    params.vacancy = filters.vacancy;
  }

  if (filters.status && filters.status !== 'all') {
    where.push('COALESCE(c.admin_status, c.status) = @status');
    params.status = filters.status;
  }

  if (filters.search) {
    where.push(`(
      c.first_name LIKE @search OR
      c.last_name LIKE @search OR
      c.username LIKE @search OR
      c.telegram_user_id LIKE @search OR
      c.summary LIKE @search OR
      EXISTS (
        SELECT 1 FROM candidate_answers a
        WHERE a.candidate_id = c.id
          AND (a.answer_text LIKE @search OR a.question_text LIKE @search)
      )
    )`);
    params.search = `%${filters.search}%`;
  }

  const sql = `
    SELECT c.*, v.title AS vacancy_title
    FROM candidates c
    LEFT JOIN vacancies v ON v.slug = c.vacancy_slug
    ${where.length ? `WHERE ${where.join(' AND ')}` : ''}
    ORDER BY datetime(c.updated_at) DESC, c.id DESC
    LIMIT @limit OFFSET @offset
  `;

  return db
    .prepare(sql)
    .all({
      ...params,
      limit: Number(filters.limit || 100),
      offset: Number(filters.offset || 0)
    })
    .map(parseCandidate);
}

export function getCandidateDetails(db, id) {
  const candidate = getCandidate(db, id);
  if (!candidate) return null;

  return {
    candidate,
    vacancy: candidate.vacancySlug ? getVacancy(db, candidate.vacancySlug) : null,
    answers: getCandidateAnswers(db, candidate.id),
    questions: listQuestionsForCandidate(db, candidate.vacancySlug),
    messages: getMessages(db, candidate.id, 100),
    notes: db
      .prepare('SELECT * FROM admin_notes WHERE candidate_id = ? ORDER BY datetime(created_at) DESC, id DESC')
      .all(candidate.id)
  };
}

export function updateAdminDecision(db, id, { adminStatus, note }) {
  const cleanStatus = adminStatus || null;
  db.prepare('UPDATE candidates SET admin_status = ?, updated_at = ? WHERE id = ?').run(
    cleanStatus,
    now(),
    id
  );

  if (note && note.trim()) {
    db.prepare('INSERT INTO admin_notes (candidate_id, note, created_at) VALUES (?, ?, ?)').run(
      id,
      note.trim(),
      now()
    );
  }

  return getCandidateDetails(db, id);
}

export function getDashboardStats(db) {
  const total = db.prepare('SELECT COUNT(*) AS count FROM candidates').get().count;
  const newToday = db
    .prepare("SELECT COUNT(*) AS count FROM candidates WHERE date(created_at) = date('now')")
    .get().count;
  const unprocessed = db
    .prepare(
      `SELECT COUNT(*) AS count
       FROM candidates
       WHERE COALESCE(admin_status, status) IN ('new', 'screening', 'needs_review')`
    )
    .get().count;
  const byStatus = db
    .prepare(
      `SELECT COALESCE(admin_status, status) AS status, COUNT(*) AS count
       FROM candidates
       GROUP BY COALESCE(admin_status, status)`
    )
    .all();
  const byVacancy = db
    .prepare(
      `SELECT v.slug AS slug, v.title AS title, COUNT(c.id) AS count
       FROM vacancies v
       LEFT JOIN candidates c ON c.vacancy_slug = v.slug
       WHERE v.active = 1
       GROUP BY v.slug, v.title
       ORDER BY count DESC, v.title ASC`
    )
    .all();
  const attentionCandidates = db
    .prepare(
      `SELECT c.*, v.title AS vacancy_title
       FROM candidates c
       LEFT JOIN vacancies v ON v.slug = c.vacancy_slug
       WHERE COALESCE(c.admin_status, c.status) IN ('screening', 'needs_review')
       ORDER BY datetime(c.updated_at) DESC, c.id DESC
       LIMIT 8`
    )
    .all()
    .map(parseCandidate);

  return { total, newToday, unprocessed, byStatus, byVacancy, attentionCandidates };
}

function parseVacancy(row) {
  return {
    slug: row.slug,
    title: row.title,
    description: row.description,
    criteria: safeJson(row.criteria_json, []),
    active: Boolean(row.active),
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
}

function parseQuestionnaireQuestion(row) {
  return {
    id: row.id,
    textRu: row.text_ru,
    textUz: row.text_uz || '',
    type: row.type || 'text',
    options: safeJson(row.options_json, []),
    isCriterion: Boolean(row.is_criterion),
    active: Boolean(row.active),
    sortOrder: row.sort_order,
    vacancySlug: row.vacancy_slug || null,
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
}

function normalizeQuestionInput(input = {}) {
  const type = input.type === 'single_choice' ? 'single_choice' : 'text';
  const textRu = cleanString(input.textRu ?? input.text_ru);
  const textUz = cleanString(input.textUz ?? input.text_uz);
  if (!textRu) {
    throw new Error('Текст вопроса обязателен');
  }

  return {
    textRu,
    textUz,
    type,
    isCriterion: type === 'single_choice' && Boolean(input.isCriterion ?? input.is_criterion),
    options: type === 'single_choice' ? normalizeQuestionOptions(input.options) : []
  };
}

function normalizeQuestionOptions(options = []) {
  return (Array.isArray(options) ? options : [])
    .map((option) => {
      const labelRu = cleanString(option.labelRu ?? option.label ?? option.text ?? option.value);
      const labelUz = cleanString(option.labelUz ?? option.label_uz);
      if (!labelRu) return null;
      return {
        id: cleanString(option.id) || randomUUID(),
        labelRu,
        labelUz,
        passes: Boolean(option.passes)
      };
    })
    .filter(Boolean);
}

function parseCandidateAnswer(row) {
  return {
    id: row.id,
    candidateId: row.candidate_id,
    questionId: row.question_id,
    questionText: row.question_text,
    currentQuestionTextRu: row.current_question_text_ru || '',
    currentQuestionTextUz: row.current_question_text_uz || '',
    questionSortOrder: row.question_sort_order,
    questionActive: row.question_active === null || row.question_active === undefined
      ? true
      : Boolean(row.question_active),
    answerText: row.answer_text,
    selectedOptionId: row.selected_option_id || '',
    isCriterion: Boolean(row.is_criterion),
    passedCriterion:
      row.passed_criterion === null || row.passed_criterion === undefined
        ? null
        : Boolean(row.passed_criterion),
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
}

function normalizeAnswerInput(question, answerInput = {}) {
  if (question.type === 'single_choice') {
    const option =
      answerInput.option ||
      question.options.find((item) => item.id === answerInput.selectedOptionId) ||
      findQuestionOptionByLabel(question, answerInput.answerText);
    if (!option) {
      throw new Error('Выберите один из вариантов ответа');
    }
    return {
      answerText: option.labelRu,
      selectedOptionId: option.id,
      passedCriterion: Boolean(option.passes)
    };
  }

  const answerText = cleanString(answerInput.answerText);
  if (!answerText) {
    throw new Error('Ответ не может быть пустым');
  }
  return {
    answerText,
    selectedOptionId: null,
    passedCriterion: null
  };
}

function findQuestionOptionByLabel(question, value) {
  const normalized = normalizeComparable(value);
  if (!normalized) return null;
  return question.options.find((option) => {
    return [option.labelRu, option.labelUz]
      .filter(Boolean)
      .some((label) => normalizeComparable(label) === normalized);
  });
}

function buildQuestionnaireCriteria(questions, answers) {
  const answerMap = new Map(answers.map((answer) => [answer.questionId, answer]));
  return questions
    .filter((question) => question.isCriterion)
    .map((question) => {
      const answer = answerMap.get(question.id);
      return {
        key: `question_${question.id}`,
        label: question.textRu,
        hard: true,
        met: answer ? answer.passedCriterion === true : null,
        evidence: answer?.answerText || 'Нет ответа'
      };
    });
}

function buildQuestionnaireSummary(answers) {
  if (!answers.length) return 'Анкета ещё не заполнена.';
  return answers
    .slice(0, 6)
    .map((answer) => `${answer.questionText}: ${answer.answerText}`)
    .join('\n');
}

function buildQuestionnaireExtracted(answers) {
  const extracted = {
    answers: answers.map((answer) => ({
      questionId: answer.questionId,
      question: answer.questionText,
      answer: answer.answerText,
      isCriterion: answer.isCriterion,
      passedCriterion: answer.passedCriterion
    }))
  };

  for (const answer of answers) {
    const question = normalizeComparable(answer.questionText);
    if (!extracted.full_name && /(фио|фамилия|имя|ism|familiya)/iu.test(question)) {
      extracted.full_name = answer.answerText;
    }
    if (!extracted.phone && /(телефон|phone|raqam)/iu.test(question)) {
      extracted.phone = answer.answerText;
    }
  }

  return extracted;
}

function calculateQuestionnaireScore(criteria, completed) {
  if (!completed) return 0;
  if (!criteria.length) return 100;
  const met = criteria.filter((item) => item.met === true).length;
  return Math.round((met / criteria.length) * 100);
}

function parseCandidate(row) {
  return {
    id: row.id,
    telegramUserId: row.telegram_user_id,
    username: row.username,
    firstName: row.first_name,
    lastName: row.last_name,
    languageCode: row.language_code,
    preferredLanguage: row.preferred_language || '',
    vacancySlug: row.vacancy_slug,
    vacancyTitle: row.vacancy_title,
    status: row.admin_status || row.status,
    screeningStatus: row.screening_status,
    adminStatus: row.admin_status,
    fitScore: row.fit_score,
    verdictReason: row.verdict_reason,
    summary: row.summary,
    extracted: safeJson(row.extracted_json, {}),
    criteria: safeJson(row.criteria_json, []),
    missingFields: safeJson(row.missing_fields_json, []),
    lastQuestion: row.last_question,
    currentQuestionId: row.current_question_id,
    state: row.state,
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
}

function parseTelegramProfile(row) {
  return {
    telegramUserId: row.telegram_user_id,
    username: row.username,
    firstName: row.first_name,
    lastName: row.last_name,
    languageCode: row.language_code,
    preferredLanguage: row.preferred_language || '',
    activeCandidateId: row.active_candidate_id,
    pendingVacancySlug: row.pending_vacancy_slug || '',
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
}

function safeJson(value, fallback) {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function cleanString(value) {
  if (value === undefined || value === null) return '';
  return String(value).trim();
}

function normalizeComparable(value) {
  return cleanString(value).toLowerCase().replace(/\s+/g, ' ');
}

function slugifyVacancy(value) {
  const transliteration = {
    а: 'a',
    б: 'b',
    в: 'v',
    г: 'g',
    д: 'd',
    е: 'e',
    ё: 'e',
    ж: 'zh',
    з: 'z',
    и: 'i',
    й: 'y',
    к: 'k',
    л: 'l',
    м: 'm',
    н: 'n',
    о: 'o',
    п: 'p',
    р: 'r',
    с: 's',
    т: 't',
    у: 'u',
    ф: 'f',
    х: 'h',
    ц: 'c',
    ч: 'ch',
    ш: 'sh',
    щ: 'sch',
    ъ: '',
    ь: '',
    ы: 'y',
    э: 'e',
    ю: 'yu',
    я: 'ya'
  };
  const slug = cleanString(value)
    .toLowerCase()
    .split('')
    .map((char) => transliteration[char] || char)
    .join('')
    .replace(/[ьъ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || `vacancy-${Date.now()}`;
}

function clampScore(score) {
  const numeric = Number(score || 0);
  if (Number.isNaN(numeric)) return 0;
  return Math.max(0, Math.min(100, Math.round(numeric)));
}
