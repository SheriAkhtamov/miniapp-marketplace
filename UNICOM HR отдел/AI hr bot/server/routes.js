import express from 'express';
import {
  createQuestionnaireQuestion,
  createVacancy,
  deleteQuestionnaireQuestion,
  getCandidateDetails,
  getDashboardStats,
  getVacancies,
  getVacancy,
  listCandidates,
  listQuestionnaireQuestions,
  updateQuestionnaireQuestion,
  updateAdminDecision
} from './db.js';

export function createRoutes(db, config, { settingsStore, botRuntime } = {}) {
  const router = express.Router();
  const requireSystemAuth = createRequireSystemAuth(config);
  const requireSettingsAccess = createRequireSettingsAccess(config);

  router.get('/health', asyncHandler(async (req, res) => {
    const settings = settingsStore
      ? await settingsStore.getSettings({ includeSecrets: false })
      : {
          botTokenConfigured: Boolean(config.telegram.botToken)
        };
    res.json({
      ok: true,
      botEnabled: botRuntime ? botRuntime.isRunning() : Boolean(config.telegram.botToken),
      botTokenConfigured: Boolean(settings.botTokenConfigured)
    });
  }));

  router.post('/api/login', (req, res) => {
    res.status(410).json({
      ok: false,
      error: 'Вход выполняется через UNICOM Market',
      loginUrl: buildLoginUrl(req, config)
    });
  });

  router.post('/api/logout', (req, res) => {
    res.json({ ok: true, logoutUrl: buildMarketUrl(config, '/admin/logout') });
  });

  router.get('/api/session', asyncHandler(async (req, res) => {
    const systemSession = await getSystemSession(req, config);
    if (!systemSession.authenticated) {
      res.json({
        authenticated: false,
        loginUrl: buildLoginUrl(req, config),
        workspaces: buildWorkspaces(config)
      });
      return;
    }

    res.json({
      authenticated: true,
      user: systemSession.user,
      workspaces: buildWorkspaces(config)
    });
  }));

  router.get('/api/vacancies', requireSystemAuth, (req, res) => {
    res.json({ vacancies: getVacancies(db) });
  });

  router.post(
    '/api/vacancies',
    requireSettingsAccess,
    express.json({ limit: '64kb' }),
    asyncHandler(async (req, res) => {
      const vacancy = createVacancy(db, req.body || {});
      res.status(201).json({ vacancy });
    })
  );

  router.get('/api/vacancies/:slug', requireSystemAuth, (req, res) => {
    const vacancy = getVacancy(db, req.params.slug);
    if (!vacancy) {
      res.status(404).json({ error: 'Вакансия не найдена' });
      return;
    }
    res.json({ vacancy });
  });

  router.get('/api/dashboard', requireSystemAuth, (req, res) => {
    res.json(getDashboardStats(db));
  });

  router.get('/api/settings', requireSettingsAccess, asyncHandler(async (req, res) => {
    const settings = await settingsStore.getSettings({ includeSecrets: false });
    res.json({
      settings: {
        botTokenConfigured: settings.botTokenConfigured,
        updatedAt: settings.updatedAt
      }
    });
  }));

  router.post(
    '/api/settings',
    requireSettingsAccess,
    express.json({ limit: '64kb' }),
    asyncHandler(async (req, res) => {
      const input = sanitizeSettingsInput(req.body || {});
      const updated = await settingsStore.updateSettings(input);

      const botState = botRuntime ? await botRuntime.refresh() : { running: updated.botTokenConfigured };
      const settings = await settingsStore.getSettings({ includeSecrets: false });

      res.json({
        ok: true,
        settings: {
          botTokenConfigured: settings.botTokenConfigured,
          updatedAt: settings.updatedAt
        },
        bot: botState
      });
    })
  );

  router.get('/api/questions', requireSettingsAccess, (req, res) => {
    const vacancySlug = req.query.vacancy;
    if (!vacancySlug) {
      res.json({ questions: [] });
      return;
    }

    const opts = {};
    opts.vacancySlug = vacancySlug;
    res.json({ questions: listQuestionnaireQuestions(db, opts) });
  });

  router.post(
    '/api/questions',
    requireSettingsAccess,
    express.json({ limit: '64kb' }),
    asyncHandler(async (req, res) => {
      const question = createQuestionnaireQuestion(db, req.body || {});
      res.status(201).json({ question });
    })
  );

  router.patch(
    '/api/questions/:id',
    requireSettingsAccess,
    express.json({ limit: '64kb' }),
    asyncHandler(async (req, res) => {
      const question = updateQuestionnaireQuestion(db, req.params.id, req.body || {});
      if (!question) {
        res.status(404).json({ error: 'Вопрос не найден' });
        return;
      }
      res.json({ question });
    })
  );

  router.delete(
    '/api/questions/:id',
    requireSettingsAccess,
    asyncHandler(async (req, res) => {
      const question = deleteQuestionnaireQuestion(db, req.params.id);
      if (!question) {
        res.status(404).json({ error: 'Вопрос не найден' });
        return;
      }
      res.json({ ok: true });
    })
  );

  router.get('/api/candidates', requireSystemAuth, (req, res) => {
    const candidates = listCandidates(db, {
      vacancy: req.query.vacancy,
      status: req.query.status,
      search: req.query.search,
      limit: req.query.limit,
      offset: req.query.offset
    });

    res.json({ candidates });
  });

  router.get('/api/candidates.csv', requireSystemAuth, (req, res) => {
    const candidates = listCandidates(db, {
      vacancy: req.query.vacancy,
      status: req.query.status,
      search: req.query.search,
      limit: 10000
    });

    res.header('Content-Type', 'text/csv; charset=utf-8');
    res.attachment('candidates.csv');
    res.send(toCsv(candidates));
  });

  router.get('/api/candidates/:id', requireSystemAuth, (req, res) => {
    const details = getCandidateDetails(db, req.params.id);
    if (!details) {
      res.status(404).json({ error: 'Кандидат не найден' });
      return;
    }
    res.json(details);
  });

  router.patch('/api/candidates/:id', requireSystemAuth, express.json(), (req, res) => {
    const details = updateAdminDecision(db, req.params.id, {
      adminStatus: req.body.adminStatus,
      note: req.body.note
    });

    if (!details) {
      res.status(404).json({ error: 'Кандидат не найден' });
      return;
    }

    res.json(details);
  });

  return router;
}

