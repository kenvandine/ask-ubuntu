.PHONY: setup-dev lint format

setup-dev:
	sudo apt install pre-commit
	pre-commit install

lint:
	pre-commit run --all-files

format:
	ruff format .
