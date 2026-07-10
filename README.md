# Unicom Bot

Telegram Mini App shop with FastAPI, aiogram, PostgreSQL, Redis, Docker Compose and Nginx.

## Environment

Runtime configuration is loaded from `.env`. Keep `.env` only on the server or in GitHub Actions secrets; commit `.env.example` as the template.

For share links from the admin panel, set `BOT_USERNAME`. If the Mini App has a BotFather direct-link short name, also set `TELEGRAM_MINI_APP_SHORT_NAME`; otherwise links use the bot's main Mini App format.

## Local checks

```bash
cp .env.example .env
python -m compileall app main.py create_admin.py
docker compose config || docker-compose config
```

## Deployment

Pushes to `main` run `.github/workflows/deploy.yml`. The workflow expects these repository secrets:

- `SERVER_HOST`
- `SERVER_USER`
- `SERVER_PASSWORD`
- `PRODUCTION_ENV` containing the full `.env` file content

The workflow syncs the repository to `/root/shop_bot`, preserves runtime folders, rebuilds Docker Compose services and checks `/health`.
