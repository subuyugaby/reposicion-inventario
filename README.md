# Motor de reposición de inventario

Laboratorio 1 · Product Development · Maestría en Data Science, Universidad Galileo.

Cada lunes, el producto transforma las ventas que llegan a diario desde el sistema de origen en:

1. **Pronóstico de ventas** diario para los 14 días siguientes, por tienda y familia, con cuantiles p10, p50 y p90.
2. **Pedido sugerido** para los 7 días siguientes: el cuantil `faltante / (faltante + sobrante)` del pronóstico,
   con los costos de [configs/costos.yaml](configs/costos.yaml).
3. **Seguimiento del desempeño**: lo publicado contra las ventas reales a medida que se conocen
   ([reportes/seguimiento.md](reportes/seguimiento.md)).

Datos: [Corporación Favorita, Kaggle](https://www.kaggle.com/competitions/store-sales-time-series-forecasting/data).
Las decisiones de diseño y su justificación están en [DECISIONES.md](DECISIONES.md).

## Arquitectura

```
data/kaggle/ ──make bandeja──► data/historico/  (carga histórica, hasta 2016-12-31)
                           └─► bandeja/<fuente>/<fuente>_<fecha de entrega>.csv  (sistema de origen, solo lectura)

ingesta_diaria       validar_y_cargar[ventas | transacciones | petroleo] ──► data/landing/  o  data/cuarentena/
pronostico_semanal   sincronizar_bandeja ► asegurar_modelo ► entrenar_challenger ► compuerta ┬► promover  ─┐
     (lunes)                                                (primer lunes del mes)            └► descartar ─┴► preparar ► pronosticar ► generar_pedido
                                                                                                   data/procesado/corte=C/   data/publicado/corte=C/
seguimiento_diario   sincronizar_bandeja ► evaluar_publicados ──► data/seguimiento/ y reportes/seguimiento.md
```

| Herramienta | Qué guarda o hace |
|---|---|
| Git | Código, `params.yaml`, `configs/costos.yaml`, DAGs, pruebas y punteros `.dvc` |
| DVC | Datos de entrada, landing, procesados, modelos (`models/`) y pronósticos publicados |
| Airflow 3.3 | Orquesta los tres DAGs (LocalExecutor + Postgres, Docker Compose) |
| MLflow 3.17 | Runs de entrenamiento, métricas, Model Registry (`@champion`, `@anterior`) |

| Ruta | Contenido |
|---|---|
| `src/reposicion/` | Toda la lógica: `fuentes`, `bandeja`, `features`, `modelos`, `negocio`, `entrenamiento`, `pronostico`, `seguimiento` |
| `dags/` | Solo orquestación |
| `tests/` | Pruebas con datos sintéticos (pytest, en GitHub Actions en cada Pull Request) |
| `scripts/` | `preparar_bandeja.py` y `reproducir_pronostico.py` |
| `reportes/` | `comparacion_modelos.md` y `seguimiento.md` |

## Ejecutar el producto desde cero

Requisitos: Docker con Docker Compose (Docker Desktop, OrbStack o Docker Engine), `make` y unos 6 GB de RAM para
los contenedores. En macOS, clone el repositorio fuera de carpetas sincronizadas con iCloud (Escritorio o
Documentos con "Optimizar almacenamiento"): iCloud puede dejar archivos solo en la nube y los contenedores los
leen vacíos.

```bash
git clone https://github.com/subuyugaby/reposicion-inventario.git
cd reposicion-inventario
```

1. **Coloque los archivos de Kaggle** `train.csv`, `stores.csv`, `holidays_events.csv`, `oil.csv` y
   `transactions.csv` en **`data/kaggle/`**. `test.csv` y `sample_submission.csv` no se usan.

2. **Levante Airflow y MLflow** (la primera vez construye la imagen, unos minutos):

   ```bash
   make up
   ```

   Airflow: http://localhost:8080 (sin usuario ni contraseña) · MLflow: http://localhost:5001

3. **Construya la carga histórica y la bandeja** a partir de los archivos de Kaggle:

   ```bash
   make bandeja
   ```

4. **Ejecute el producto sobre un periodo** (backfill de los tres DAGs):

   ```bash
   make backfill DESDE=2017-01-01 HASTA=2017-08-31
   ```

   El avance se ve en Airflow. El primer lunes registra el baseline como modelo inicial y entrena el primer
   LightGBM; desde ahí, cada lunes publica pronóstico y pedido, y cada primer lunes del mes reentrena.

Resultados: `data/publicado/corte=AAAA-MM-DD/{pronostico.parquet, pedido.parquet, metadata.json}`,
[reportes/comparacion_modelos.md](reportes/comparacion_modelos.md) y [reportes/seguimiento.md](reportes/seguimiento.md).

### Otro periodo o una bandeja propia

- La fecha desde la que los datos llegan por la bandeja es `bandeja.inicio` en [params.yaml](params.yaml); lo
  anterior es la carga histórica. Si `train.csv` trae más fechas, `make bandeja` genera sus entregas.
- También pueden colocarse entregas propias en `bandeja/<fuente>/<fuente>_<AAAA-MM-DD>.csv`, con la fecha de
  *entrega* en el nombre y las columnas de Kaggle (`date, store_nbr, family, sales, onpromotion` para ventas,
  `date, store_nbr, transactions` y `date, dcoilwtico`). Una entrega puede traer varios días y correcciones de
  días ya entregados: vale la entrega más reciente.
- Entregas inválidas, días sin entregas, llegadas tardías y correcciones se manejan sin intervención; ver
  [DECISIONES.md](DECISIONES.md#3-validación-de-los-datos).

## Desarrollo

```bash
make venv    # entorno local con Python 3.12 (en macOS LightGBM requiere: brew install libomp)
make test
```

Todo cambio entra a `main` mediante una rama y un Pull Request con las pruebas de GitHub Actions en verde.

## Versionado con DVC y reproducción de un pronóstico pasado

Después de una ejecución, `make versionar` hace `dvc add` de datos de entrada, landing, procesados, modelos y
pronósticos publicados y `dvc push` al remoto. Los `.dvc` resultantes se confirman en Git y se etiqueta la versión.

La ejecución de enero a agosto de 2017 quedó versionada en el tag **`pronosticos-2017`**. Para reproducir un
pronóstico publicado se obtiene esa versión del código y los datos en un directorio aparte, y se vuelve a
calcular el pronóstico de un corte con el modelo y los datos que registra su `metadata.json`:

```bash
git worktree add ../reposicion-v2017 pronosticos-2017   # código, params.yaml, costos.yaml y punteros .dvc
cd ../reposicion-v2017
dvc pull                                                 # datos, modelos y pronósticos exactos de esa versión
PYTHONPATH=src python scripts/reproducir_pronostico.py --corte 2017-03-06
PYTHONPATH=src python scripts/reproducir_pronostico.py --corte 2017-06-12
```

Resultado obtenido:

```
1445 files fetched and 1438 files added

corte:               2017-03-06
modelo:              v2 (lightgbm) models/lightgbm_2017-01-02.joblib
commit publicado:    95f249dbc0b5fe4d0a26250baa7dd83b1be5c673
commit actual:       97e312e4d6d5743f91289df1f0974b58e3967a37
huella de datos:     acd6e7e6fbeb25689158c2331351a0ca (igual)
pronóstico y pedido: idénticos al publicado (24,948 y 12,474 filas)

corte:               2017-06-12
modelo:              v7 (lightgbm) models/lightgbm_2017-06-05.joblib
commit publicado:    95f249dbc0b5fe4d0a26250baa7dd83b1be5c673
commit actual:       97e312e4d6d5743f91289df1f0974b58e3967a37
huella de datos:     8928a20947fa50e4d90c19997a7cd4aa (igual)
pronóstico y pedido: idénticos al publicado (24,948 y 12,474 filas)
```

El script recalcula features, pronóstico y pedido desde los datos disponibles en el corte y los compara fila
por fila con lo publicado. La huella de los datos de entrada coincide con la registrada al publicar. El commit
actual difiere del publicado solo en dos correcciones del script de reproducción y de la lectura del commit; la
lógica del pronóstico es la misma.

## Evidencia de funcionamiento

Ejecución de `make backfill DESDE=2017-01-01 HASTA=2017-08-31` sobre la bandeja generada desde Kaggle:

| DAG | Runs | Resultado |
|---|---|---|
| `ingesta_diaria` | 243 | 242 exitosos; **1 fallido a propósito**: la entrega `ventas_2017-07-13.csv` trae ventas negativas, queda en `data/cuarentena/` y su contenido llega reenviado en la entrega siguiente |
| `pronostico_semanal` | 35 | 35 exitosos: 35 pronósticos y pedidos publicados, 9 versiones de modelo registradas |
| `seguimiento_diario` | 243 | 243 exitosos |

**Comparación de modelos** ([reportes/comparacion_modelos.md](reportes/comparacion_modelos.md)). Retador y
vigente se miden en las mismas 4 fechas de evaluación:

| Corte | Retador | Costo retador | Costo vigente | WAPE retador / vigente | Decisión |
|---|---|---|---|---|---|
| 2017-01-02 | v1 baseline | 7,440,190 | — | 0.205 / — | modelo inicial |
| 2017-01-02 | v2 LightGBM | 5,811,949 | 7,440,190 (v1) | 0.168 / 0.205 | **promovido** (−21.9 % de costo) |
| 2017-02-06 … 2017-05-01 | v3–v6 LightGBM | — | v2 | — | descartados (no bajan el costo 2 %) |
| 2017-06-05 | v7 LightGBM | 4,980,984 | 5,272,865 (v2) | 0.148 / 0.158 | **promovido** (−5.5 %) |
| 2017-07-03 | v8 LightGBM | 4,182,215 | 4,030,261 (v7) | 0.135 / 0.129 | descartado |
| 2017-08-07 | v9 LightGBM | 3,669,135 | 3,806,720 (v7) | 0.118 / 0.118 | **promovido** (−3.6 %) |

**Seguimiento del desempeño** ([reportes/seguimiento.md](reportes/seguimiento.md)), en los 31 cortes con sus
14 días ya observados: WAPE medio de la mediana 0.150, cobertura media del intervalo p10–p90 78.2 % (nominal
80 %), y costo del pedido sugerido igual a 9.8 % de las ventas reales. El faltante equivale al 5.4 % de las
ventas y el sobrante al 13.1 %: con los costos configurados el pedido prefiere sobrar a faltar.

Capturas de la interfaz de Airflow y de MLflow: [reportes/evidencia/](reportes/evidencia/).
