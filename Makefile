# One-command local environment: `make dev`
.PHONY: dev down migrate test test-unit plugin-zip contracts openapi pilot logs

dev:            ## build and start postgres, redis, minio, api, worker, beat; run migrations
	@test -f .env || cp .env.example .env
	docker compose up -d --build
	docker compose exec api trial-knowledge migrate
	docker compose exec api trial-knowledge seed-claims
	@echo "API: http://localhost:8000/docs   MinIO console: http://localhost:9001"

down:
	docker compose down

logs:
	docker compose logs -f api worker

migrate:
	docker compose exec api trial-knowledge migrate

test:           ## full suite (needs Postgres with pgvector on NTK_TEST_ADMIN_URL)
	NTK_TEST_ADMIN_URL=$${NTK_TEST_ADMIN_URL:-postgresql+psycopg://ntk:ntk@localhost:5432/postgres} python -m pytest

test-unit:
	python -m pytest tests/unit

plugin-zip:
	tools/build_plugin_zip.sh

contracts:
	python tools/build_contracts.py

openapi:
	trial-knowledge openapi

pilot:          ## run the April 2021 pilot through the whole chain
	docker compose exec api trial-knowledge ingest manifests/pilot-april-2021.json --inline
	docker compose exec api trial-knowledge build-claims --slug p-request-attribution --slug p-judicial-remarks
	docker compose exec api trial-knowledge eval --suite golden/adversarial-v1.json --out golden/reports/adversarial.json
	docker compose exec api trial-knowledge eval --suite golden/pilot-hebrew-legal-v1.json --out golden/reports/pilot.json
