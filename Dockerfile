# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /app
RUN pip install uv
COPY pyproject.toml ./
RUN uv sync

# --- Stage 2: Final Image ---
FROM python:3.12-slim AS final
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY . .

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
