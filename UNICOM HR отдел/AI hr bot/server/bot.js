import { Markup, Telegraf } from 'telegraf';
import {
  addMessage,
  clearPendingVacancy,
  createOrGetCandidateForVacancy,
  getCandidateCurrentQuestion,
  getCandidateAnswers,
  getActiveCandidateByTelegramId,
  getCandidateByTelegramAndVacancy,
  getNextQuestionForCandidate,
  getPreviousAnsweredQuestion,
  getTelegramProfile,
  getVacancies,
  getVacancy,
  listQuestionsForCandidate,
  refreshCandidateQuestionnaireState,
  removeCandidateAnswer,
  saveQuestionnaireAnswer,
  setActiveCandidate,
  setCandidateCurrentQuestion,
  setPendingVacancy,
  setProfileLanguage,
  updateCandidateTelegramInfo,
  upsertTelegramProfile
} from './db.js';

const LANGUAGES = {
  ru: {
    buttons: ['Русский', '🇷🇺 Русский'],
    vacancies: 'Вакансии',
    changeLanguage: '🌐 Сменить язык',
    chooseLanguage: 'Выберите язык общения:',
    languageSaved: 'Язык выбран: Русский.',
    chooseVacancy: 'Выберите вакансию, на которую хотите откликнуться:',
    vacancyButtons: 'Список вакансий:',
    vacancyMissing: 'Вакансия не найдена.',
    needLanguage: 'Сначала выберите язык.',
    needVacancy: 'Сначала выберите вакансию:',
    alreadyAnswered: 'Вы уже отвечали на вопросы по этой вакансии. Хотите изменить ответы?',
    rewriteYes: 'Да, изменить ответы',
    rewriteNo: 'Нет, оставить как есть',
    keptAnswers: 'Хорошо, текущая анкета оставлена без изменений. Можно выбрать другую вакансию.',
    back: 'Вернуться назад',
    questionnaireEmpty: 'Анкета пока не настроена. Напишите HR или попробуйте позже.',
    chooseOption: 'Выберите один из вариантов кнопкой ниже.',
    noPreviousAnswer: 'Это первый вопрос. Возвращаться пока некуда.',
    returnedBack: 'Хорошо, можно изменить предыдущий ответ.',
    answersSubmitted: 'Спасибо! Анкета отправлена HR.',
    error: 'Произошла ошибка. Попробуйте ещё раз или дождитесь ответа HR.',
    vacancyTitles: {
      'office-manager': 'Офис менеджер',
      'sales-representative': 'Торговый представитель'
    }
  },
  uz: {
    buttons: ["O'zbekcha", "O‘zbekcha", '🇺🇿 O‘zbekcha', 'Узбекский'],
    vacancies: 'Vakansiyalar',
    changeLanguage: "🌐 Tilni o'zgartirish",
    chooseLanguage: 'Muloqot tilini tanlang:',
    languageSaved: "Til tanlandi: O'zbekcha.",
    chooseVacancy: 'Qaysi vakansiyaga ariza bermoqchisiz?',
    vacancyButtons: 'Vakansiyalar ro‘yxati:',
    vacancyMissing: 'Vakansiya topilmadi.',
    needLanguage: 'Avval muloqot tilini tanlang.',
    needVacancy: 'Avval vakansiyani tanlang:',
    alreadyAnswered: "Siz bu vakansiya bo'yicha savollarga allaqachon javob bergansiz. Javoblarni o'zgartirmoqchimisiz?",
    rewriteYes: "Ha, javoblarni o'zgartirish",
    rewriteNo: 'Yo‘q, avvalgisi qolsin',
    keptAnswers: 'Yaxshi, joriy anketa o‘zgarishsiz qoldi. Boshqa vakansiyani tanlashingiz mumkin.',
    back: 'Orqaga qaytish',
    questionnaireEmpty: "Anketa hali sozlanmagan. HR bilan bog'laning yoki keyinroq urinib ko'ring.",
    chooseOption: 'Quyidagi tugmalardan birini tanlang.',
    noPreviousAnswer: 'Bu birinchi savol. Hozircha orqaga qaytib bo‘lmaydi.',
    returnedBack: 'Yaxshi, oldingi javobni o‘zgartirishingiz mumkin.',
    answersSubmitted: 'Rahmat! Anketa HR bo‘limiga yuborildi.',
    error: 'Xatolik yuz berdi. Qayta urinib ko‘ring yoki HR javobini kuting.',
    vacancyTitles: {
      'office-manager': 'Ofis menejeri',
      'sales-representative': 'Savdo vakili'
    }
  }
};

