import { createBot } from './bot.js';

export function createBotRuntime(db, config, settingsStore) {
  let bot = null;
  let currentToken = '';
  let launchPromise = null;
  let retryTimer = null;

  async function start() {
    const settings = await settingsStore.getSettings({ includeSecrets: true });
    await restart(settings.botToken);
  }

  async function restart(nextToken) {
    clearRetryTimer();
    const token = (nextToken || '').trim();
    if (token && token === currentToken && bot) {
      return { running: true, changed: false };
    }

    await stop('settings-update');
    currentToken = token;

    if (!currentToken) {
      console.warn('[bot] Telegram bot token is not configured. Telegram bot is disabled.');
      return { running: false, changed: true };
    }

    const runtimeConfig = {
      ...config,
      telegram: {
        ...config.telegram,
        botToken: currentToken
      }
    };

    const nextBot = createBot(db, runtimeConfig, { settingsStore });
    bot = nextBot;
    launchPromise = nextBot
      .launch({}, () => {
        console.log('[bot] Telegram bot connected, long polling is starting');
      })
      .then(() => {
        if (bot === nextBot) {
          console.warn('[bot] Telegram long polling stopped unexpectedly');
          bot = null;
          currentToken = '';
        }
      })
      .catch((error) => {
        console.error('[bot] Telegram launch failed:', error.message);
        if (bot === nextBot) {
          bot = null;
        }
        if (isUnauthorizedTelegramError(error)) {
          currentToken = '';
          return;
        }
        scheduleRetry(currentToken);
      });

    return { running: true, changed: true };
  }

  async function refresh() {
    const settings = await settingsStore.getSettings({ includeSecrets: true });
    return restart(settings.botToken);
  }

  async function stop(signal = 'SIGTERM') {
    clearRetryTimer();
    if (!bot) return;
    const activeBot = bot;
    bot = null;
    try {
      activeBot.stop(signal);
    } catch (error) {
      console.warn('[bot] stop warning:', error.message);
    }
    try {
      await activeBot.telegram?.deleteWebhook?.();
    } catch {
      // Polling bots do not need webhook cleanup; ignore best-effort failures.
    }
  }

  function isRunning() {
    return Boolean(bot && currentToken);
  }

  function getLaunchPromise() {
    return launchPromise;
  }

  function scheduleRetry(token) {
    if (!token || retryTimer) return;
    retryTimer = setTimeout(() => {
      retryTimer = null;
      if (bot || currentToken !== token) return;
      console.warn('[bot] Retrying Telegram long polling after launch failure');
      restart(token).catch((error) => {
        console.error('[bot] Telegram retry failed:', error.message);
      });
    }, 5_000);
  }

  function clearRetryTimer() {
    if (!retryTimer) return;
    clearTimeout(retryTimer);
    retryTimer = null;
  }

  return {
    start,
    refresh,
    stop,
    isRunning,
    getLaunchPromise
  };
}

function isUnauthorizedTelegramError(error) {
  return String(error?.message || '').includes('401');
}
