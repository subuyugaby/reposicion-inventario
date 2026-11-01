from datetime import date

import pandas as pd

from conftest import entregar
from reposicion import fuentes


def fila(fecha="2016-05-01", **cambios) -> pd.DataFrame:
    base = {"date": fecha, "store_nbr": "1", "family": "A", "sales": "3.5", "onpromotion": "0"}
    return pd.DataFrame([{**base, **cambios}])


def test_valida_entrega_correcta_y_rechaza_errores(proyecto):
    tiendas, familias = fuentes.maestros()
    df, errores = fuentes.validar(fila(), "ventas", date(2016, 5, 2), tiendas, familias)
    assert errores == [] and df["sales"].iloc[0] == 3.5
    for cambio in ({"sales": "-1"}, {"sales": ""}, {"store_nbr": "99"}, {"family": "Z"}, {"date": "2016-05-02"}):
        _, errores = fuentes.validar(fila(**cambio), "ventas", date(2016, 5, 2), tiendas, familias)
        assert errores, cambio
    _, errores = fuentes.validar(pd.concat([fila(), fila()]), "ventas", date(2016, 5, 2), tiendas, familias)
    assert errores == ["llaves duplicadas"]


def test_ingesta_es_idempotente_y_lo_invalido_va_a_cuarentena(proyecto):
    bueno = entregar(proyecto, "ventas", "2016-05-02", fila())
    assert fuentes.ingerir_entregas(date(2016, 5, 2)) == {bueno.name: "cargado"}
    assert fuentes.ingerir_entregas(date(2016, 5, 2)) == {bueno.name: "sin_cambios"}

    malo = entregar(proyecto, "ventas", "2016-05-03", fila(sales="-1"))
    assert fuentes.ingerir_entregas(date(2016, 5, 3), solo_ese_dia=True) == {malo.name: "invalido"}
    assert not (proyecto / "data/landing/ventas/ventas_2016-05-03.parquet").exists()
    assert (proyecto / "data/cuarentena/ventas/ventas_2016-05-03.json").exists()


def test_panel_respeta_la_fecha_de_corte_y_aplica_correcciones(proyecto):
    entregar(proyecto, "ventas", "2016-05-02", fila(sales="3"))
    entregar(proyecto, "ventas", "2016-05-06", fila(sales="7"))  # corrección del 1 de mayo
    fuentes.ingerir_entregas(date(2016, 5, 6))

    def valor(corte):
        v = fuentes.panel("ventas", corte)
        return v.loc[(v["date"] == "2016-05-01") & (v["store_nbr"] == 1) & (v["family"] == "A"), "sales"].tolist()

    assert valor(date(2016, 5, 1)) == []
    assert valor(date(2016, 5, 2)) == [3.0]
    assert valor(date(2016, 5, 6)) == [7.0]