export function createBot(db, config) {
  const token = config.telegram.botToken;
  if (!token) {
    console.warn('[bot] telegram.botToken is not set in config.json. Telegram bot is disabled.');
    return null;
  }

  const bot = new Telegraf(token);

  bot.start(async (ctx) => {
    upsertTelegramProfile(db, ctx.from);
    await askLanguage(ctx);
  });

  bot.command('vacancy', async (ctx) => {
    const profile = upsertTelegramProfile(db, ctx.from);
    if (!profile.preferredLanguage) {
      await askLanguage(ctx);
      return;
    }
    await sendVacancyPicker(ctx, db, profile.preferredLanguage);
  });

  bot.hears(languageButtonMatcher(), async (ctx) => {
    const language = resolveLanguageFromText(ctx.message.text);
    const profile = upsertTelegramProfile(db, ctx.from);
    setProfileLanguage(db, profile.telegramUserId, language);
    await ctx.reply(t(language).languageSaved, mainKeyboard(language));
    await sendVacancyPicker(ctx, db, language);
  });

  bot.hears(changeLanguageMatcher(), async (ctx) => {
    upsertTelegramProfile(db, ctx.from);
    await askLanguage(ctx);
  });

  bot.hears(vacanciesButtonMatcher(), async (ctx) => {
    const profile = upsertTelegramProfile(db, ctx.from);
    const language = profile.preferredLanguage || 'ru';
    if (!profile.preferredLanguage) {
      await askLanguage(ctx);
      return;
    }
    await sendVacancyPicker(ctx, db, language);
  });

  bot.action(/^vacancy:(.+)$/u, async (ctx) => {
    const vacancySlug = ctx.match[1];
    const profile = upsertTelegramProfile(db, ctx.from);
    const language = profile.preferredLanguage || 'ru';
    const vacancy = getVacancy(db, vacancySlug);

    if (!profile.preferredLanguage) {
      await ctx.answerCbQuery(t(language).needLanguage);
      await askLanguage(ctx);
      return;
    }

    if (!vacancy) {
      await ctx.answerCbQuery(t(language).vacancyMissing);
      return;
    }

    const existing = getCandidateByTelegramAndVacancy(db, profile.telegramUserId, vacancySlug);
    if (existing && hasCandidateAnswers(db, existing)) {
      setPendingVacancy(db, profile.telegramUserId, vacancySlug);
      await ctx.answerCbQuery(vacancyTitle(vacancy, language));
      await deleteCallbackMessage(ctx);
      await ctx.reply(t(language).alreadyAnswered, rewriteKeyboard(vacancySlug, language));
      return;
    }

    await ctx.answerCbQuery(vacancyTitle(vacancy, language));
    await deleteCallbackMessage(ctx);
    const candidate = createOrGetCandidateForVacancy(db, ctx.from, vacancySlug);
    addMessage(db, candidate.id, 'system', `Candidate selected vacancy: ${vacancyTitle(vacancy, language)}`);
    await startQuestionnaire(ctx, db, candidate);
  });

  bot.action(/^rewrite:(yes|no):(.+)$/u, async (ctx) => {
    const decision = ctx.match[1];
    const vacancySlug = ctx.match[2];
    const profile = upsertTelegramProfile(db, ctx.from);
    const language = profile.preferredLanguage || 'ru';
    const vacancy = getVacancy(db, vacancySlug);

    if (!vacancy || profile.pendingVacancySlug !== vacancySlug) {
      await ctx.answerCbQuery(t(language).vacancyMissing);
      return;
    }

    clearPendingVacancy(db, profile.telegramUserId);
    await ctx.answerCbQuery();

    if (decision === 'no') {
      await ctx.reply(t(language).keptAnswers, mainKeyboard(language));
      await sendVacancyPicker(ctx, db, language);
      return;
    }

    const candidate = createOrGetCandidateForVacancy(db, ctx.from, vacancySlug, { reset: true });
    addMessage(db, candidate.id, 'system', `Candidate restarted vacancy answers: ${vacancyTitle(vacancy, language)}`);
    await startQuestionnaire(ctx, db, candidate);
  });

  bot.hears(backButtonMatcher(), async (ctx) => {
    const profile = upsertTelegramProfile(db, ctx.from);
    const language = profile.preferredLanguage || 'ru';
    const candidate = getActiveCandidateByTelegramId(db, profile.telegramUserId);

    if (!candidate || candidate.state === 'completed') {
      await sendVacancyPicker(ctx, db, language);
      return;
    }

    await returnToPreviousQuestion(ctx, db, candidate);
  });

  bot.on('contact', async (ctx) => {
    const profile = upsertTelegramProfile(db, ctx.from);
    if (!profile.preferredLanguage) {
      await askLanguage(ctx);
      return;
    }

    const candidate = getActiveCandidateByTelegramId(db, profile.telegramUserId);
    if (!candidate || candidate.state === 'completed') {
      await sendVacancyPicker(ctx, db, profile.preferredLanguage);
      return;
    }

    const phone = ctx.message.contact?.phone_number || '';
    if (!phone) return;
    await acceptQuestionnaireAnswer(ctx, db, candidate, phone);
  });

  bot.on('text', async (ctx) => {
    const profile = upsertTelegramProfile(db, ctx.from);
    const language = profile.preferredLanguage || 'ru';
    const text = ctx.message.text.trim();

    if (!profile.preferredLanguage) {
      await askLanguage(ctx);
      return;
    }

    const candidate = getActiveCandidateByTelegramId(db, profile.telegramUserId);
    if (!candidate || candidate.state === 'completed') {
      const detectedVacancy = detectVacancy(text);
      if (detectedVacancy && getVacancy(db, detectedVacancy)) {
        const nextCandidate = createOrGetCandidateForVacancy(db, ctx.from, detectedVacancy);
        addMessage(db, nextCandidate.id, 'user', text);
        await startQuestionnaire(ctx, db, nextCandidate);
        return;
      }

      await ctx.reply(t(language).needVacancy, mainKeyboard(language));
      await sendVacancyPicker(ctx, db, language);
      return;
    }

    await acceptQuestionnaireAnswer(ctx, db, candidate, text);
  });

  bot.catch((error, ctx) => {
    console.error('[bot] error', error);
    const language = resolveLanguageFromContext(db, ctx);
    ctx?.reply?.(t(language).error, mainKeyboard(language));
  });

  return bot;
}

