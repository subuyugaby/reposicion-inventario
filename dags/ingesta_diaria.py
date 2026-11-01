"""Ingesta y validación diaria: carga a landing las entregas que llegaron a la bandeja ese día.

Una entrega inválida no llega a landing (queda en data/cuarentena/) y la tarea falla para que se vea.
Un día sin entregas de una fuente es normal y no es un error.
"""

from datetime import date, datetime

from airflow.sdk.exceptions import AirflowFailException
from airflow.sdk import dag, task

from reposicion import fuentes


@dag(schedule="@daily", start_date=datetime(2013, 1, 1), catchup=False, max_active_runs=4,
     default_args={"retries": 1}, tags=["reposicion"])
def ingesta_diaria():

    @task
    def validar_y_cargar(fuente: str, ds=None) -> dict:
        estados = fuentes.ingerir_entregas(date.fromisoformat(ds), [fuente], solo_ese_dia=True)
        invalidas = [archivo for archivo, estado in estados.items() if estado == "invalido"]
        if invalidas:
            raise AirflowFailException(f"entregas inválidas, en cuarentena: {invalidas}")
        return estados

    validar_y_cargar.expand(fuente=list(fuentes.FUENTES))


ingesta_diaria()
