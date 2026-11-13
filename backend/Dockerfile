FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project
RUN useradd --create-home app && mkdir /state && chown app:app /app /state
COPY --chown=app:app . .
USER app
# Every service command passes the database identity guard first. Only the
# service commands (uvicorn, celery, debugpy wrapping them) are accepted; the migrate
# service replaces this entrypoint with `python -m app.guard` (plan/apply).
ENTRYPOINT ["python", "-m", "app.guard", "exec", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
