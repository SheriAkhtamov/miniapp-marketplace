import {
  ArrowLeft,
  ArrowDown,
  ArrowUp,
  BarChart3,
  Bot,
  BriefcaseBusiness,
  Check,
  CircleAlert,
  ClipboardList,
  Download,
  Eye,
  EyeOff,
  FileText,
  ListChecks,
  Loader2,
  LogOut,
  MessageSquareText,
  MessageCircle,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Trash2,
  UserRound,
  UsersRound,
  X
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const statusLabels = {
  new: 'Новый',
  screening: 'В процессе',
  qualified: 'Подходит',
  not_fit: 'Не подходит',
  needs_review: 'В обработке'
};

const statusOptions = [
  ['all', 'Все статусы'],
  ['new', 'Новые'],
  ['screening', 'В процессе'],
  ['needs_review', 'В обработке'],
  ['qualified', 'Подходит'],
  ['not_fit', 'Не подходит']
];

const appBasePath = import.meta.env.BASE_URL || '/';

function appUrl(path) {
  const base = appBasePath.endsWith('/') ? appBasePath : `${appBasePath}/`;
  const cleanPath = path.startsWith('/') ? path.slice(1) : path;
  return `${base}${cleanPath}`;
}

async function api(path, options = {}) {
  const response = await fetch(appUrl(path), {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    },
    ...options
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    const error = new Error(detail.error || `Request failed: ${response.status}`);
    error.status = response.status;
    error.detail = detail;
    throw error;
  }

  return response.json();
}

export default function App() {
  const [session, setSession] = useState({ loading: true, authenticated: false });

  useEffect(() => {
    api('/api/session')
      .then((data) => setSession({ loading: false, ...data }))
      .catch(() => setSession({ loading: false, authenticated: false }));
  }, []);

  if (session.loading) {
    return <FullPageLoader />;
  }

  if (!session.authenticated) {
    return <Login loginUrl={session.loginUrl} workspaces={session.workspaces} />;
  }

  return (
    <Dashboard
      workspaces={session.workspaces}
    />
  );
}

function Login({ loginUrl, workspaces }) {
  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="brand-lockup">
          <span className="brand-mark">
            <BriefcaseBusiness size={22} />
          </span>
          <div>
            <h1>UNICOM</h1>
            <p>HR отдел</p>
          </div>
        </div>

        <div className="login-title">
          <h2>Вход для сотрудников</h2>
          <p>HR workspace использует единый вход сотрудников UNICOM Market.</p>
        </div>

        <a className="primary-button login-link" href={loginUrl || workspaces?.market || '/admin/login'}>
          <ShieldCheck size={18} />
          Войти через UNICOM Market
        </a>
      </section>
    </main>
  );
}

function Dashboard({ workspaces }) {
  const [vacancies, setVacancies] = useState([]);
  const [stats, setStats] = useState(null);
  const [health, setHealth] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filters, setFilters] = useState({ vacancy: 'all', status: 'all', search: '' });
  const [activeView, setActiveView] = useState('dashboard');

  const loadVacancies = useCallback(async () => {
    const data = await api('/api/vacancies');
    setVacancies(data.vacancies || []);
    return data.vacancies || [];
  }, []);

  const loadDashboard = useCallback(async () => {
    const [statsData, healthData] = await Promise.all([
      api('/api/dashboard'),
      api('/health').catch(() => null)
    ]);
    setStats(statsData);
    setHealth(healthData);
  }, []);

  const loadCandidates = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    const candidateData = await api(`/api/candidates?${params}`);
    setCandidates(candidateData.candidates || []);
    const nextCandidates = candidateData.candidates || [];
    setSelectedId((current) =>
      current && nextCandidates.some((candidate) => candidate.id === current)
        ? current
        : nextCandidates[0]?.id || null
    );
    setLoading(false);
  }, [filters]);

  useEffect(() => {
    loadVacancies().catch(console.error);
  }, [loadVacancies]);

  useEffect(() => {
    loadDashboard().catch((error) => {
      console.error(error);
    });
  }, [loadDashboard]);

  useEffect(() => {
    loadCandidates().catch((error) => {
      console.error(error);
      setLoading(false);
    });
  }, [loadCandidates]);

  useEffect(() => {
    if (!selectedId) {
      setDetails(null);
      return;
    }
    api(`/api/candidates/${selectedId}`)
      .then(setDetails)
      .catch(() => setDetails(null));
  }, [selectedId]);

  async function logout() {
    const data = await api('/api/logout', { method: 'POST' }).catch(() => null);
    window.location.href = data?.logoutUrl || `${workspaces?.market || '/admin'}/logout`;
  }

  const viewTitle =
    activeView === 'dashboard'
      ? 'Дашборд'
      : activeView === 'questionnaire'
        ? 'Конструктор анкет'
      : activeView === 'settings'
        ? 'Настройки'
        : 'Кандидаты';

  async function refreshWorkspace() {
    setRefreshing(true);
    try {
      await Promise.all([
        loadDashboard(),
        loadVacancies(),
        activeView === 'candidates' ? loadCandidates() : Promise.resolve()
      ]);
    } finally {
      setRefreshing(false);
    }
  }

  function openCandidates(nextFilters = {}, candidateId = null) {
    setFilters((current) => ({ ...current, ...nextFilters }));
    setActiveView('candidates');
    setSelectedId(candidateId);
  }

  function handleVacancyCreated(vacancy) {
    setVacancies((current) =>
      [...current.filter((item) => item.slug !== vacancy.slug), vacancy]
        .sort((a, b) => a.title.localeCompare(b.title, 'ru'))
    );
    loadDashboard().catch(console.error);
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <span className="brand-mark">
            <BriefcaseBusiness size={22} />
          </span>
          <div>
            <h1>UNICOM</h1>
            <p>HR отдел</p>
          </div>
        </div>
        <nav className="sidebar-nav">
          <button
            className={activeView === 'dashboard' ? 'active' : ''}
            onClick={() => setActiveView('dashboard')}
            type="button"
          >
            <BarChart3 size={18} />
            Дашборд
          </button>
          <button
            className={activeView === 'candidates' ? 'active' : ''}
            onClick={() => setActiveView('candidates')}
            type="button"
          >
            <UsersRound size={18} />
            Кандидаты
          </button>
          <button
            className={activeView === 'questionnaire' ? 'active' : ''}
            onClick={() => setActiveView('questionnaire')}
            type="button"
          >
            <ClipboardList size={18} />
            Конструктор анкет
          </button>
          <button
            className={activeView === 'settings' ? 'active' : ''}
            onClick={() => setActiveView('settings')}
            type="button"
          >
            <Settings2 size={18} />
            Настройки
          </button>
        </nav>
        <button className="ghost-button sidebar-logout" onClick={logout}>
          <LogOut size={17} />
          Выйти
        </button>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h2>{viewTitle}</h2>
            <p>{new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}</p>
          </div>
          <div className="topbar-actions">
            <WorkspaceSwitcher workspaces={workspaces} />
            {activeView !== 'settings' ? (
              <button className="icon-button" onClick={refreshWorkspace} title="Обновить" disabled={refreshing}>
                <RefreshCw size={18} className={refreshing ? 'spin' : ''} />
              </button>
            ) : null}
          </div>
        </header>

        {activeView === 'dashboard' ? (
          <DashboardHome
            stats={stats}
            health={health}
            onOpenCandidates={openCandidates}
            onSelectCandidate={(candidate) => openCandidates({ status: 'all', vacancy: candidate.vacancySlug || 'all' }, candidate.id)}
            onOpenSettings={() => setActiveView('settings')}
          />
        ) : activeView === 'settings' ? (
          <SettingsPanel />
        ) : activeView === 'questionnaire' ? (
          <QuestionnaireBuilder vacancies={vacancies} onVacancyCreated={handleVacancyCreated} />
        ) : activeView === 'candidates' ? (
          <div className="content-grid">
            <section className="list-panel">
              <Filters
                vacancies={vacancies}
                filters={filters}
                resultCount={candidates.length}
                onExport={() => exportCsv(filters)}
                onChange={setFilters}
              />
              <CandidateTable
                candidates={candidates}
                loading={loading}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            </section>

            <DetailPanel
              details={details}
              candidate={details?.candidate}
              onSaved={(nextDetails) => {
                setDetails(nextDetails);
                loadCandidates();
                loadDashboard();
              }}
            />
          </div>
        ) : (
          <DashboardHome
            stats={stats}
            health={health}
            onOpenCandidates={openCandidates}
            onOpenSettings={() => setActiveView('settings')}
          />
        )}
      </section>
    </main>
  );
}

