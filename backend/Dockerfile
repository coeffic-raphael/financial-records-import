FROM python:3.11-slim

# Bytecode written at build time, and nothing buffered: a crash must not take
# the last log lines with it.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Lowest precedence of the three levels compose uses, so a clean clone with
    # no .env still starts -- while an .env that names a real provider wins.
    EXTRACTION_PROVIDER=mock

WORKDIR /app

# Dependencies first, so editing source does not reinstall them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Uploaded documents live on a named volume mounted here. Created and owned
# before dropping privileges, or the unprivileged process cannot write to it.
RUN mkdir -p /app/uploads \
    && useradd --create-home --uid 1000 app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# Migrations run at start, not at build: an image must know nothing about the
# state of a database. `exec` so uvicorn becomes PID 1 and receives signals.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
