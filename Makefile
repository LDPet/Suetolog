.PHONY: install check lint test format fix up down migrate

PIPENV = pipenv
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
	docker compose up -d
down:
	docker compose down
logs:
	docker compose logs -f
migrate:
	python manage.py migrate
