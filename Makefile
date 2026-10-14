.PHONY: backend-check frontend-check docs-check api-types check

backend-check:
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .
	cd backend && uv run pyright
	cd backend && uv run pytest

docs-check:
	python3 scripts/check_docs.py

frontend-check:
	cd frontend && npm run lint
	cd frontend && npm run typecheck
	cd frontend && npm run test
	cd frontend && npm run build

api-types:
	cd backend && uv run python ../scripts/export_openapi.py
	cd frontend && npm run generate:api

check: docs-check backend-check frontend-check