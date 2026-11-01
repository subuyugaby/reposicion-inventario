# Motor de reposición de inventario

Cada lunes pronostica 14 días de ventas por tienda y familia (Corporación Favorita, Kaggle) con cuantiles,
deriva un pedido sugerido para 7 días según los costos de configs/costos.yaml y da seguimiento a lo publicado.
Laboratorio 1 de Product Development: Git + DVC + Airflow 3 + MLflow.

## Comandos
- `make venv` · `make test`: entorno local (Python 3.12) y pruebas.
- `make up` · `make down`: Airflow en http://localhost:8080 y MLflow en http://localhost:5000.
- `make bandeja`: carga histórica y bandeja a partir de data/kaggle/.
- `make backfill DESDE=… HASTA=…`: ejecuta los tres DAGs sobre un periodo.
- `make versionar`: `dvc add` de datos, modelos y pronósticos, y `dvc push`.
- `make reproducir CORTE=AAAA-MM-DD`: reproduce un pronóstico publicado.

## Estructura
- `src/reposicion/`: toda la lógica (fuentes, features, modelos, negocio, entrenamiento, pronostico, seguimiento, bandeja).
- `dags/`: solo orquestan; llaman a funciones de `src/reposicion/`.
- `params.yaml`: horizonte, cuantiles, partición temporal, hiperparámetros y reglas de promoción.
- `configs/costos.yaml`: costos de faltante y sobrante; cambian el pedido sin tocar código.
- `bandeja/`: sistema de origen simulado; `data/historico/`: carga histórica.

## Reglas del proyecto
- Toda predicción usa solo información disponible en la fecha de corte: entregas con fecha <= corte y filas con fecha < corte.
- Las tareas usan la fecha lógica del run (`ds`), nunca la fecha de hoy.
- La bandeja se lee, nunca se modifica (en Docker se monta en solo lectura).
- Toda escritura reemplaza la partición de su fecha de forma atómica: repetir una tarea no duplica nada.
- Los datos y modelos nunca van a Git: se versionan con DVC (`make versionar`).
- La validación es temporal y la misma para todos los modelos (`entrenamiento.particion`).
- Un modelo solo reemplaza al vigente si pasa la compuerta (`entrenamiento.decidir`).
- Ramas `feat/`, `fix/`, `data/`, `docs/`, `chore/`; todo cambio entra a main por Pull Request con las pruebas en verde.
- Commits con Conventional Commits: `tipo(alcance): descripción`.
