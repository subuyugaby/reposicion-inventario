# Decisiones técnicas y de producto

Cada decisión indica la alternativa considerada y por qué se eligió la opción actual.

## 1. Producto

| Decisión | Elección | Alternativa | Justificación |
|---|---|---|---|
| Fecha de corte | Cada lunes a las 06:00 (`pronostico_semanal`) | Corte diario | La dirección pide una sugerencia semanal; un corte semanal también reduce el costo de cómputo. |
| Horizonte | 14 días después del corte | 7 días | El pedido cubre 7 días; los 7 siguientes anticipan el próximo pedido y permiten medir el deterioro del pronóstico con h. |
| Pedido | Por día, tienda y familia, para los 7 días siguientes al corte, redondeado hacia arriba | Un total semanal | La suma de cuantiles diarios no es el cuantil de la suma; el pedido diario es consistente con el costo diario que se mide. |
| Regla del pedido | Cuantil `faltante / (faltante + sobrante)` del pronóstico (newsvendor) | Media más un inventario de seguridad fijo | Es la cantidad que minimiza el costo esperado con los costos dados; cambiar `configs/costos.yaml` cambia el pedido sin tocar el código ni reentrenar. |
| Costos | Por defecto faltante 1 y sobrante 0.25 (cuantil 0.80); perecederos faltante 1 y sobrante 0.9 (cuantil 0.53) | Un costo único | El contexto describe quiebres en alta rotación y merma en perecederos: dos perfiles de costo distintos. |

## 2. Disponibilidad de la información en el tiempo

**Principio:** un pronóstico con corte C usa solo las entregas con fecha de entrega ≤ C y, dentro de ellas, solo
filas con fecha < C (`fuentes.panel` y `features.datos_al_corte`). La prueba
`test_features_no_usan_datos_del_corte_en_adelante` altera los datos desde el corte y comprueba que las features
no cambian.

| Fuente | Cómo llega (simulación) | Qué se conoce el lunes C |
|---|---|---|
| Ventas | Al día siguiente; 4 % de los días, de 2 a 4 días tarde | Hasta C-1, salvo días retrasados |
| Transacciones | Cada lunes, la semana anterior completa | Hasta C-1 |
| Petróleo | Días hábiles, al día siguiente | Último día hábil anterior |
| Feriados y tiendas | Datos maestros, completos en la carga histórica | Todo el calendario |

- **Bandeja: una entrega por fecha y fuente** (`<fuente>_<AAAA-MM-DD>.csv`), donde la fecha es la de *entrega*,
  no la de los datos. La alternativa, un archivo por fecha de datos, no permite expresar llegadas tardías ni
  correcciones sin inventar otra convención. Con la fecha de entrega en el nombre, la disponibilidad es explícita y
  el simulador y un sistema real se tratan igual.
- **Feriados conocidos de antemano.** El calendario de feriados se publica con anticipación, así que se usa para
  las fechas pronosticadas. Los traslados y puentes de Kaggle se tratan como conocidos; es un supuesto razonable,
  pero optimista.
- **Promociones del día pronosticado: no se usan.** En Kaggle `onpromotion` llega con las ventas, después del
  hecho. Usarla para fechas futuras sería fuga de información. Se usa la proporción de promoción de los últimos 28
  días. Si el negocio compartiera su plan de promociones, sería la primera feature a agregar.
- **Precio del petróleo:** se usa el último valor conocido antes del corte (relleno hacia adelante en feriados).
- **Limitación conocida:** al entrenar sobre la historia, las features de cortes pasados se calculan con los datos
  ya corregidos, no con la versión exacta que se conocía en cada corte. Para pronosticar sí se usa siempre la
  versión conocida en el corte. Reconstruir la historia de entregas para entrenar es posible, pero el efecto es
  pequeño (el 4 % de los días tiene una tienda corregida).

## 3. Validación de los datos

- **Qué se valida** (`fuentes.validar`): columnas obligatorias, fechas legibles y anteriores a la entrega,
  numéricos no vacíos y no negativos, petróleo positivo cuando existe, tiendas y familias conocidas (según la carga
  histórica) y llaves no duplicadas.
- **La entrega completa se rechaza**, no solo las filas malas. Una entrega parcial es difícil de interpretar
  (¿falta un dato o es cero?), y el sistema de origen la reenvía. La alternativa de cargar solo las filas válidas
  contaminaría los promedios con días incompletos.