function WorkspaceSwitcher({ workspaces }) {
  return (
    <label className="workspace-switcher" aria-label="Переключить workspace">
      <select
        value="hr"
        onChange={(event) => {
          if (event.target.value === 'market') {
            window.location.href = workspaces?.market || '/admin';
          }
        }}
      >
        <option value="market">UNICOM Market</option>
        <option value="hr">UNICOM HR отдел</option>
      </select>
    </label>
  );
}

/* ── Dashboard Home ───────────────────────────────────────── */

function DashboardHome({ stats, health, onOpenCandidates, onSelectCandidate, onOpenSettings }) {
  const attentionCandidates = stats?.attentionCandidates || [];
  const vacancyFunnel = stats?.byVacancy || [];
  const botMissing = health && !health.botTokenConfigured;
  const hasCandidates = Boolean(stats?.total);

  return (
    <section className="dashboard-home fade-in">
      {botMissing ? (
        <div className="dashboard-alert">
          <CircleAlert size={20} />
          <div>
            <strong>Telegram-бот не подключен</strong>
            <span>Перейдите в Настройки, чтобы указать токен BotFather.</span>
          </div>
          <button className="secondary-button compact" type="button" onClick={onOpenSettings}>
            Открыть настройки
          </button>
        </div>
      ) : null}

      <StatsStrip stats={stats} />

      {!hasCandidates ? (
        <div className="empty-state dashboard-empty">
          <UsersRound size={34} />
          <p>Нет откликов. Распространите ссылку на вашего бота: @имя_бота.</p>
        </div>
      ) : null}

      <div className="dashboard-grid">
        <section className="dashboard-panel attention-panel">
          <div className="panel-head">
            <div>
              <h3>Требуют внимания</h3>
              <p>Кандидаты, которые ждут решения HR</p>
            </div>
            <button
              className="secondary-button compact"
              type="button"
              onClick={() => onOpenCandidates({ status: 'all', search: '' })}
            >
              Открыть все
            </button>
          </div>

          {attentionCandidates.length ? (
            <div className="attention-list">
              {attentionCandidates.map((candidate) => (
                <button
                  className="attention-card"
                  key={candidate.id}
                  type="button"
                  onClick={() => onSelectCandidate(candidate)}
                >
                  <span className="avatar">
                    <UserRound size={16} />
                  </span>
                  <span className="attention-main">
                    <strong>{displayName(candidate)}</strong>
                    <small>{candidate.vacancyTitle || 'Вакансия не выбрана'}</small>
                  </span>
                  <FitScoreBadge score={candidate.fitScore} />
                  <StatusBadge status={candidate.status} />
                </button>
              ))}
            </div>
          ) : (
            <div className="empty-state compact-empty">
              <Check size={28} />
              <p>Очередь проверки пуста</p>
            </div>
          )}
        </section>

        <section className="dashboard-panel funnel-panel">
          <div className="panel-head">
            <div>
              <h3>Воронка по вакансиям</h3>
              <p>Клик по вакансии откроет кандидатов с фильтром</p>
            </div>
          </div>

          <div className="vacancy-funnel-list">
            {vacancyFunnel.map((item) => (
              <button
                className="funnel-row"
                key={item.slug || item.title}
                type="button"
                onClick={() => onOpenCandidates({ vacancy: item.slug || 'all', status: 'all', search: '' })}
              >
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.count} кандидатов</small>
                </span>
                <span className="metric-chip">
                  <UsersRound size={14} />
                  {item.count}
                </span>
              </button>
            ))}
            {!vacancyFunnel.length ? (
              <div className="empty-state compact-empty">
                <BriefcaseBusiness size={28} />
                <p>Вакансии пока не найдены</p>
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </section>
  );
}

/* ── Vacancy Detail View ──────────────────────────────────── */

function VacancyDetailView({ vacancySlug, onBack }) {
  const [vacancy, setVacancy] = useState(null);
  const [activeTab, setActiveTab] = useState('questions');
  const [questions, setQuestions] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedCandidateId, setSelectedCandidateId] = useState(null);
  const [candidateDetails, setCandidateDetails] = useState(null);
  const [addingQuestion, setAddingQuestion] = useState(false);
  const [newQuestion, setNewQuestion] = useState(createEmptyQuestion);
  const [savingQuestion, setSavingQuestion] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(timer);
  }, [message]);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api(`/api/vacancies/${vacancySlug}`),
      api(`/api/questions?vacancy=${vacancySlug}`),
      api(`/api/candidates?vacancy=${vacancySlug}`)
    ]).then(([vacData, qData, cData]) => {
      setVacancy(vacData.vacancy);
      setQuestions(qData.questions || []);
      setCandidates(cData.candidates || []);
      setLoading(false);
    }).catch((error) => {
      console.error(error);
      setLoading(false);
    });
  }, [vacancySlug]);

  useEffect(() => {
    if (!selectedCandidateId) {
      setCandidateDetails(null);
      return;
    }
    api(`/api/candidates/${selectedCandidateId}`)
      .then(setCandidateDetails)
      .catch(() => setCandidateDetails(null));
  }, [selectedCandidateId]);

  async function createQuestion() {
    setSavingQuestion(true);
    setMessage(null);
    try {
      const payload = normalizeQuestionPayload(newQuestion);
      payload.vacancySlug = vacancySlug;
      const data = await api('/api/questions', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      setQuestions((current) => [...current, data.question]);
      setNewQuestion(createEmptyQuestion());
      setAddingQuestion(false);
      setMessage({ type: 'success', text: 'Вопрос добавлен' });
    } catch (error) {
      setMessage({ type: 'error', text: error.message || 'Не удалось добавить вопрос' });
    } finally {
      setSavingQuestion(false);
    }
  }

  function replaceQuestion(nextQuestion) {
    setQuestions((current) =>
      current.map((question) => (question.id === nextQuestion.id ? nextQuestion : question))
    );
    setMessage({ type: 'success', text: 'Вопрос сохранён' });
  }

  function removeQuestion(questionId) {
    setQuestions((current) => current.filter((question) => question.id !== questionId));
    setMessage({ type: 'success', text: 'Вопрос удалён' });
  }

  if (loading) {
    return (
      <div className="vacancy-detail fade-in">
        <div className="empty-state">
          <Loader2 size={24} className="spin" />
          <p>Загрузка вакансии...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="vacancy-detail fade-in">
      <div className="vacancy-detail-header">
        <div className="back-row">
          <button className="back-button" onClick={onBack} type="button">
            <ArrowLeft size={16} />
            Вакансии
          </button>
        </div>
        <h2>{vacancy?.title || vacancySlug}</h2>
        {vacancy?.description ? <p>{vacancy.description}</p> : null}
      </div>

      <div className="tab-bar">
        <button
          className={activeTab === 'questions' ? 'active' : ''}
          onClick={() => setActiveTab('questions')}
          type="button"
        >
          <ListChecks size={16} />
          Вопросы анкеты
          <span className="tab-count">{questions.length}</span>
        </button>
        <button
          className={activeTab === 'candidates' ? 'active' : ''}
          onClick={() => setActiveTab('candidates')}
          type="button"
        >
          <UsersRound size={16} />
          Кандидаты
          <span className="tab-count">{candidates.length}</span>
        </button>
      </div>

      <div className="vacancy-detail-content">
        {activeTab === 'questions' ? (
          <div className="vacancy-questions-section fade-in">
            {message ? (
              <div className={`settings-alert ${message.type}`}>
                {message.type === 'success' ? <Check size={17} /> : <CircleAlert size={17} />}
                <span>{message.text}</span>
              </div>
            ) : null}

            <section className="settings-panel questionnaire-panel">
              <div className="settings-panel-head">
                <span className="settings-panel-icon">
                  <ListChecks size={20} />
                </span>
                <div>
                  <h3>Вопросы анкеты</h3>
                  <p>{questions.length} вопросов для этой вакансии</p>
                </div>
              </div>
              <div className="question-list">
                {questions.map((question) => (
                  <QuestionEditor
                    key={question.id}
                    question={question}
                    onSaved={replaceQuestion}
                    onDeleted={removeQuestion}
                  />
                ))}
                {!questions.length ? (
                  <div className="empty-state">
                    <ListChecks size={32} />
                    <p>Пока нет вопросов для этой вакансии</p>
                  </div>
                ) : null}
                <button className="add-question-row" type="button" onClick={() => setAddingQuestion(true)}>
                  <Plus size={18} />
                  Добавить вопрос
                </button>
              </div>
            </section>
          </div>
        ) : (
          <div className="fade-in">
            {candidates.length ? (
              <div className="content-grid">
                <section className="list-panel">
                  <CandidateTable
                    candidates={candidates}
                    loading={false}
                    selectedId={selectedCandidateId}
                    onSelect={setSelectedCandidateId}
                  />
                </section>
                <DetailPanel
                  details={candidateDetails}
                  candidate={candidateDetails?.candidate}
                  onSaved={(nextDetails) => {
                    setCandidateDetails(nextDetails);
                    // Reload candidates for this vacancy
                    api(`/api/candidates?vacancy=${vacancySlug}`)
                      .then((data) => setCandidates(data.candidates || []))
                      .catch(() => {});
                  }}
                />
              </div>
            ) : (
              <div className="empty-state">
                <UsersRound size={32} />
                <p>Пока нет кандидатов на эту вакансию</p>
              </div>
            )}
          </div>
        )}
      </div>

      {addingQuestion ? (
        <QuestionCreateModal
          question={newQuestion}
          vacancyTitle={vacancy?.title || vacancySlug}
          saving={savingQuestion}
          onChange={setNewQuestion}
          onSubmit={createQuestion}
          onClose={() => {
            if (savingQuestion) return;
            setAddingQuestion(false);
            setNewQuestion(createEmptyQuestion());
          }}
        />
      ) : null}
    </div>
  );
}

/* ── Settings Panel ───────────────────────────────────────── */

function SettingsPanel() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] = useState(null);
  const [health, setHealth] = useState(null);
  const [form, setForm] = useState({ botToken: '' });
  const [message, setMessage] = useState(null);
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(timer);
  }, [message]);

  useEffect(() => {
    Promise.all([api('/api/settings'), api('/health').catch(() => null)])
      .then(([settingsData, healthData]) => {
        setSettings(settingsData.settings);
        setHealth(healthData);
        setForm({ botToken: '' });
      })
      .catch((error) => setMessage({ type: 'error', text: error.message }))
      .finally(() => setLoading(false));
  }, []);

  function updateForm(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function saveSettings() {
    setSaving(true);
    setMessage(null);
    try {
      const data = await api('/api/settings', {
        method: 'POST',
        body: JSON.stringify(form)
      });
      setSettings(data.settings);
      setHealth(data.bot ? { botEnabled: data.bot.running, botTokenConfigured: data.settings.botTokenConfigured } : health);
      setForm((current) => ({ ...current, botToken: '' }));
      setMessage({ type: 'success', text: 'Настройки сохранены' });
    } catch (error) {
      setMessage({ type: 'error', text: error.message || 'Не удалось сохранить настройки' });
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="empty-state">
        <Loader2 size={24} className="spin" />
        <p>Загрузка настроек...</p>
      </div>
    );
  }

  const botActive = settings?.botTokenConfigured && health?.botEnabled !== false;
  const lastUpdated = settings?.updatedAt ? formatDateTime(settings.updatedAt) : null;

  return (
    <section className="settings-workspace fade-in">
      {message ? (
        <div className={`settings-alert ${message.type}`}>
          {message.type === 'success' ? <Check size={17} /> : <CircleAlert size={17} />}
          <span>{message.text}</span>
        </div>
      ) : null}

      <div className="settings-page">
        <section className="settings-panel settings-main">
          <div className="settings-panel-head">
            <span className="settings-panel-icon">
              <Bot size={20} />
            </span>
            <div>
              <h3>Подключение Telegram бота</h3>
              <p>Настройте бота для приема анкет от кандидатов</p>
            </div>
          </div>

          <div className={`bot-status ${botActive ? 'active' : 'inactive'}`}>
            <span />
            {botActive ? 'Бот активен и принимает анкеты' : 'Бот не настроен'}
          </div>

          <div className="settings-instructions">
            <h4>Как настроить</h4>
            <ol>
              <li>Откройте <strong>@BotFather</strong> в Telegram</li>
              <li>Создайте бота командой <code>/newbot</code></li>
              <li>Скопируйте полученный токен</li>
              <li>Вставьте токен в поле ниже и сохраните</li>
            </ol>
          </div>

          <label className="settings-token-field">
            Токен бота
            <div className="token-input-row">
              <input
                type={showToken ? 'text' : 'password'}
                autoComplete="new-password"
                placeholder={settings?.botTokenConfigured ? 'Оставьте пустым, чтобы не менять' : '1234567890:ABCdefGHIjklMNOpqrsTUVwxyz'}
                value={form.botToken}
                onChange={(event) => updateForm('botToken', event.target.value)}
              />
              <button
                type="button"
                className="icon-button token-toggle"
                onClick={() => setShowToken((current) => !current)}
                title={showToken ? 'Скрыть токен' : 'Показать токен'}
              >
                {showToken ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
          </label>

          <div className="settings-save-row">
            <button className="primary-button" onClick={saveSettings} disabled={saving || !form.botToken.trim()}>
              {saving ? <Loader2 size={17} className="spin" /> : <Check size={17} />}
              Сохранить настройки
            </button>
          </div>

          {lastUpdated ? (
            <span className="settings-cache-line">Последнее обновление: {lastUpdated}</span>
          ) : null}
        </section>

        <aside className="settings-sidebar">
          <div className="settings-info-card">
            <h4>Что делает бот?</h4>
            <p>Бот общается с кандидатами в Telegram, задает вопросы анкеты и отправляет результаты в HR workspace.</p>
          </div>
          <div className="settings-info-card">
            <h4>Безопасность</h4>
            <p>Токен хранится на сервере и никогда не отображается в открытом виде. Токен передается по защищенному соединению.</p>
          </div>
          {botActive ? (
            <div className="settings-info-card success-card">
              <h4>Все готово</h4>
              <p>Бот работает. Распространите ссылку на бота среди кандидатов.</p>
            </div>
          ) : (
            <div className="settings-info-card warning-card">
              <h4>Требуется действие</h4>
              <p>Бот не может принимать анкеты, пока токен не будет настроен.</p>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

/* ── Questionnaire Builder ───────────────────────────────── */

function QuestionnaireBuilder({ vacancies, onVacancyCreated }) {
  const [selectedScenarioId, setSelectedScenarioId] = useState('');
  const [questionMap, setQuestionMap] = useState({});
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [addingVacancy, setAddingVacancy] = useState(false);
  const [savingVacancy, setSavingVacancy] = useState(false);
  const [savingQuestion, setSavingQuestion] = useState(false);
  const [newQuestion, setNewQuestion] = useState(createEmptyQuestion);
  const [newVacancy, setNewVacancy] = useState(createEmptyVacancy);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(timer);
  }, [message]);

  const scenarios = useMemo(() => {
    return vacancies.map((vacancy) => ({
      id: vacancy.slug,
      title: vacancy.title,
      subtitle: vacancy.description || 'Вопросы этой вакансии',
      vacancySlug: vacancy.slug
    }));
  }, [vacancies]);

  const selectedScenario = scenarios.find((scenario) => scenario.id === selectedScenarioId) || null;
  const questions = selectedScenario ? questionMap[selectedScenario.id] || [] : [];

  const loadQuestions = useCallback(async () => {
    if (!scenarios.length) {
      setQuestionMap({});
      setLoading(false);
      return;
    }

    setLoading(true);
    const entries = await Promise.all(
      scenarios.map((scenario) =>
        api(`/api/questions?vacancy=${encodeURIComponent(scenario.id)}`)
          .then((data) => [scenario.id, data.questions || []])
          .catch(() => [scenario.id, []])
      )
    );
    setQuestionMap(Object.fromEntries(entries));
    setLoading(false);
  }, [scenarios]);

  useEffect(() => {
    if (selectedScenarioId && scenarios.some((scenario) => scenario.id === selectedScenarioId)) {
      return;
    }
    setSelectedScenarioId(scenarios[0]?.id || '');
  }, [scenarios, selectedScenarioId]);

  useEffect(() => {
    loadQuestions().catch((error) => {
      console.error(error);
      setLoading(false);
    });
  }, [loadQuestions]);

  async function createVacancy() {
    setSavingVacancy(true);
    setMessage(null);
    try {
      const data = await api('/api/vacancies', {
        method: 'POST',
        body: JSON.stringify(newVacancy)
      });
      onVacancyCreated(data.vacancy);
      setQuestionMap((current) => ({ ...current, [data.vacancy.slug]: [] }));
      setSelectedScenarioId(data.vacancy.slug);
      setNewVacancy(createEmptyVacancy());
      setAddingVacancy(false);
      setMessage({ type: 'success', text: 'Вакансия добавлена' });
    } catch (error) {
      setMessage({ type: 'error', text: error.message || 'Не удалось добавить вакансию' });
    } finally {
      setSavingVacancy(false);
    }
  }

  async function createQuestion() {
    if (!selectedScenario) {
      setMessage({ type: 'error', text: 'Сначала создайте или выберите вакансию' });
      return;
    }

    setSavingQuestion(true);
    setMessage(null);
    try {
      const payload = normalizeQuestionPayload(newQuestion);
      payload.vacancySlug = selectedScenario.vacancySlug;
      const data = await api('/api/questions', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      setQuestionMap((current) => ({
        ...current,
        [selectedScenarioId]: [...(current[selectedScenarioId] || []), data.question]
      }));
      setNewQuestion(createEmptyQuestion());
      setAdding(false);
      setMessage({ type: 'success', text: 'Вопрос добавлен' });
    } catch (error) {
      setMessage({ type: 'error', text: error.message || 'Не удалось добавить вопрос' });
    } finally {
      setSavingQuestion(false);
    }
  }

  function replaceQuestion(nextQuestion) {
    setQuestionMap((current) => ({
      ...current,
      [selectedScenarioId]: (current[selectedScenarioId] || []).map((question) =>
        question.id === nextQuestion.id ? nextQuestion : question
      )
    }));
    setMessage({ type: 'success', text: 'Вопрос сохранён' });
  }

  function removeQuestion(questionId) {
    setQuestionMap((current) => ({
      ...current,
      [selectedScenarioId]: (current[selectedScenarioId] || []).filter((question) => question.id !== questionId)
    }));
    setMessage({ type: 'success', text: 'Вопрос удалён' });
  }

  async function moveQuestion(question, direction) {
    const currentQuestions = questionMap[selectedScenarioId] || [];
    const index = currentQuestions.findIndex((item) => item.id === question.id);
    const swapIndex = direction === 'up' ? index - 1 : index + 1;
    if (index < 0 || swapIndex < 0 || swapIndex >= currentQuestions.length) return;

    const neighbor = currentQuestions[swapIndex];
    const nextOrder = neighbor.sortOrder;
    const neighborOrder = question.sortOrder;

    const optimistic = [...currentQuestions];
    optimistic[index] = { ...neighbor, sortOrder: neighborOrder };
    optimistic[swapIndex] = { ...question, sortOrder: nextOrder };
    setQuestionMap((current) => ({
      ...current,
      [selectedScenarioId]: optimistic.sort(sortByQuestionOrder)
    }));

    try {
      const [updatedQuestion, updatedNeighbor] = await Promise.all([
        api(`/api/questions/${question.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ sortOrder: nextOrder })
        }),
        api(`/api/questions/${neighbor.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ sortOrder: neighborOrder })
        })
      ]);
      setQuestionMap((current) => ({
        ...current,
        [selectedScenarioId]: (current[selectedScenarioId] || []).map((item) => {
          if (item.id === question.id) return updatedQuestion.question;
          if (item.id === neighbor.id) return updatedNeighbor.question;
          return item;
        }).sort(sortByQuestionOrder)
      }));
    } catch (error) {
      setMessage({ type: 'error', text: error.message || 'Не удалось изменить порядок' });
      loadQuestions().catch(console.error);
    }
  }

  return (
    <section className="questionnaire-builder fade-in">
      <aside className="scenario-list">
        <div className="scenario-list-head">
          <div>
            <h3>Вакансии</h3>
            <p>Вопросы создаются только внутри вакансии</p>
          </div>
          <button className="icon-button" type="button" onClick={() => setAddingVacancy(true)} title="Добавить вакансию">
            <Plus size={17} />
          </button>
        </div>

        {scenarios.map((scenario) => (
          <button
            className={selectedScenarioId === scenario.id ? 'active' : ''}
            key={scenario.id}
            type="button"
            onClick={() => {
              setSelectedScenarioId(scenario.id);
              setAdding(false);
              setNewQuestion(createEmptyQuestion());
            }}
          >
            <span>
              <strong>{scenario.title}</strong>
              <small>{scenario.subtitle}</small>
            </span>
            <span className="scenario-count">{questionMap[scenario.id]?.length || 0}</span>
          </button>
        ))}

        {!scenarios.length ? (
          <div className="empty-state compact-empty">
            <BriefcaseBusiness size={28} />
            <p>Вакансий пока нет. Создайте первую вакансию, чтобы добавить вопросы.</p>
          </div>
        ) : null}
      </aside>

      <section className="questionnaire-editor">
        <div className="questionnaire-editor-head">
          <div>
            <h3>{selectedScenario?.title || 'Выберите вакансию'}</h3>
            <p>
              {selectedScenario
                ? 'Эти вопросы бот задаст только кандидатам выбранной вакансии'
                : 'Создайте вакансию слева, затем добавьте вопросы'}
            </p>
          </div>
          {selectedScenario ? (
            <span className="metric-chip">
              <ListChecks size={14} />
              {questions.length} вопросов
            </span>
          ) : null}
        </div>

        {message ? (
          <div className={`settings-alert ${message.type}`}>
            {message.type === 'success' ? <Check size={17} /> : <CircleAlert size={17} />}
            <span>{message.text}</span>
          </div>
        ) : null}

        {!selectedScenario ? (
          <div className="empty-state">
            <BriefcaseBusiness size={34} />
            <p>Нет выбранной вакансии. Создайте вакансию и настройте ее вопросы.</p>
          </div>
        ) : loading ? (
          <div className="empty-state">
            <Loader2 size={24} className="spin" />
            <p>Загрузка вопросов...</p>
          </div>
        ) : (
          <div className="question-list builder-question-list">
            {questions.map((question, index) => (
              <QuestionEditor
                key={question.id}
                question={question}
                onSaved={replaceQuestion}
                onDeleted={removeQuestion}
                onMoveUp={() => moveQuestion(question, 'up')}
                onMoveDown={() => moveQuestion(question, 'down')}
                disableMoveUp={index === 0}
                disableMoveDown={index === questions.length - 1}
              />
            ))}
            {!questions.length ? (
              <div className="empty-state compact-empty">
                <ListChecks size={30} />
                <p>В этой вакансии пока нет вопросов</p>
              </div>
            ) : null}

            <button className="add-question-row" type="button" onClick={() => setAdding(true)}>
              <Plus size={18} />
              Добавить вопрос
            </button>
          </div>
        )}
      </section>

      {adding && selectedScenario ? (
        <QuestionCreateModal
          question={newQuestion}
          vacancyTitle={selectedScenario.title}
          saving={savingQuestion}
          onChange={setNewQuestion}
          onSubmit={createQuestion}
          onClose={() => {
            if (savingQuestion) return;
            setAdding(false);
            setNewQuestion(createEmptyQuestion());
          }}
        />
      ) : null}

      {addingVacancy ? (
        <VacancyCreateModal
          vacancy={newVacancy}
          saving={savingVacancy}
          onChange={setNewVacancy}
          onSubmit={createVacancy}
          onClose={() => {
            if (savingVacancy) return;
            setAddingVacancy(false);
            setNewVacancy(createEmptyVacancy());
          }}
        />
      ) : null}
    </section>
  );
}

function useModalDismiss(onClose) {
  const dialogRef = useRef(null);

  useEffect(() => {
    function onKey(event) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    const node = dialogRef.current;
    const focusTarget = node?.querySelector('input, textarea, select, button') || node;
    focusTarget?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return dialogRef;
}

function VacancyCreateModal({ vacancy, saving, onChange, onSubmit, onClose }) {
  const dialogRef = useModalDismiss(onClose);
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="question-modal vacancy-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="vacancy-modal-title"
        tabIndex={-1}
        ref={dialogRef}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <h3 id="vacancy-modal-title">Новая вакансия</h3>
            <p>После создания здесь можно будет добавить вопросы</p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} disabled={saving} title="Закрыть">
            <X size={18} />
          </button>
        </div>

        <div className="vacancy-form">
          <label>
            Название вакансии
            <input
              value={vacancy.title}
              onChange={(event) => onChange((current) => ({ ...current, title: event.target.value }))}
              placeholder="Например: Курьер"
            />
          </label>
          <label>
            Описание
            <textarea
              value={vacancy.description}
              onChange={(event) => onChange((current) => ({ ...current, description: event.target.value }))}
              placeholder="Коротко: требования, график, зарплата"
            />
          </label>
        </div>

        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose} disabled={saving}>
            Отмена
          </button>
          <button
            className="primary-button"
            type="button"
            onClick={onSubmit}
            disabled={saving || !vacancy.title.trim()}
          >
            {saving ? <Loader2 size={16} className="spin" /> : <Check size={16} />}
            Создать вакансию
          </button>
        </div>
      </section>
    </div>
  );
}

function QuestionCreateModal({ question, vacancyTitle, saving, onChange, onSubmit, onClose }) {
  const dialogRef = useModalDismiss(onClose);
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="question-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="question-modal-title"
        tabIndex={-1}
        ref={dialogRef}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <h3 id="question-modal-title">Новый вопрос</h3>
            <p>Для вакансии: {vacancyTitle}</p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} disabled={saving} title="Закрыть">
            <X size={18} />
          </button>
        </div>

        <div className="modal-type-row">
          <QuestionTypeBadge question={question} />
        </div>

        <QuestionForm
          question={question}
          onChange={onChange}
          onSubmit={onSubmit}
          saving={saving}
          submitLabel="Добавить вопрос"
        />
      </section>
    </div>
  );
}

