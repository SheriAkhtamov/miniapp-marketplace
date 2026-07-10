FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# postgresql-client-17 — должен совпадать с версией postgres в docker-compose (postgres:17)
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg lsb-release ffmpeg \
    && echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/pgdg.gpg \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
    && apt-get purge -y curl gnupg lsb-release && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаем папки для медиа и логов
RUN mkdir -p media logs

# Копируем entrypoint и убираем Windows-переносы строк (CRLF → LF)
COPY entrypoint.sh .
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

CMD ["sh", "entrypoint.sh"]
