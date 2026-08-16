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

test:
	$(VENV)/pytest

# Real provider calls; needs a key and costs money.
test-live:
	$(VENV)/pytest -m live

lint:
	$(VENV)/ruff check .
