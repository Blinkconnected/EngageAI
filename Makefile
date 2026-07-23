.PHONY: backend-install backend-test backend-lint backend-typecheck backend-check up down logs

backend-install:
	cd backend && python3.13 -m venv .venv && . .venv/bin/activate && pip install --upgrade pip && pip install -e ".[dev]"

backend-test:
	cd backend && . .venv/bin/activate && python -m pytest -q --cov=blinkengage --cov-report=term-missing

backend-lint:
	cd backend && . .venv/bin/activate && ruff check src tests && black --check src tests

backend-typecheck:
	cd backend && . .venv/bin/activate && mypy src

backend-check: backend-lint backend-typecheck backend-test

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f