function asyncHandler(handler) {
  return (req, res, next) => {
    Promise.resolve(handler(req, res, next)).catch(next);
  };
}

function createRequireSystemAuth(config) {
  return asyncHandler(async (req, res, next) => {
    const systemSession = await getSystemSession(req, config);
    if (!systemSession.authenticated) {
      res.status(401).json({
        error: 'Требуется вход сотрудника UNICOM',
        loginUrl: buildLoginUrl(req, config),
        workspaces: buildWorkspaces(config)
      });
      return;
    }

    req.systemUser = systemSession.user;
    next();
  });
}

function createRequireSettingsAccess(config) {
  const requireSystemAuth = createRequireSystemAuth(config);
  return [
    requireSystemAuth,
    (req, res, next) => {
      const user = req.systemUser || {};
      const canManageSettings =
        user.role === 'superadmin' ||
        user.permissions?.settings === true ||
        user.permissions?.hr_settings === true;
      if (!canManageSettings) {
        res.status(403).json({ error: 'Недостаточно прав для настроек HR' });
        return;
      }
      next();
    }
  ];
}

function sanitizeSettingsInput(input) {
  return {
    botToken: cleanText(input.botToken),
    clearBotToken: Boolean(input.clearBotToken)
  };
}

function cleanText(value) {
  if (value === undefined || value === null) return '';
  return String(value).trim();
}

async function getSystemSession(req, config) {
  const endpoint = buildMarketUrl(config, '/admin/api/session');
  let response;

  try {
    response = await fetch(endpoint, {
      headers: {
        Accept: 'application/json',
        Cookie: req.headers.cookie || ''
      },
      redirect: 'manual'
    });
  } catch (error) {
    return {
      authenticated: false,
      error: `UNICOM Market недоступен: ${error.message}`
    };
  }

  if (response.status === 401 || response.status === 403) {
    return { authenticated: false };
  }

  if (!response.ok) {
    return {
      authenticated: false,
      error: `UNICOM Market вернул ${response.status}`
    };
  }

  const data = await response.json().catch(() => ({}));
  return {
    authenticated: Boolean(data.authenticated),
    user: data.user || null
  };
}

function buildLoginUrl(req, config) {
  const marketWorkspaceUrl = config.workspace.marketWorkspaceUrl || buildMarketUrl(config, '/admin');
  const loginUrl = new URL(
    `${marketWorkspaceUrl.replace(/\/+$/, '')}/login`,
    originFromRequest(req)
  );
  loginUrl.searchParams.set('next', config.workspace.hrWorkspaceUrl || originFromRequest(req));
  if (marketWorkspaceUrl.startsWith('/')) {
    return `${loginUrl.pathname}${loginUrl.search}`;
  }
  return loginUrl.toString();
}

function buildMarketUrl(config, path) {
  const baseUrl = config.workspace.marketBaseUrl.replace(/\/+$/, '');
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
}

function buildWorkspaces(config) {
  return {
    market: config.workspace.marketWorkspaceUrl || buildMarketUrl(config, '/admin'),
    hr: config.workspace.hrWorkspaceUrl || '/'
  };
}

function originFromRequest(req) {
  return `${req.protocol}://${req.get('host')}`;
}

function toCsv(candidates) {
  const headers = [
    'id',
    'telegram_user_id',
    'username',
    'name',
    'vacancy',
    'status',
    'fit_score',
    'phone',
    'answers',
    'result',
    'updated_at'
  ];

  const rows = candidates.map((candidate) => [
    candidate.id,
    candidate.telegramUserId,
    candidate.username,
    [candidate.firstName, candidate.lastName].filter(Boolean).join(' '),
    candidate.vacancyTitle || candidate.vacancySlug || '',
    candidate.status,
    candidate.fitScore,
    candidate.extracted?.phone || '',
    formatAnswersForCsv(candidate.extracted?.answers || []),
    candidate.summary,
    candidate.updatedAt
  ]);

  return [headers, ...rows].map((row) => row.map(csvCell).join(',')).join('\n');
}

function formatAnswersForCsv(answers) {
  return answers.map((answer) => `${answer.question}: ${answer.answer}`).join('\n');
}

function csvCell(value) {
  const text = String(value ?? '');
  return `"${text.replace(/"/g, '""')}"`;
}
