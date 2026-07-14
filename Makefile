.PHONY: install check lint test format fix up up-infra down logs ps migrate migrate-docker worker beat

PIPENV = pipenv
DOCKER_COMPOSE = docker compose
PY_FILES := $(shell git ls-files '*.py')

install:
	$(PIPENV) install --dev

check:
	$(PIPENV) run python manage.py check

lint:
	$(PIPENV) run isort --check $(PY_FILES)
	$(PIPENV) run yapf --diff $(PY_FILES)

test:
	$(PIPENV) run pytest

format:
	$(PIPENV) run isort $(PY_FILES)
	$(PIPENV) run yapf --in-place $(PY_FILES)

fix: format


up:
	$(DOCKER_COMPOSE) --profile app up -d --build

up-infra:
	$(DOCKER_COMPOSE) up -d postgres redis

down:
	$(DOCKER_COMPOSE) --profile app down

logs:
	$(DOCKER_COMPOSE) --profile app logs -f bot worker beat

ps:
	$(DOCKER_COMPOSE) --profile app ps -a

migrate:
	$(PIPENV) run python manage.py migrate

migrate-docker:
	$(DOCKER_COMPOSE) --profile app run --rm migrate

worker:
	$(PIPENV) run celery -A config worker --loglevel=info --pool=solo

beat:
	$(PIPENV) run celery -A config beat --loglevel=info
