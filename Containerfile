FROM ghcr.io/astral-sh/uv:trixie-slim


RUN apt update && \
    apt install -y --no-install-recommends curl ca-certificates default-libmysqlclient-dev build-essential pkg-config libcairo2-dev sqlite3 cron && \
    apt clean

ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_DEV=1
ENV UV_NO_CACHE=1
ENV VIRTUAL_ENV=/opt/venv

WORKDIR /app

COPY . .

RUN uv python install 3.10 && \
    uv venv "$VIRTUAL_ENV" && \
    uv pip install -r requirements.txt && \
    uv pip install 'setuptools<82' && \
    uv run noethysweb/manage.py collectstatic --noinput

WORKDIR /app/noethysweb


CMD ["./tools/run.sh"]
