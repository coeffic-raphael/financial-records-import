.PHONY: install migrate seed run test lint

VENV := .venv/bin

install:
	python3 -m venv .venv
	$(VENV)/pip install -r requirements.txt -r requirements-dev.txt

migrate:
	$(VENV)/alembic upgrade head

seed: migrate
	$(VENV)/python -m app.seed

run:
	$(VENV)/uvicorn app.main:app --reload

# The two URLs the harness requires. Supplied here rather than defaulted in the
# code: the suite empties every table in DATABASE_URL_TEST, so which database
# that is must be visible, not inferred. Both point at `docker compose up -d db`.
TEST_ENV = DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/financial_records \
           DATABASE_URL_TEST=postgresql+psycopg://app:app@localhost:5432/financial_records_test

test:
	$(TEST_ENV) $(VENV)/pytest

# Real provider calls; needs a key and costs money.
test-live:
	$(TEST_ENV) $(VENV)/pytest -m live

lint:
	$(VENV)/ruff check .
