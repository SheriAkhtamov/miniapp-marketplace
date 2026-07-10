import { Pool } from 'pg';

const SETTINGS_ID = 1;

export async function createSettingsStore(config) {
  const pool = new Pool({
    host: config.postgres.host,
    port: config.postgres.port,
    user: config.postgres.user,
    password: config.postgres.password,
    database: config.postgres.database,
    max: 4,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000
  });

  const store = new SettingsStore(pool, config);
  await store.init();
  return store;
}

class SettingsStore {
  constructor(pool, config) {
    this.pool = pool;
    this.config = config;
  }

  async init() {
    await this.pool.query(`
      CREATE TABLE IF NOT EXISTS hr_workspace_settings (
        id INTEGER PRIMARY KEY DEFAULT 1,
        bot_token TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT hr_workspace_settings_singleton CHECK (id = 1)
      )
    `);

    await this.pool.query(`
      ALTER TABLE hr_workspace_settings
        DROP COLUMN IF EXISTS ai_provider,
        DROP COLUMN IF EXISTS ai_api_key,
        DROP COLUMN IF EXISTS ai_base_url,
        DROP COLUMN IF EXISTS ai_model,
        DROP COLUMN IF EXISTS reasoning_effort
    `);

    await this.pool.query('DROP TABLE IF EXISTS hr_ai_model_cache');

    await this.pool.query(
      `
      INSERT INTO hr_workspace_settings (
        id, bot_token
      )
      VALUES ($1, $2)
      ON CONFLICT (id) DO NOTHING
      `,
      [SETTINGS_ID, cleanSecret(this.config.telegram.botToken)]
    );
  }

  async getSettings({ includeSecrets = false } = {}) {
    const result = await this.pool.query(
      `SELECT * FROM hr_workspace_settings WHERE id = $1 LIMIT 1`,
      [SETTINGS_ID]
    );
    const row = result.rows[0];
    if (!row) {
      throw new Error('HR settings row was not initialized');
    }
    return serializeSettings(row, includeSecrets);
  }

  async updateSettings(input) {
    const current = await this.getSettings({ includeSecrets: true });
    const next = {
      botToken: resolveSecretUpdate(current.botToken, input.botToken, input.clearBotToken)
    };

    const result = await this.pool.query(
      `
      UPDATE hr_workspace_settings
      SET
        bot_token = $1,
        updated_at = NOW()
      WHERE id = $2
      RETURNING *
      `,
      [next.botToken, SETTINGS_ID]
    );

    return serializeSettings(result.rows[0], true);
  }

  async close() {
    await this.pool.end();
  }
}

function serializeSettings(row, includeSecrets) {
  return {
    botToken: includeSecrets ? row.bot_token || '' : undefined,
    botTokenConfigured: Boolean(row.bot_token),
    updatedAt: row.updated_at
  };
}

function resolveSecretUpdate(currentValue, nextValue, shouldClear) {
  if (shouldClear) return '';
  const cleaned = cleanSecret(nextValue);
  return cleaned === null ? currentValue || '' : cleaned;
}

function cleanSecret(value) {
  if (value === undefined || value === null) return null;
  const cleaned = String(value).trim();
  return cleaned ? cleaned : null;
}
