# DF_Xray Panel — быстрые команды для разработки и эксплуатации.
PYTHON ?= python3
PORT   ?= 8000
DATA   ?= ./data

.PHONY: help run seed check test reset-password docker-up docker-down docker-logs clean

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

run: ## Запустить панель локально (данные в ./data)
	DFX_DATA_DIR=$(DATA) $(PYTHON) -m app serve --port $(PORT)

seed: ## Наполнить базу демо-данными
	DFX_DATA_DIR=$(DATA) $(PYTHON) -m app seed

check: ## Показать состояние базы
	DFX_DATA_DIR=$(DATA) $(PYTHON) -m app check

test: ## Запустить тесты
	$(PYTHON) -m unittest discover -s tests -v

reset-password: ## Сбросить пароль администратора
	DFX_DATA_DIR=$(DATA) $(PYTHON) -m app reset-password

docker-up: ## Поднять панель и ноду в Docker
	docker compose up -d --build

docker-down: ## Остановить контейнеры
	docker compose down

docker-logs: ## Логи панели
	docker compose logs -f panel

clean: ## Удалить локальные данные и кэш
	rm -rf $(DATA) __pycache__ app/__pycache__ app/vendor/qrcode/__pycache__ tests/__pycache__
