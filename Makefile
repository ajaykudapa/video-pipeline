.PHONY: up down logs scale test smoke

up:
	docker compose up -d --build

down:
	docker compose down -v

logs:
	docker compose logs -f api worker autoscaler

scale:
	docker compose up -d --scale worker=$(N) --no-recreate

test:
	python -m pytest tests/ -v

smoke:
	./scripts/smoke_test.sh
