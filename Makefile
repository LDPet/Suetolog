.PHONY: install check lint test format up down migrate

install:
	pipenv install --dev

check:
	python manage.py check

lint:
	pipenv run isort --check .
	pipenv run yapf --diff --recursive .

test:
	pipenv run pytest

format:
	pipenv run isort .
	pipenv run yapf --in-place --recursive .


up:
	docker compose up -d
down:
	docker compose down
logs:
	docker compose logs -f
migrate:
	python manage.py migrate
