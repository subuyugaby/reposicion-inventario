import pandas as pd

from reposicion import config, features, negocio
from reposicion.entrenamiento import decidir, particion
from reposicion.modelos import Perfil
from reposicion.pronostico import calcular_pedido

CORTE = pd.Timestamp("2016-04-11")


def construir(ventas: pd.DataFrame) -> features.Datos:
    h = config.ruta("historico")
    return features.construir(ventas, pd.read_parquet(h / "transacciones.parquet"),
                              pd.read_parquet(h / "petroleo.parquet"), pd.read_parquet(h / "feriados.parquet"),
                              pd.read_parquet(h / "tiendas.parquet"), pd.Timestamp("2016-04-30"))


def test_features_no_usan_datos_del_corte_en_adelante(proyecto):
    ventas = pd.read_parquet(config.ruta("historico") / "ventas.parquet")
    alterado = ventas.copy()
    alterado.loc[alterado["date"] >= CORTE, "sales"] = 1e6
    pd.testing.assert_frame_equal(features.features(construir(ventas), CORTE, 14),
                                  features.features(construir(alterado), CORTE, 14))


def test_particion_temporal_sin_cruce_de_objetivos():
    p = {"semanas_entrenamiento": 52, "semanas_validacion": 4, "semanas_evaluacion": 4}
    corte, h = pd.Timestamp("2017-06-05"), pd.Timedelta(days=14)
    entrenamiento, validacion, evaluacion = particion(corte, 14, p)
    assert len(entrenamiento) == 52 and len(validacion) == 4 and len(evaluacion) == 4
    assert max(entrenamiento) + h < min(validacion)
    assert max(validacion) + h < min(evaluacion)
    assert max(evaluacion) + h < corte


def test_cuantil_del_pedido_sale_de_los_costos():
    costos = {"por_defecto": {"faltante": 1, "sobrante": 0.25},
              "perecederos": {"familias": ["PRODUCE"], "faltante": 1, "sobrante": 1}}
    c = negocio.costos_familia(["PRODUCE", "AUTOMOTIVE"], costos)
    assert c.set_index("family")["cuantil_pedido"].to_dict() == {"PRODUCE": 0.5, "AUTOMOTIVE": 0.8}
    assert negocio.costo(10, 8, 1, 0.25) == 2 and negocio.costo(10, 12, 1, 0.25) == 0.5


def test_pedido_cambia_con_los_costos_sin_reentrenar(proyecto):
    d = construir(pd.read_parquet(config.ruta("historico") / "ventas.parquet"))
    modelo = Perfil().calibrar(features.dataset(d, [CORTE - pd.Timedelta(weeks=k) for k in range(3, 7)], 14))
    X = features.features(d, CORTE, 14)

    def pedido(faltante, sobrante):
        costos = {"por_defecto": {"faltante": faltante, "sobrante": sobrante},
                  "perecederos": {"familias": [], "faltante": 1, "sobrante": 1}}
        return calcular_pedido(X, modelo, 7, costos)["pedido"]

    bajo, alto = pedido(1, 4), pedido(4, 1)
    assert (alto >= bajo).all() and alto.sum() > bajo.sum()


def test_compuerta_de_promocion():
    reglas = {"mejora_minima_costo": 0.02, "max_aumento_wape": 0.0}
    vigente = {"costo": 100, "wape": 0.20}
    assert decidir(vigente, {"costo": 97, "wape": 0.19}, reglas)[0]
    assert not decidir(vigente, {"costo": 99, "wape": 0.19}, reglas)[0]   # mejora insuficiente
    assert not decidir(vigente, {"costo": 90, "wape": 0.21}, reglas)[0]   # empeora el WAPE
