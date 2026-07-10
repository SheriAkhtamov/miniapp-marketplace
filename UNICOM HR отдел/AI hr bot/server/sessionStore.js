export function createSessionStore(sessionModule, db) {
  const Store = sessionModule.Store;

  db.exec(`
    CREATE TABLE IF NOT EXISTS web_sessions (
      sid TEXT PRIMARY KEY,
      data TEXT NOT NULL,
      expires_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_web_sessions_expires ON web_sessions(expires_at);
  `);

  const statements = {
    get: db.prepare('SELECT data, expires_at FROM web_sessions WHERE sid = ?'),
    set: db.prepare(`
      INSERT INTO web_sessions (sid, data, expires_at)
      VALUES (?, ?, ?)
      ON CONFLICT(sid) DO UPDATE SET
        data = excluded.data,
        expires_at = excluded.expires_at
    `),
    touch: db.prepare('UPDATE web_sessions SET expires_at = ? WHERE sid = ?'),
    destroy: db.prepare('DELETE FROM web_sessions WHERE sid = ?'),
    prune: db.prepare('DELETE FROM web_sessions WHERE expires_at <= ?')
  };

  return new (class BetterSqliteSessionStore extends Store {
    get(sid, callback) {
      try {
        const row = statements.get.get(sid);
        if (!row) {
          callback(null, null);
          return;
        }

        if (row.expires_at <= Date.now()) {
          statements.destroy.run(sid);
          callback(null, null);
          return;
        }

        callback(null, JSON.parse(row.data));
      } catch (error) {
        callback(error);
      }
    }

    set(sid, sessionData, callback) {
      try {
        statements.set.run(sid, JSON.stringify(sessionData), getExpiresAt(sessionData));
        statements.prune.run(Date.now());
        callback?.(null);
      } catch (error) {
        callback?.(error);
      }
    }

    touch(sid, sessionData, callback) {
      try {
        statements.touch.run(getExpiresAt(sessionData), sid);
        callback?.(null);
      } catch (error) {
        callback?.(error);
      }
    }

    destroy(sid, callback) {
      try {
        statements.destroy.run(sid);
        callback?.(null);
      } catch (error) {
        callback?.(error);
      }
    }
  })();
}

function getExpiresAt(sessionData) {
  const maxAge = sessionData?.cookie?.originalMaxAge;
  if (typeof maxAge === 'number' && maxAge > 0) {
    return Date.now() + maxAge;
  }
  return Date.now() + 1000 * 60 * 60 * 12;
}
