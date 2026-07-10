import express from 'express';
import helmet from 'helmet';
import morgan from 'morgan';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { config } from './config.js';
import { createDb } from './db.js';
import { createBotRuntime } from './botRuntime.js';
import { createRoutes } from './routes.js';
import { createSettingsStore } from './settingsStore.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');
const port = Number(config.server.port || 3000);

const app = express();
const db = createDb(config.server.databasePath);
const settingsStore = await createSettingsStore(config);
const botRuntime = createBotRuntime(db, config, settingsStore);

app.use(helmet({ contentSecurityPolicy: false }));
app.use(morgan('dev'));

app.use(createRoutes(db, config, { settingsStore, botRuntime }));

const distDir = path.resolve(rootDir, 'dist');
app.use(express.static(distDir));
app.get(/.*/, (req, res, next) => {
  if (req.path.startsWith('/api') || req.path === '/health') {
    next();
    return;
  }
  res.sendFile(path.join(distDir, 'index.html'), (error) => {
    if (error) {
      res.status(404).send('Admin panel is not built yet. Run npm run build or use npm run dev.');
    }
  });
});

const server = app.listen(port, () => {
  console.log(`[server] Admin API listening on http://localhost:${port}`);
});

await botRuntime.start();

process.once('SIGINT', () => shutdown('SIGINT'));
process.once('SIGTERM', () => shutdown('SIGTERM'));

async function shutdown(signal) {
  console.log(`[server] ${signal} received, shutting down`);
  await botRuntime.stop(signal);
  await settingsStore.close();
  server.close(() => process.exit(0));
}
