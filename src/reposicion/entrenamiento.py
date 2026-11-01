"""Entrenamiento, evaluación y compuerta de promoción, con MLflow Tracking y Model Registry.

Cada versión registrada lleva como tags su fecha de corte, su tipo, la decisión de la compuerta y la ruta
del modelo en models/ (versionada con DVC). El modelo vigente en una fecha de corte es la versión inicial
o promovida más reciente con corte <= esa fecha: un backfill nunca usa un modelo entrenado con datos
posteriores a la fecha que procesa.
"""

import json
import math
from datetime import date

import joblib
import pandas as pd

from reposicion import config, fuentes, negocio
from reposicion.features import dataset, datos_al_corte
from reposicion.modelos import LightGBM, Perfil


def particion(corte, horizonte: int, p_modelo: dict) -> tuple[list, list, list]:
    """Fechas de corte de entrenamiento, validación y evaluación, en semanas anteriores al corte.
    Entre bloques hay un salto para que ningún objetivo de un bloque caiga dentro del siguiente."""
    salto = pd.Timedelta(weeks=math.ceil((horizonte + 1) / 7))

    def bloque(ultimo, n):
        return [ultimo - pd.Timedelta(weeks=k) for k in range(n - 1, -1, -1)]

    evaluacion = bloque(pd.Timestamp(corte) - salto, p_modelo["semanas_evaluacion"])
    validacion = bloque(evaluacion[0] - salto, p_modelo["semanas_validacion"])
    entrenamiento = bloque(validacion[0] - salto, p_modelo["semanas_entrenamiento"])
    return entrenamiento, validacion, evaluacion


def decidir(campeon: dict, retador: dict, reglas: dict) -> tuple[bool, str]:
    """Compuerta: el retador reemplaza al vigente solo si baja el costo de negocio lo suficiente
    sin empeorar el WAPE. Ambos se miden en las mismas fechas de evaluación."""
    mejora = 1 - retador["costo"] / campeon["costo"]
    if mejora < reglas["mejora_minima_costo"]:
        return False, f"mejora de costo {mejora:.1%}, menor que el mínimo de {reglas['mejora_minima_costo']:.0%}"
    if retador["wape"] > campeon["wape"] + reglas["max_aumento_wape"]:
        return False, f"el WAPE empeora de {campeon['wape']:.3f} a {retador['wape']:.3f}"
    return True, f"mejora de costo {mejora:.1%}; WAPE {campeon['wape']:.3f} -> {retador['wape']:.3f}"


# ----------------------------------------------------------------------
# Model Registry
# ----------------------------------------------------------------------

def _nombre() -> str:
    return config.params()["modelo"]["nombre_registro"]


def _cliente():
    from mlflow import MlflowClient
    return MlflowClient()


def versiones() -> list[dict]:
    vs = _cliente().search_model_versions(f"name='{_nombre()}'")
    return sorted(({"version": int(v.version), **v.tags} for v in vs), key=lambda v: v["version"])


def vigente(corte: date) -> dict | None:
    iso = corte.isoformat()
    candidatas = [v for v in versiones() if v.get("decision") in ("inicial", "promovido") and v["corte"] <= iso]
    return max(candidatas, key=lambda v: (v["corte"], v["version"]), default=None)


def cargar(version: dict):
    return joblib.load(config.raiz() / version["ruta"])


def registrar(modelo, corte: date, metricas: dict, decision: str, motivo: str, extra: dict | None = None) -> dict:
    """Guarda el modelo en models/, registra el run en MLflow y crea una versión en el Model Registry."""
    import mlflow

    ruta = f"{config.params()['rutas']['modelos']}/{modelo.tipo}_{corte.isoformat()}.joblib"
    (config.raiz() / ruta).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, config.raiz() / ruta)
    mlflow.set_experiment(_nombre())
    with mlflow.start_run(run_name=f"{modelo.tipo}-{corte.isoformat()}") as run:
        mlflow.log_params({"tipo": modelo.tipo, "corte": corte.isoformat(), **getattr(modelo, "hiperparametros", {})})
        mlflow.log_metrics({f"eval_{k}": v for k, v in metricas.items()})
        mlflow.set_tags({"git_commit": config.git_commit(), "huella_datos": fuentes.huella_datos(corte),
                         "costos_md5": config.md5(config.raiz() / "configs" / "costos.yaml")})
        mlflow.log_artifact(str(config.raiz() / ruta), artifact_path="modelo")
    cliente = _cliente()
    if not cliente.search_registered_models(f"name='{_nombre()}'"):
        cliente.create_registered_model(_nombre())
    tags = {"tipo": modelo.tipo, "corte": corte.isoformat(), "decision": decision, "motivo": motivo,
            "ruta": ruta, "metricas": json.dumps(metricas), **(extra or {})}
    mv = cliente.create_model_version(_nombre(), source=f"{run.info.artifact_uri}/modelo",
                                      run_id=run.info.run_id, tags=tags)
    return {"version": int(mv.version), **tags}


