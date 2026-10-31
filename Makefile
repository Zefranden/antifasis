PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: install db init actualizar resumen exportar test limpiar ayuda

ayuda:
	@echo "make install     Crea .venv e instala el proyecto y las dependencias de desarrollo"
	@echo "make db          Levanta PostgreSQL con Docker"
	@echo "make init        Aplica el esquema y registra los 20 medios"
	@echo "make actualizar  Extrae y guarda las noticias"
	@echo "make resumen     Muestra el resumen de hoy"
	@echo "make test        Ejecuta las pruebas unitarias"
	@echo "make limpiar     Borra caches de Python y pytest"

install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -e ".[dev]"

db:
	docker compose up -d db

init:
	$(BIN)/python -m antifasis init-db

actualizar:
	$(BIN)/python -m antifasis actualizar

resumen:
	$(BIN)/python -m antifasis resumen

exportar:
	$(BIN)/python -m antifasis exportar

test:
	$(BIN)/pytest

limpiar:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .coverage htmlcov