async function startQuestionnaire(ctx, db, candidate) {
  const freshCandidate = updateCandidateTelegramInfo(db, candidate.id, ctx.from);
  const language = freshCandidate.preferredLanguage || resolveLanguageFromContext(db, ctx);
  const questions = listQuestionsForCandidate(db, freshCandidate.vacancySlug);

  if (!questions.length) {
    await ctx.reply(t(language).questionnaireEmpty, mainKeyboard(language));
    return;
  }

  const currentQuestion = getCandidateCurrentQuestion(db, freshCandidate.id) || questions[0];
  setCandidateCurrentQuestion(db, freshCandidate.id, currentQuestion.id);
  await askQuestion(ctx, currentQuestion, language);
}

async function acceptQuestionnaireAnswer(ctx, db, candidate, answerText) {
  const freshCandidate = updateCandidateTelegramInfo(db, candidate.id, ctx.from);
  const language = freshCandidate.preferredLanguage || resolveLanguageFromContext(db, ctx);
  const question = getCandidateCurrentQuestion(db, freshCandidate.id);

  if (!question) {
    await completeQuestionnaire(ctx, db, freshCandidate.id, language);
    return;
  }

  if (question.type === 'single_choice') {
    const option = findOptionForAnswer(question, answerText, language);
    if (!option) {
      await ctx.reply(t(language).chooseOption, questionKeyboard(question, language));
      return;
    }
    addMessage(db, freshCandidate.id, 'user', optionLabel(option, language));
    const updated = saveQuestionnaireAnswer(db, freshCandidate.id, question, { option });
    await continueQuestionnaire(ctx, db, updated, language);
    return;
  }

  const cleaned = String(answerText || '').trim();
  if (!cleaned) {
    await askQuestion(ctx, question, language);
    return;
  }

  addMessage(db, freshCandidate.id, 'user', cleaned);
  const updated = saveQuestionnaireAnswer(db, freshCandidate.id, question, { answerText: cleaned });
  await continueQuestionnaire(ctx, db, updated, language);
}

async function continueQuestionnaire(ctx, db, candidate, language) {
  const nextQuestion = getNextQuestionForCandidate(db, candidate.id);
  if (!nextQuestion) {
    await completeQuestionnaire(ctx, db, candidate.id, language);
    return;
  }

  setCandidateCurrentQuestion(db, candidate.id, nextQuestion.id);
  await askQuestion(ctx, nextQuestion, language);
}

async function completeQuestionnaire(ctx, db, candidateId, language) {
  const updated = refreshCandidateQuestionnaireState(db, candidateId);
  setActiveCandidate(db, updated.telegramUserId, null);
  addMessage(db, updated.id, 'assistant', t(language).answersSubmitted);
  await ctx.reply(t(language).answersSubmitted, mainKeyboard(language));
}

async function returnToPreviousQuestion(ctx, db, candidate) {
  const language = candidate.preferredLanguage || resolveLanguageFromContext(db, ctx);
  const previousAnswer = getPreviousAnsweredQuestion(db, candidate.id);

  if (!previousAnswer) {
    const currentQuestion = getCandidateCurrentQuestion(db, candidate.id);
    await ctx.reply(t(language).noPreviousAnswer, currentQuestion ? questionKeyboard(currentQuestion, language) : mainKeyboard(language));
    if (currentQuestion) {
      await askQuestion(ctx, currentQuestion, language);
    }
    return;
  }

  removeCandidateAnswer(db, candidate.id, previousAnswer.questionId);
  const question = getCandidateCurrentQuestion(db, candidate.id);
  if (!question) {
    await completeQuestionnaire(ctx, db, candidate.id, language);
    return;
  }

  addMessage(db, candidate.id, 'system', `Candidate returned to question: ${question.textRu}`);
  await ctx.reply(t(language).returnedBack, questionKeyboard(question, language));
  await askQuestion(ctx, question, language);
}

