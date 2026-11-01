"""Seguimiento diario del desempeño: compara lo publicado con las ventas reales conocidas ese día."""

from datetime import date, datetime

from airflow.sdk import dag, task

from reposicion import fuentes, seguimiento


@dag(schedule="@daily", start_date=datetime(2013, 1, 1), catchup=False, max_active_runs=1,
     default_args={"retries": 1}, tags=["reposicion"])
def seguimiento_diario():

    @task
    def sincronizar_bandeja(ds=None) -> int:
        return len(fuentes.ingerir_entregas(date.fromisoformat(ds)))

    @task
    def evaluar_publicados(ds=None) -> int:
        return len(seguimiento.evaluar(date.fromisoformat(ds)))

    sincronizar_bandeja() >> evaluar_publicados()


seguimiento_diario()