/* ── Question Editor ──────────────────────────────────────── */

function QuestionEditor({
  question,
  onSaved,
  onDeleted,
  onMoveUp,
  onMoveDown,
  disableMoveUp = true,
  disableMoveDown = true
}) {
  const [draft, setDraft] = useState(question);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(question);
  }, [question]);

  async function saveQuestion() {
    setSaving(true);
    try {
      const data = await api(`/api/questions/${question.id}`, {
        method: 'PATCH',
        body: JSON.stringify(normalizeQuestionPayload(draft))
      });
      onSaved(data.question);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  async function deleteQuestion() {
    const confirmed = window.confirm('Удалить вопрос? Это не повлияет на старые анкеты, но новым кандидатам он задаваться не будет.');
    if (!confirmed) return;
    setSaving(true);
    try {
      await api(`/api/questions/${question.id}`, { method: 'DELETE' });
      onDeleted(question.id);
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="question-list-item">
      <div className="question-list-main">
        <div>
          <strong>{question.textRu}</strong>
          <div className="question-list-meta">
            <QuestionTypeBadge question={question} />
            <span>{question.type === 'single_choice' ? `${question.options?.length || 0} вариантов` : 'Свободный текст'}</span>
          </div>
        </div>
        {question.textUz ? <small>{question.textUz}</small> : null}
      </div>

      <div className="question-list-actions">
        {onMoveUp || onMoveDown ? (
          <div className="question-order-actions" aria-label="Изменить порядок вопроса">
            <button className="icon-button" type="button" onClick={onMoveUp} disabled={disableMoveUp || saving} title="Выше">
              <ArrowUp size={16} />
            </button>
            <button className="icon-button" type="button" onClick={onMoveDown} disabled={disableMoveDown || saving} title="Ниже">
              <ArrowDown size={16} />
            </button>
          </div>
        ) : null}

        <button className="secondary-button compact" type="button" onClick={() => setEditing(true)} disabled={saving}>
          Редактировать
        </button>
        <button className="icon-button danger" type="button" onClick={deleteQuestion} disabled={saving} title="Удалить вопрос">
          {saving ? <Loader2 size={16} className="spin" /> : <Trash2 size={16} />}
        </button>
      </div>

      {editing ? (
        <QuestionEditModal
          question={draft}
          saving={saving}
          onChange={setDraft}
          onSubmit={saveQuestion}
          onClose={() => {
            if (saving) return;
            setDraft(question);
            setEditing(false);
          }}
        />
      ) : null}
    </article>
  );
}

function QuestionEditModal({ question, saving, onChange, onSubmit, onClose }) {
  const dialogRef = useModalDismiss(onClose);
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="question-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="question-edit-modal-title"
        tabIndex={-1}
        ref={dialogRef}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <h3 id="question-edit-modal-title">Редактировать вопрос</h3>
            <p>Изменения применятся к новым прохождениям анкеты</p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} disabled={saving} title="Закрыть">
            <X size={18} />
          </button>
        </div>

        <div className="modal-type-row">
          <QuestionTypeBadge question={question} />
        </div>

        <QuestionForm
          question={question}
          onChange={onChange}
          onSubmit={onSubmit}
          saving={saving}
          submitLabel="Сохранить"
        />
      </section>
    </div>
  );
}