def _mover_champion(version: dict) -> None:
    """@champion apunta a la versión vigente más reciente; la anterior queda en @anterior."""
    cliente = _cliente()
    try:
        actual = cliente.get_model_version_by_alias(_nombre(), "champion")
    except Exception:
        actual = None
    if actual is None or actual.tags["corte"] <= version["corte"]:
        if actual is not None and int(actual.version) != version["version"]:
            cliente.set_registered_model_alias(_nombre(), "anterior", actual.version)
        cliente.set_registered_model_alias(_nombre(), "champion", str(version["version"]))


# ----------------------------------------------------------------------
# Pasos que orquesta Airflow
# ----------------------------------------------------------------------

def asegurar_modelo(corte: date) -> dict:
    """Si en la fecha de corte no hay modelo vigente, registra el baseline como modelo inicial."""
    actual = vigente(corte)
    if actual:
        return actual
    p = config.params()
    h = p["pronostico"]["horizonte"]
    d = datos_al_corte(corte)
    _, validacion, evaluacion = particion(corte, h, p["modelo"])
    modelo = Perfil().calibrar(dataset(d, validacion, h))
    metricas = negocio.evaluar(modelo, dataset(d, evaluacion, h), p["pronostico"]["cuantiles"])
    version = registrar(modelo, corte, metricas, "inicial", "primer modelo vigente: baseline")
    _mover_champion(version)
    escribir_reporte()
    return version


def toca_reentrenar(corte: date) -> bool:
    """Se reentrena el primer lunes de cada mes, o si todavía no hay ningún challenger."""
    previos = [v for v in versiones() if v["tipo"] == "lightgbm" and v["corte"] <= corte.isoformat()]
    return corte.day <= 7 or not previos


def entrenar_challenger(corte: date) -> dict:
    """Entrena LightGBM con los datos disponibles en el corte y lo evalúa junto al modelo vigente,
    en las mismas fechas de evaluación. Idempotente: si ya existe la versión de ese corte, la devuelve."""
    existente = next((v for v in versiones() if v["tipo"] == "lightgbm" and v["corte"] == corte.isoformat()), None)
    if existente:
        return existente
    p = config.params()
    h, cuantiles = p["pronostico"]["horizonte"], p["pronostico"]["cuantiles"]
    campeon = vigente(corte)
    d = datos_al_corte(corte)
    entrenamiento, validacion, evaluacion = particion(corte, h, p["modelo"])
    retador = LightGBM(p["modelo"]["lightgbm"], p["seed"]).ajustar(dataset(d, entrenamiento, h))
    retador.calibrar(dataset(d, validacion, h))
    datos_eval = dataset(d, evaluacion, h)
    metricas_campeon = negocio.evaluar(cargar(campeon), datos_eval, cuantiles)
    return registrar(retador, corte, negocio.evaluar(retador, datos_eval, cuantiles), "pendiente", "",
                     {"campeon_version": str(campeon["version"]), "metricas_campeon": json.dumps(metricas_campeon)})


def aplicar_compuerta(version: dict) -> tuple[bool, str]:
    return decidir(json.loads(version["metricas_campeon"]), json.loads(version["metricas"]),
                   config.params()["promocion"])


def cerrar(version: dict, promovido: bool, motivo: str) -> None:
    cliente = _cliente()
    cliente.set_model_version_tag(_nombre(), str(version["version"]), "decision",
                                  "promovido" if promovido else "descartado")
    cliente.set_model_version_tag(_nombre(), str(version["version"]), "motivo", motivo)
    if promovido:
        _mover_champion(version)
    escribir_reporte()


def escribir_reporte() -> None:
    """reportes/comparacion_modelos.md: todas las versiones del Registry y la decisión de la compuerta."""
    filas = ["| Versión | Tipo | Corte | Costo | Costo vigente | WAPE | WAPE vigente | Cobertura 80 % | Decisión | Motivo |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for v in versiones():
        m = json.loads(v["metricas"])
        c = json.loads(v.get("metricas_campeon", "{}"))
        costo_vigente = f"v{v['campeon_version']}: {c['costo']:,.0f}" if c else "—"
        wape_vigente = f"{c['wape']:.3f}" if c else "—"
        filas.append(f"| v{v['version']} | {v['tipo']} | {v['corte']} | {m['costo']:,.0f} | {costo_vigente} | "
                     f"{m['wape']:.3f} | {wape_vigente} | {m['cobertura']:.1%} | {v['decision']} | {v['motivo']} |")
    texto = ("# Comparación de modelos\n\n"
             "Cada fila es una versión del Model Registry. El retador y el modelo vigente se miden en las mismas "
             "fechas de corte de evaluación, que ninguno usó para entrenar ni calibrar. Costo: costo de negocio "
             "del pedido sugerido con configs/costos.yaml.\n\n" + "\n".join(filas) + "\n")
    destino = config.ruta("reportes") / "comparacion_modelos.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
