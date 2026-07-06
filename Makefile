.PHONY: install check test format

install:
	pipenv install --dev

check:
	python manage.py check

test:
	pipenv run pytest

format:
	pipenv run isort .
	pipenv run yapf --in-place --recursive .