/* ── Question Form ────────────────────────────────────────── */

function QuestionForm({ question, onChange, onSubmit, onDelete, saving, submitLabel }) {
  const canSave = canSaveQuestion(question);

  function updateField(field, value) {
    onChange({ ...question, [field]: value });
  }

  function updateType(type) {
    onChange({
      ...question,
      type,
      options: type === 'single_choice' && !question.options?.length
        ? [createOption('Да', 'Ha', true), createOption('Нет', "Yo'q", false)]
        : type === 'text' ? [] : question.options || []
    });
  }

  function updateOption(optionId, field, value) {
    onChange({
      ...question,
      options: (question.options || []).map((option) =>
        option.id === optionId ? { ...option, [field]: value } : option
      )
    });
  }

  function addOption() {
    onChange({
      ...question,
      options: [...(question.options || []), createOption()]
    });
  }

  function removeOption(optionId) {
    onChange({
      ...question,
      options: (question.options || []).filter((option) => option.id !== optionId)
    });
  }

  return (
    <div className="question-form">
      <div className="settings-form-grid">
        <label>
          Вопрос RU
          <input
            value={question.textRu}
            onChange={(event) => updateField('textRu', event.target.value)}
            placeholder="Например: Фамилия, имя, отчество"
          />
        </label>
        <label>
          Вопрос UZ
          <input
            value={question.textUz}
            onChange={(event) => updateField('textUz', event.target.value)}
            placeholder="Ixtiyoriy tarjima"
          />
        </label>
        <label>
          Тип ответа
          <select value={question.type} onChange={(event) => updateType(event.target.value)}>
            <option value="text">Письменный ответ</option>
            <option value="single_choice">Готовые ответы</option>
          </select>
        </label>
      </div>

      {question.type === 'single_choice' ? (
        <div className="option-list">
          {(question.options || []).map((option) => (
            <div className="option-row" key={option.id}>
              <input
                value={option.labelRu}
                onChange={(event) => updateOption(option.id, 'labelRu', event.target.value)}
                placeholder="Ответ RU"
              />
              <input
                value={option.labelUz}
                onChange={(event) => updateOption(option.id, 'labelUz', event.target.value)}
                placeholder="Ответ UZ"
              />
              <label className="option-pass">
                <input
                  type="checkbox"
                  checked={Boolean(option.passes)}
                  onChange={(event) => updateOption(option.id, 'passes', event.target.checked)}
                />
                Проходит
              </label>
              <button className="icon-button" type="button" onClick={() => removeOption(option.id)} title="Удалить ответ">
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          <button className="secondary-button compact" type="button" onClick={addOption}>
            <Plus size={16} />
            Ответ
          </button>
        </div>
      ) : null}

      <div className="question-actions">
        {onDelete ? (
          <button className="ghost-button compact" type="button" onClick={onDelete} disabled={saving}>
            <Trash2 size={16} />
            Удалить
          </button>
        ) : null}
        <button className="primary-button compact" type="button" onClick={onSubmit} disabled={saving || !canSave}>
          {saving ? <Loader2 size={16} className="spin" /> : <Check size={16} />}
          {submitLabel}
        </button>
      </div>
    </div>
  );
}

/* ── Stats Strip ──────────────────────────────────────────── */

function StatsStrip({ stats }) {
  const byStatus = useMemo(() => {
    const map = new Map((stats?.byStatus || []).map((item) => [item.status, item.count]));
    const newToday = stats?.newToday || 0;
    return {
      total: stats?.total || 0,
      reviewLabel: newToday ? 'Новых за сегодня' : 'Необработанных',
      reviewValue: newToday || stats?.unprocessed || 0,
      qualified: map.get('qualified') || 0,
      notFit: map.get('not_fit') || 0
    };
  }, [stats]);

  return (
    <section className="stats-strip">
      <Stat icon={<UsersRound size={18} />} label="Всего кандидатов" value={byStatus.total} />
      <Stat icon={<CircleAlert size={18} />} label={byStatus.reviewLabel} value={byStatus.reviewValue} tone="warn" />
      <Stat icon={<Check size={18} />} label="Подходит" value={byStatus.qualified} tone="good" />
      <Stat icon={<X size={18} />} label="Не подходит" value={byStatus.notFit} tone="bad" />
    </section>
  );
}

function Stat({ icon, label, value, tone = 'neutral' }) {
  return (
    <div className={`stat ${tone}`}>
      <span>{icon}</span>
      <div>
        <strong>{value}</strong>
        <small>{label}</small>
      </div>
    </div>
  );
}

/* ── Filters ──────────────────────────────────────────────── */

function Filters({ vacancies, filters, resultCount, onExport, onChange }) {
  const [searchInput, setSearchInput] = useState(filters.search || '');

  useEffect(() => {
    setSearchInput(filters.search || '');
  }, [filters.search]);

  useEffect(() => {
    const nextSearch = filters.search || '';
    if (searchInput === nextSearch) return;
    const timer = setTimeout(() => {
      onChange({ ...filters, search: searchInput });
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput, filters, onChange]);

  return (
    <div className="filters">
      <div className="search-box">
        <Search size={17} />
        <input
          placeholder="Поиск"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
        />
      </div>
      <select
        value={filters.vacancy}
        onChange={(event) => onChange({ ...filters, vacancy: event.target.value })}
      >
        <option value="all">Все вакансии</option>
        {vacancies.map((vacancy) => (
          <option key={vacancy.slug} value={vacancy.slug}>
            {vacancy.title}
          </option>
        ))}
      </select>
      <select
        value={filters.status}
        onChange={(event) => onChange({ ...filters, status: event.target.value })}
      >
        {statusOptions.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <button className="secondary-button export-button" type="button" onClick={onExport}>
        <Download size={17} />
        Скачать ({resultCount})
      </button>
    </div>
  );
}

/* ── Vacancy Board ────────────────────────────────────────── */

function VacancyBoard({ vacancies, stats, onOpen }) {
  const vacancyCounts = useMemo(() => {
    return new Map((stats?.byVacancy || []).map((item) => [item.title, item.count]));
  }, [stats]);

  const [questionCounts, setQuestionCounts] = useState({});

  useEffect(() => {
    // Load question counts for each vacancy
    Promise.all(
      vacancies.map((vacancy) =>
        api(`/api/questions?vacancy=${vacancy.slug}`)
          .then((data) => ({ slug: vacancy.slug, count: (data.questions || []).length }))
          .catch(() => ({ slug: vacancy.slug, count: 0 }))
      )
    ).then((results) => {
      const counts = {};
      results.forEach((r) => { counts[r.slug] = r.count; });
      setQuestionCounts(counts);
    });
  }, [vacancies]);

  if (!vacancies.length) {
    return (
      <div className="empty-state fade-in">
        <BriefcaseBusiness size={32} />
        <p>Пока нет вакансий</p>
      </div>
    );
  }

  return (
    <section className="vacancy-board fade-in">
      {vacancies.map((vacancy) => (
        <article
          className="vacancy-card"
          key={vacancy.slug}
          onClick={() => onOpen(vacancy.slug)}
        >
          <div className="vacancy-card-header">
            <div>
              <h3>{vacancy.title}</h3>
              <p>{vacancy.description}</p>
            </div>
          </div>
          <div className="vacancy-card-footer">
            <div className="vacancy-card-badges">
              <span className="metric-chip">
                <UsersRound size={14} />
                {vacancyCounts.get(vacancy.title) || 0} кандидатов
              </span>
              <span className="question-count-badge">
                <ListChecks size={14} />
                {questionCounts[vacancy.slug] ?? '…'} вопросов
              </span>
            </div>
            <ChevronRight size={18} color="var(--admin-muted)" />
          </div>
        </article>
      ))}
    </section>
  );
}

/* ── Candidate Table ──────────────────────────────────────── */

function CandidateTable({ candidates, loading, selectedId, onSelect }) {
  if (!candidates.length && loading) {
    return (
      <div className="empty-state">
        <Loader2 size={24} className="spin" />
        <p>Загрузка...</p>
      </div>
    );
  }

  if (!candidates.length) {
    return (
      <div className="empty-state">
        <UsersRound size={32} />
        <p>Нет откликов. Распространите ссылку на вашего бота: @имя_бота.</p>
      </div>
    );
  }

  return (
    <div className="candidate-list">
      {candidates.map((candidate) => (
        <button
          key={candidate.id}
          className={`candidate-card ${selectedId === candidate.id ? 'selected' : ''}`}
          onClick={() => onSelect(candidate.id)}
          type="button"
        >
          <span className="candidate-card-main">
            <span className="avatar">
              <UserRound size={16} />
            </span>
            <span>
              <strong>{displayName(candidate)}</strong>
              <small>{candidate.username ? `@${candidate.username}` : candidate.telegramUserId}</small>
            </span>
          </span>
          <span className="candidate-card-meta">
            <span>{candidate.vacancyTitle || 'Вакансия не выбрана'}</span>
            <FactLine candidate={candidate} />
          </span>
          <span className="candidate-card-badges">
            <FitScoreBadge score={candidate.fitScore} />
            <StatusBadge status={candidate.status} />
          </span>
        </button>
      ))}
    </div>
  );
}

/* ── Detail Panel ─────────────────────────────────────────── */

function DetailPanel({ details, candidate, onSaved }) {
  const [activeTab, setActiveTab] = useState('analysis');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setActiveTab('analysis');
    setNote('');
  }, [candidate?.id]);

  if (!candidate) {
    return (
      <aside className="detail-panel empty-detail">
        <MessageSquareText size={24} />
        <p>Выберите кандидата</p>
      </aside>
    );
  }

  async function saveDecision(nextStatus) {
    if (nextStatus === 'not_fit') {
      const confirmed = window.confirm('Уверены? Кандидату в будущем будет отказано');
      if (!confirmed) return;
    }
    setSaving(true);
    try {
      const nextDetails = await api(`/api/candidates/${candidate.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ adminStatus: nextStatus, note })
      });
      onSaved(nextDetails);
      setNote('');
    } finally {
      setSaving(false);
    }
  }

  return (
    <aside className="detail-panel">
      <div className="detail-header">
        <div>
          <h3>{displayName(candidate)}</h3>
          <p>{candidate.vacancyTitle || details?.vacancy?.title || 'Вакансия не выбрана'}</p>
        </div>
        <div className="detail-header-badges">
          <FitScoreBadge score={candidate.fitScore} />
          <StatusBadge status={candidate.status} />
        </div>
      </div>

      <div className="detail-tab-bar" role="tablist" aria-label="Данные кандидата">
        <button
          className={activeTab === 'analysis' ? 'active' : ''}
          onClick={() => setActiveTab('analysis')}
          type="button"
        >
          <BarChart3 size={16} />
          Анализ анкеты
        </button>
        <button
          className={activeTab === 'questionnaire' ? 'active' : ''}
          onClick={() => setActiveTab('questionnaire')}
          type="button"
        >
          <FileText size={16} />
          Анкета
        </button>
        <button
          className={activeTab === 'chat' ? 'active' : ''}
          onClick={() => setActiveTab('chat')}
          type="button"
        >
          <MessageCircle size={16} />
          Чат с ботом
        </button>
      </div>

      <div className="detail-tab-content">
        {activeTab === 'analysis' ? (
          <div className="detail-tab-pane fade-in">
            <section className="summary-card">
              <h4>Краткий вывод</h4>
              <p>{candidate.summary || 'Краткий вывод по анкете пока не сформирован.'}</p>
            </section>

            <section className="detail-section">
              <h4>Совпадение по критериям</h4>
              <div className="criteria-list">
                {(candidate.criteria || []).map((item) => (
                  <div className="criterion compact" key={item.key}>
                    <span className={`criterion-state ${criterionTone(item.met)}`}>
                      {criterionIcon(item.met)}
                    </span>
                    <div>
                      <strong>{item.label}</strong>
                      <small>{item.evidence}</small>
                    </div>
                  </div>
                ))}
                {!candidate.criteria?.length ? <p className="summary">Критерии не заданы</p> : null}
              </div>
            </section>

            {candidate.verdictReason ? (
              <section className="detail-section">
                <h4>Причина отказа / итог</h4>
                <p className="reason">{candidate.verdictReason}</p>
              </section>
            ) : null}
          </div>
        ) : null}

        {activeTab === 'questionnaire' ? (
          <div className="detail-tab-pane fade-in">
            <dl className="facts-grid questionnaire-facts">
              <Fact label="Telegram" value={formatTelegram(candidate)} wide />
              {(details?.answers || []).map((answer) => (
                <Fact
                  key={answer.id}
                  label={answer.questionText}
                  value={answer.answerText}
                  wide
                />
              ))}
              {!details?.answers?.length ? <Fact label="Ответы" value="Нет данных" wide /> : null}
            </dl>
          </div>
        ) : null}

        {activeTab === 'chat' ? (
          <div className="detail-tab-pane fade-in">
            <div className="message-list full-height">
              {(details?.messages || []).map((message) => (
                <div className={`chat-message ${message.role}`} key={message.id}>
                  <small>{message.role === 'user' ? 'Кандидат' : message.role === 'assistant' ? 'Бот' : 'Система'}</small>
                  <p>{message.content}</p>
                </div>
              ))}
              {!details?.messages?.length ? (
                <div className="empty-state compact-empty">
                  <MessageSquareText size={28} />
                  <p>История чата пока пуста</p>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      <section className="decision-bar">
        <textarea
          placeholder="Заметка HR"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        <div className="decision-actions">
          <button
            className={`decision-button accept ${candidate.adminStatus === 'qualified' ? 'active' : ''}`}
            onClick={() => saveDecision('qualified')}
            disabled={saving}
            type="button"
          >
            {saving ? <Loader2 size={16} className="spin" /> : <Check size={16} />}
            Подходит
          </button>
          <button
            className={`decision-button reject ${candidate.adminStatus === 'not_fit' ? 'active' : ''}`}
            onClick={() => saveDecision('not_fit')}
            disabled={saving}
            type="button"
          >
            <X size={16} />
            Не подходит
          </button>
        </div>
      </section>
    </aside>
  );
}

/* ── Small Components ─────────────────────────────────────── */

function StatusBadge({ status }) {
  return <span className={`status-badge ${status}`}>{statusLabels[status] || status}</span>;
}

function FitScoreBadge({ score = 0 }) {
  return (
    <span className={`fit-score ${scoreTone(score)}`}>
      {Number(score || 0)}% совпадения
    </span>
  );
}

function QuestionTypeBadge({ question }) {
  const hasPassingOptions = question.type === 'single_choice' && (question.options || []).some((option) => option.passes);
  const isCriterion = hasPassingOptions;
  const isChoice = question.type === 'single_choice' && !isCriterion;
  return (
    <span className={`question-type-badge ${isCriterion ? 'criterion' : isChoice ? 'choice' : 'text'}`}>
      {isCriterion ? 'Обязательный критерий' : isChoice ? 'Варианты ответа' : 'Текстовый ответ'}
    </span>
  );
}

function FactLine({ candidate }) {
  const answerFacts = candidate.extracted?.answers || [];
  const facts = answerFacts.length
    ? answerFacts.slice(0, 2).map((item) => item.answer)
    : [
        candidate.extracted?.full_name,
        candidate.extracted?.phone
      ].filter(Boolean);

  return <span className="fact-line">{facts.length ? facts.join(' · ') : 'Нет данных'}</span>;
}

function Fact({ label, value, wide = false }) {
  return (
    <div className={wide ? 'wide' : ''}>
      <dt>{label}</dt>
      <dd>{value || 'Нет данных'}</dd>
    </div>
  );
}

function formatTelegram(candidate) {
  return candidate.username ? `@${candidate.username}` : candidate.telegramUserId;
}

function FullPageLoader() {
  return (
    <main className="login-page">
      <div className="empty-state">
        <Loader2 size={24} className="spin" />
        <p>Загрузка...</p>
      </div>
    </main>
  );
}

/* ── Helper Functions ─────────────────────────────────────── */

function displayName(candidate) {
  return (
    [candidate.firstName, candidate.lastName].filter(Boolean).join(' ') ||
    candidate.extracted?.full_name ||
    `Кандидат #${candidate.id}`
  );
}

function criterionTone(value) {
  if (value === true) return 'met';
  if (value === false) return 'failed';
  return 'unknown';
}

function scoreTone(score = 0) {
  if (score >= 75) return 'high';
  if (score >= 45) return 'medium';
  return 'low';
}

function sortByQuestionOrder(a, b) {
  return Number(a.sortOrder || 0) - Number(b.sortOrder || 0) || Number(a.id || 0) - Number(b.id || 0);
}

function criterionIcon(value) {
  if (value === true) return <Check size={14} />;
  if (value === false) return <X size={14} />;
  return <CircleAlert size={14} />;
}

function formatYears(value) {
  if (value === null || value === undefined || value === '') return '';
  return `${value} лет`;
}

function formatBoolean(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (
      ['false', '0', 'no', 'n', 'нет', 'yoq', "yo'q"].includes(normalized) ||
      normalized.includes('не подходит') ||
      normalized.includes('не соглас')
    ) {
      return 'Нет';
    }
    if (
      ['true', '1', 'yes', 'y', 'да', 'ha'].includes(normalized) ||
      normalized.includes('подходит') ||
      normalized.includes('соглас')
    ) {
      return 'Да';
    }
  }
  return value ? 'Да' : 'Нет';
}

function createEmptyQuestion() {
  return {
    textRu: '',
    textUz: '',
    type: 'text',
    isCriterion: false,
    options: []
  };
}

function createEmptyVacancy() {
  return {
    title: '',
    description: ''
  };
}

function createOption(labelRu = '', labelUz = '', passes = false) {
  return {
    id: `option-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    labelRu,
    labelUz,
    passes
  };
}

function normalizeQuestionPayload(question) {
  const options = question.type === 'single_choice'
    ? (question.options || [])
        .filter((option) => String(option.labelRu || '').trim())
        .map((option) => ({
          id: option.id,
          labelRu: String(option.labelRu || '').trim(),
          labelUz: String(option.labelUz || '').trim(),
          passes: Boolean(option.passes)
        }))
    : [];

  return {
    textRu: String(question.textRu || '').trim(),
    textUz: String(question.textUz || '').trim(),
    type: question.type,
    isCriterion: question.type === 'single_choice' && options.some((option) => option.passes),
    options
  };
}

function canSaveQuestion(question) {
  if (!String(question.textRu || '').trim()) return false;
  if (question.type !== 'single_choice') return true;
  const options = (question.options || []).filter((option) => String(option.labelRu || '').trim());
  return options.length > 0;
}

function formatDateTime(value) {
  if (!value) return '';
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  });
}

function exportCsv(filters) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const link = document.createElement('a');
  link.href = appUrl(`/api/candidates.csv?${params}`);
  link.download = 'candidates.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
}
