PYTHON ?= .venv/bin/python
DVC ?= .venv/bin/dvc
COMPOSE = docker compose
AIRFLOW = $(COMPOSE) exec airflow-scheduler airflow
DESDE ?= 2017-01-01
HASTA ?= 2017-08-31
export PYTHONPATH := src

.PHONY: venv test bandeja up down backfill versionar reproducir

venv:        ## entorno local para pruebas, DVC y reproducción
	python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest -q

up:          ## levanta Airflow (http://localhost:8080) y MLflow (http://localhost:5001)
	echo "AIRFLOW_UID=$$(id -u)" > .env
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

bandeja:     ## carga histórica y bandeja a partir de data/kaggle/
	$(COMPOSE) run --rm --no-deps airflow-scheduler python /opt/reposicion/proyecto/scripts/preparar_bandeja.py

backfill:    ## ejecuta el producto sobre un periodo: make backfill DESDE=2017-01-01 HASTA=2017-08-31
	$(AIRFLOW) backfill create --dag-id ingesta_diaria --from-date $(DESDE) --to-date $(HASTA) --max-active-runs 4
	$(AIRFLOW) backfill create --dag-id pronostico_semanal --from-date $(DESDE) --to-date $(HASTA) --max-active-runs 1
	$(AIRFLOW) backfill create --dag-id seguimiento_diario --from-date $(DESDE) --to-date $(HASTA) --max-active-runs 1

versionar:   ## versiona con DVC los datos de entrada, procesados, modelos y pronósticos publicados
	$(DVC) add data/kaggle data/historico bandeja data/landing data/procesado data/publicado models
	$(DVC) push

reproducir:  ## reproduce un pronóstico publicado: make reproducir CORTE=2017-03-06
	$(PYTHON) scripts/reproducir_pronostico.py --corte $(CORTE)
