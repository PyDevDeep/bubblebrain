# Stage 1: Builder
FROM python:3.13-slim AS builder

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app

# Встановлюємо poetry перед копіюванням файлів
RUN pip install poetry

COPY pyproject.toml poetry.lock ./

# Встановлюємо лише production залежності
RUN poetry install --only main --no-root && rm -rf $POETRY_CACHE_DIR

# Stage 2: Runtime
FROM python:3.13-slim AS runtime

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Копіюємо віртуальне середовище з першого етапу
COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

# Копіюємо вихідний код
COPY ./app ./app

EXPOSE 8000

# Запуск uvicorn згідно з вимогами Roadmap
# Заміни поточний CMD на цей:
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
