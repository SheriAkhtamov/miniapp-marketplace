import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');
const configPath = path.resolve(rootDir, 'config.json');

const defaults = {
  server: {
    port: process.env.PORT || 3000,
    appBaseUrl: 'http://localhost:3000',
    databasePath: './data/hr-bot.sqlite'
  },
  workspace: {
    marketBaseUrl: 'http://localhost:8000',
    marketWorkspaceUrl: 'http://localhost:8000/admin',
    hrWorkspaceUrl: 'http://localhost:3000'
  },
  telegram: {
    botToken: ''
  },
  postgres: {
    host: 'db',
    port: 5432,
    user: 'postgres',
    password: 'postgres',
    database: 'shop_db'
  },
  screening: {
    enforceSensitiveCriteria: false
  }
};

export const config = applyEnv(loadConfig());

export function loadConfig() {
  if (!fs.existsSync(configPath)) {
    console.warn(`[config] ${configPath} not found. Using safe defaults.`);
    return defaults;
  }

  const fileConfig = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  return mergeConfig(defaults, fileConfig);
}

function mergeConfig(base, override) {
  const merged = { ...base };

  for (const [key, value] of Object.entries(override || {})) {
    if (isPlainObject(value) && isPlainObject(base[key])) {
      merged[key] = mergeConfig(base[key], value);
    } else {
      merged[key] = value;
    }
  }

  return merged;
}

function isPlainObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value);
}

function applyEnv(fileConfig) {
  return mergeConfig(fileConfig, {
    server: {
      port: process.env.PORT || fileConfig.server.port,
      appBaseUrl: process.env.UNICOM_HR_WORKSPACE_URL || fileConfig.server.appBaseUrl,
      databasePath: process.env.HR_DATABASE_PATH || fileConfig.server.databasePath
    },
    workspace: {
      marketBaseUrl: process.env.UNICOM_MARKET_BASE_URL || fileConfig.workspace.marketBaseUrl,
      marketWorkspaceUrl:
        process.env.UNICOM_MARKET_WORKSPACE_URL || fileConfig.workspace.marketWorkspaceUrl,
      hrWorkspaceUrl: process.env.UNICOM_HR_WORKSPACE_URL || fileConfig.workspace.hrWorkspaceUrl
    },
    telegram: {
      botToken: process.env.HR_TELEGRAM_BOT_TOKEN || fileConfig.telegram.botToken
    },
    postgres: {
      host: process.env.HR_PG_HOST || process.env.DB_HOST || fileConfig.postgres.host,
      port: Number(process.env.HR_PG_PORT || process.env.DB_PORT || fileConfig.postgres.port),
      user: process.env.HR_PG_USER || process.env.DB_USER || fileConfig.postgres.user,
      password: process.env.HR_PG_PASSWORD || process.env.DB_PASS || fileConfig.postgres.password,
      database: process.env.HR_PG_DATABASE || process.env.DB_NAME || fileConfig.postgres.database
    }
  });
}