- **Datos inválidos frente a situaciones esperadas.** Una entrega inválida queda en `data/cuarentena/` con su
  motivo, nunca llega a landing y hace fallar la tarea de `ingesta_diaria` de ese día, para que se vea en Airflow.
  El pronóstico la ignora y sigue con el resto. En cambio, no son errores: un día sin entregas de una fuente
  (fines de semana del petróleo, transacciones solo los lunes), una entrega tardía, una corrección o un día con
  todas las ventas en cero. Si no hay ventas en los 14 días anteriores al corte (por ejemplo, el run programado de
  hoy, sin datos), el pronóstico se *omite* (skipped) en lugar de fallar.
- **Una entrega vacía** (solo encabezado) es válida y no aporta filas; un archivo ilegible es inválido.

## 4. Correcciones y reprocesamiento

- **Gana la última entrega.** Si una fila (fecha, tienda, familia) llega más de una vez, `fuentes.panel` usa la
  entrega más reciente con fecha ≤ corte. Una corrección se aplica sin código especial y sin modificar la bandeja.
- **Lo publicado no se reescribe.** El pronóstico del corte C se hizo con lo que se sabía en C; corregirlo
  después borraría la evidencia de lo que el negocio recibió. Una corrección sí cambia los pronósticos
  posteriores (sus features) y el seguimiento, que siempre compara con la versión más reciente de las ventas.
- **Reproceso explícito:** volver a ejecutar un corte (`airflow backfill create … --reprocess-behavior completed`)
  produce el mismo resultado, porque el corte define qué entregas se usan. Si el sistema de origen reemplazara un
  archivo con el mismo nombre, el md5 cambia y la ingesta lo vuelve a validar y cargar.

## 5. Idempotencia

- Cada tarea escribe su partición (`landing/<fuente>/<entrega>.parquet`, `procesado/corte=C/`,
  `publicado/corte=C/`, `seguimiento/fecha=D.parquet`) con una escritura atómica (archivo temporal y `replace`).
  Repetirla reemplaza en lugar de duplicar.
- La ingesta compara el md5 de la entrega con el de la última carga: si es igual, no escribe (`sin_cambios`).
- El modelo de un corte se registra una sola vez: si ya existe la versión de ese corte, `entrenar_challenger` la
  devuelve y la compuerta vuelve a llegar a la misma decisión.
- `metadata.json` no lleva marcas de tiempo, para que dos ejecuciones iguales produzcan archivos idénticos (y el
  mismo hash en DVC).

## 6. Orquestación

- **Tres DAGs:** `ingesta_diaria` (validación y carga por fuente, con *dynamic task mapping*),
  `pronostico_semanal` (sincronizar, asegurar modelo, reentrenar, compuerta, preparar, pronosticar y pedido) y
  `seguimiento_diario`. Los DAGs solo orquestan: toda la lógica está en `src/reposicion/` y tiene pruebas.
- **El reentrenamiento vive dentro del DAG semanal**, como una rama que corre el primer lunes de cada mes. Con un
  DAG separado, un backfill podría ejecutar el reentrenamiento de agosto antes que el pronóstico de marzo. El
  pronóstico de marzo seguiría usando su modelo vigente (ver 7), pero el resultado dependería del orden de
  ejecución. Dentro del mismo DAG, con `max_active_runs=1`, el orden es determinista.
- **Cada DAG sincroniza la bandeja hasta su fecha** antes de trabajar, así no depende de que otro DAG haya
  corrido primero. La ingesta es idempotente, así que sincronizar varias veces no tiene costo de corrección.
- **Fecha lógica, nunca la de hoy:** todas las tareas reciben `ds`. `catchup=False` y los DAGs empiezan activos.
  El run programado más reciente (2026) no tiene datos y termina en *skipped*.

## 7. Modelado

- **Baseline (`Perfil`):** promedio de los últimos cuatro días iguales de la semana. Es simple, explica el patrón
  semanal y es el piso de comparación. Es también el primer modelo vigente.
