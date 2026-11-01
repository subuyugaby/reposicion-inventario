"""Pronóstico y pedido sugerido de cada lunes, con reentrenamiento mensual y compuerta de promoción.

Todo usa la fecha lógica del run (el corte), nunca la fecha de hoy: un backfill reproduce lo que se
habría publicado cada lunes con la información disponible ese día.
"""

from datetime import date, datetime

from airflow.sdk.exceptions import AirflowSkipException
from airflow.sdk import dag, task

from reposicion import entrenamiento, fuentes, pronostico


def _corte(ds) -> date:
    return date.fromisoformat(ds)


def _con_datos(paso, corte: date):
    try:
        return paso(corte)
    except pronostico.SinDatosRecientes as e:
        raise AirflowSkipException(str(e))


@dag(schedule="0 6 * * 1", start_date=datetime(2013, 1, 7), catchup=False, max_active_runs=1,
     default_args={"retries": 1}, tags=["reposicion"])
def pronostico_semanal():

    @task
    def sincronizar_bandeja(ds=None) -> dict:
        """Carga cualquier entrega pendiente hasta el corte; las inválidas se ignoran (están en cuarentena)."""
        estados = fuentes.ingerir_entregas(_corte(ds))
        return {e: sum(1 for v in estados.values() if v == e) for e in set(estados.values())}

    @task
    def asegurar_modelo(ds=None) -> dict:
        """Sin modelo vigente en el corte, registra el baseline. Sin ventas recientes, no hay nada que hacer."""
        ultimo = _con_datos(pronostico.verificar_frescura, _corte(ds))
        return {"ultimo_dia_ventas": ultimo.isoformat(), **entrenamiento.asegurar_modelo(_corte(ds))}

    @task
    def entrenar_challenger(ds=None) -> dict:
        if not entrenamiento.toca_reentrenar(_corte(ds)):
            raise AirflowSkipException("no es semana de reentrenamiento")
        return entrenamiento.entrenar_challenger(_corte(ds))

    @task.branch
    def compuerta(version: dict) -> str:
        promovido, _ = entrenamiento.aplicar_compuerta(version)
        return "promover" if promovido else "descartar"

    @task
    def promover(version: dict) -> None:
        entrenamiento.cerrar(version, True, entrenamiento.aplicar_compuerta(version)[1])

    @task
    def descartar(version: dict) -> None:
        entrenamiento.cerrar(version, False, entrenamiento.aplicar_compuerta(version)[1])

    @task(trigger_rule="none_failed")
    def preparar(ds=None) -> dict:
        return _con_datos(pronostico.preparar, _corte(ds))

    @task
    def pronosticar(ds=None) -> dict:
        return pronostico.pronosticar(_corte(ds))

    @task
    def generar_pedido(ds=None) -> dict:
        return pronostico.generar_pedido(_corte(ds))

    version = entrenar_challenger()
    sincronizar_bandeja() >> asegurar_modelo() >> version
    decision = compuerta(version)
    caminos = [promover(version), descartar(version)]
    decision >> caminos
    caminos >> preparar() >> pronosticar() >> generar_pedido()


pronostico_semanal()