async function askQuestion(ctx, question, language) {
  await ctx.reply(questionText(question, language), questionKeyboard(question, language));
}

async function askLanguage(ctx) {
  await ctx.reply('Выберите язык общения / Muloqot tilini tanlang:', languageKeyboard());
}

async function sendVacancyPicker(ctx, db, language) {
  await ctx.reply(t(language).chooseVacancy, mainKeyboard(language));
  await ctx.reply(t(language).vacancyButtons, vacancyKeyboard(db, language));
}

function languageKeyboard() {
  return Markup.keyboard([['🇷🇺 Русский', '🇺🇿 O‘zbekcha']]).resize().oneTime();
}

function mainKeyboard(language) {
  return Markup.keyboard([[t(language).vacancies, t(language).changeLanguage]]).resize();
}

function questionKeyboard(question, language) {
  const rows = [];
  if (question.type === 'single_choice') {
    const optionRows = question.options.map((option) => [optionLabel(option, language)]);
    rows.push(...optionRows);
  }
  rows.push([t(language).back]);
  return Markup.keyboard(rows).resize();
}

function vacancyKeyboard(db, language) {
  const buttons = getVacancies(db).map((vacancy) =>
    Markup.button.callback(vacancyTitle(vacancy, language), `vacancy:${vacancy.slug}`)
  );
  return Markup.inlineKeyboard(buttons, { columns: 1 });
}

async function deleteCallbackMessage(ctx) {
  try {
    await ctx.deleteMessage();
  } catch (error) {
    console.warn('[bot] failed to delete callback message:', error.message);
  }
}

function rewriteKeyboard(vacancySlug, language) {
  return Markup.inlineKeyboard(
    [
      Markup.button.callback(t(language).rewriteYes, `rewrite:yes:${vacancySlug}`),
      Markup.button.callback(t(language).rewriteNo, `rewrite:no:${vacancySlug}`)
    ],
    { columns: 1 }
  );
}

function languageButtonMatcher() {
  return Object.values(LANGUAGES).flatMap((language) => language.buttons);
}

function changeLanguageMatcher() {
  return Object.values(LANGUAGES).map((language) => language.changeLanguage);
}

function vacanciesButtonMatcher() {
  return Object.values(LANGUAGES).map((language) => language.vacancies);
}

function backButtonMatcher() {
  return Object.values(LANGUAGES).map((language) => language.back);
}

function resolveLanguageFromText(text) {
  const normalized = String(text || '').toLowerCase();
  if (normalized.includes('uz') || normalized.includes('o‘z') || normalized.includes("o'z") || normalized.includes('узбек')) {
    return 'uz';
  }
  return 'ru';
}

function resolveLanguageFromContext(db, ctx) {
  const telegramUserId = String(ctx?.from?.id || '');
  if (!telegramUserId) return 'ru';
  return getTelegramProfile(db, telegramUserId)?.preferredLanguage || 'ru';
}

function t(language) {
  return LANGUAGES[language] || LANGUAGES.ru;
}

function vacancyTitle(vacancy, language) {
  return t(language).vacancyTitles[vacancy.slug] || vacancy.title;
}

function questionText(question, language) {
  if (language === 'uz' && question.textUz) return question.textUz;
  return question.textRu;
}

function optionLabel(option, language) {
  if (language === 'uz' && option.labelUz) return option.labelUz;
  return option.labelRu;
}

function findOptionForAnswer(question, answerText, language) {
  const normalized = normalizeText(answerText);
  return question.options.find((option) => {
    return [option.labelRu, option.labelUz, optionLabel(option, language)]
      .filter(Boolean)
      .some((label) => normalizeText(label) === normalized);
  });
}

function normalizeText(value) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function hasCandidateAnswers(db, candidate) {
  if (candidate.state === 'completed') return true;
  if (Object.keys(candidate.extracted || {}).length > 0) return true;
  return getCandidateAnswers(db, candidate.id).length > 0;
}

function detectVacancy(text) {
  const normalized = text.toLowerCase();
  if (normalized.includes('офис') || normalized.includes('ofis')) return 'office-manager';
  if (
    normalized.includes('торгов') ||
    normalized.includes('продаж') ||
    normalized.includes('sales') ||
    normalized.includes('savdo')
  ) {
    return 'sales-representative';
  }
  return null;
}