- **LightGBM global con horizonte directo:** un solo modelo para las 1 782 series, con h como feature y objetivo
  Tweedie sobre las ventas. Se compararon variantes en dos cortes (WAPE de la mediana, validación / evaluación):

  | Variante | Corte 2017-02-06 | Corte 2017-06-05 |
  |---|---|---|
  | Baseline | 0.165 / 0.319 | 0.160 / 0.165 |
  | LightGBM, objetivo log(1+y) | 0.153 / 0.406 | — |
  | LightGBM, log(1+y) ponderado por volumen | 0.152 / 0.328 | 0.152 / 0.149 |
  | **LightGBM, Tweedie** | **0.149 / 0.239** | **0.156 / 0.147** |
  | LightGBM, Tweedie sin petróleo ni mes | 0.171 / 0.225 | 0.152 / 0.162 |

  Con objetivo logarítmico el modelo optimiza el error relativo de cada serie por igual y se equivoca en las de
  mayor volumen, que dominan el WAPE y el costo. Tweedie modela directamente las ventas con ceros y cola larga.
- **Incertidumbre:** cuantiles empíricos de los residuos (en escala log) de cada modelo en validación, por
  familia. Así se obtiene cualquier cuantil sin reentrenar, por lo que un cambio de costos no exige otro modelo.
  La alternativa, una regresión por cuantil, obligaría a entrenar un modelo por cada cuantil de pedido posible.
- **Deep learning:** no se usó. Con 1 782 series diarias y features tabulares, los modelos de árboles son el
  estado del arte práctico (por ejemplo, en la competencia M5) a una fracción del costo de entrenamiento e
  inferencia, y sin GPU. El beneficio esperado no justifica la complejidad operativa.

## 8. Validación temporal y criterio de reemplazo

- **Partición** (`entrenamiento.particion`), igual para todos los modelos y siempre relativa al corte:
  52 cortes semanales de entrenamiento, 4 de validación (calibran los cuantiles) y 4 de evaluación (decide la
  compuerta). Entre bloques hay 3 semanas, para que los 14 días pronosticados de un bloque no caigan dentro del
  siguiente. La evaluación termina antes del corte, así que ningún dato posterior al corte participa.
- **Métricas técnicas:** WAPE de la mediana, pinball promedio de p10, p50 y p90, y cobertura del intervalo
  p10–p90. **Métrica de negocio:** costo del pedido sugerido con `configs/costos.yaml`.
- **Compuerta** (`entrenamiento.decidir`, función pura con pruebas): el retador reemplaza al vigente si, en las
  mismas fechas de evaluación, baja el costo de negocio al menos 2 % y no empeora el WAPE. Si no pasa, la versión
  queda registrada como `descartado`, con el motivo.
- **Modelo vigente en un corte:** la versión inicial o promovida más reciente con corte ≤ C. Así un backfill nunca
  usa un modelo entrenado con datos posteriores a la fecha que procesa. El alias `@champion` del Registry apunta
  a la más reciente y `@anterior` a la que reemplazó.

## 9. Versionado

- **Git:** código, `params.yaml`, `configs/costos.yaml`, DAGs, pruebas y archivos `.dvc`.
- **DVC** (remoto local `../dvc-storage/reposicion-inventario`, como en el curso): datos de entrada
  (`data/kaggle`, `data/historico`, `bandeja`, `data/landing`), datos procesados (`data/procesado`), modelos
  (`models`) y pronósticos publicados (`data/publicado`). Un remoto en la nube (S3, Google Drive) permitiría
  compartirlo; para la evaluación no hace falta, porque el producto se reconstruye desde los archivos de Kaggle.
- **MLflow** guarda runs, métricas y el Registry, pero su base de datos no se versiona: cada modelo se guarda
  también en `models/` (DVC) y `metadata.json` de cada pronóstico apunta a ese archivo. La reproducción de un
  pronóstico no depende de MLflow.
- **Trazabilidad de cada pronóstico** (`data/publicado/corte=C/metadata.json`): versión, tipo y archivo del
  modelo, commit de Git, huella de los datos de entrada disponibles en C y md5 de los archivos de configuración.

## 10. Entorno

- Airflow 3.3.2 (Python 3.12) con LocalExecutor y Postgres en Docker Compose; MLflow 3.17.2 en su propio
  contenedor. Las versiones de pandas, numpy y pyarrow coinciden con las restricciones oficiales de Airflow 3.3.2,
  y el entorno local usa las mismas.
- MLflow se publica en el puerto 5001 del equipo: en macOS el 5000 lo ocupa el receptor de AirPlay.
- La autenticación de Airflow es *simple auth manager* con todos los usuarios administradores: es un entorno
  local de evaluación y así no hay credenciales que entregar.
