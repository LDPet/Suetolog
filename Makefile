.PHONY: install check test format up down

install:
	pipenv install --dev

check:
	python manage.py check

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
