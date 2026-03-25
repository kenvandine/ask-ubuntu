.PHONY: setup-dev lint format

setup-dev:
	pip install pre-commit
	pre-commit install

lint:
	pre-commit run --all-files

format:
	ruff format .
