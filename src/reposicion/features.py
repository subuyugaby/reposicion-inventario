"""Features para pronosticar desde una fecha de corte. Solo usan información anterior al corte."""

import warnings
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from reposicion import config, fuentes

VENTANAS = (7, 14, 28, 56)
CATEGORICAS = ["store_nbr", "family", "tipo", "cluster"]
FEATURES = CATEGORICAS + [
    "h", "dia_semana", "dia_mes", "mes", "dia_pago", "feriado_nacional", "feriado_regional", "feriado_local",
    "m7", "m14", "m28", "m56", "std28", "ceros28", "promo28", "ultimo", "mismo_dia_4s", "tendencia",
    "trans28", "petroleo", "petroleo_var28",
]


@dataclass
class Datos:
    """Ventas, promociones y transacciones en matrices fechas x series, más el calendario de feriados."""
    fechas: pd.DatetimeIndex
    series: pd.DataFrame  # una fila por (tienda, familia), con los atributos de la tienda
    ventas: np.ndarray
    promo: np.ndarray
    trans: np.ndarray
    petroleo: np.ndarray
    feriados: pd.DataFrame


def construir(ventas, transacciones, petroleo, feriados, tiendas, hasta) -> Datos:
    fechas = pd.date_range(ventas["date"].min(), hasta, freq="D")
    indice = pd.MultiIndex.from_product(
        [sorted(tiendas["store_nbr"]), sorted(ventas["family"].unique())], names=["store_nbr", "family"])
    series = indice.to_frame(index=False).merge(
        tiendas.rename(columns={"type": "tipo"})[["store_nbr", "city", "state", "tipo", "cluster"]],
        on="store_nbr", how="left")

    def ancho(valor):
        tabla = ventas.pivot(index="date", columns=["store_nbr", "family"], values=valor)
        return tabla.reindex(index=fechas, columns=indice).to_numpy(float)

    trans = (transacciones.pivot(index="date", columns="store_nbr", values="transactions")
             .reindex(index=fechas, columns=series["store_nbr"]).to_numpy(float))
    oil = petroleo.set_index("date")["dcoilwtico"].reindex(fechas).ffill().to_numpy(float)
    return Datos(fechas, series, ancho("sales"), ancho("onpromotion"), trans, oil, feriados)


def datos_al_corte(corte: date) -> Datos:
    """Datos tal como se conocían en la fecha de corte, sin ninguna fila del corte en adelante."""
    limite = pd.Timestamp(corte)
    paneles = {f: fuentes.panel(f, corte) for f in fuentes.FUENTES}
    paneles = {f: df[df["date"] < limite] for f, df in paneles.items()}
    historico = config.ruta("historico")
    return construir(paneles["ventas"], paneles["transacciones"], paneles["petroleo"],
                     pd.read_parquet(historico / "feriados.parquet"),
                     pd.read_parquet(historico / "tiendas.parquet"), limite - pd.Timedelta(days=1))


def _media(m: np.ndarray, axis=0) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(m, axis=axis)


def features(d: Datos, corte, horizonte: int, con_objetivo: bool = False) -> pd.DataFrame:
    """Una fila por serie y por día del horizonte (h = 1 … horizonte días después del corte)."""
    corte = pd.Timestamp(corte)
    fin = d.fechas.get_loc(corte - pd.Timedelta(days=1))  # último día que puede conocerse
    if fin < max(VENTANAS):
        raise ValueError(f"historia insuficiente antes de {corte.date()}")
    ventana = d.ventas[fin - 27: fin + 1]
    base = {f"m{k}": _media(d.ventas[fin - k + 1: fin + 1]) for k in VENTANAS}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        base["std28"] = np.nanstd(ventana, axis=0)
    base["ceros28"] = _media(np.where(np.isnan(ventana), np.nan, (ventana == 0).astype(float)))
    base["promo28"] = _media(d.promo[fin - 27: fin + 1])
    base["ultimo"] = d.ventas[fin]
    base["tendencia"] = base["m7"] / (base["m28"] + 1)
    base["trans28"] = _media(d.trans[fin - 27: fin + 1])
    base["petroleo"] = np.full(len(d.series), d.petroleo[fin])
    base["petroleo_var28"] = np.full(len(d.series), d.petroleo[fin] / d.petroleo[fin - 28] - 1)
    dias = d.fechas[fin - 27: fin + 1].dayofweek
    mismo_dia = {dow: _media(ventana[dias == dow]) for dow in range(7)}

    partes = []
    for h in range(1, horizonte + 1):
        fecha = corte + pd.Timedelta(days=h)
        parte = d.series[["store_nbr", "family", "tipo", "cluster"]].copy()
        parte = parte.assign(**base, mismo_dia_4s=mismo_dia[fecha.dayofweek], h=h,
                             dia_semana=fecha.dayofweek, dia_mes=fecha.day, mes=fecha.month,
                             dia_pago=int(fecha.day == 15 or fecha.is_month_end))
        f = d.feriados[d.feriados["date"] == fecha]
        parte["feriado_nacional"] = int((f["locale"] == "National").any())
        parte["feriado_regional"] = d.series["state"].isin(f.loc[f["locale"] == "Regional", "locale_name"]).astype(int)
        parte["feriado_local"] = d.series["city"].isin(f.loc[f["locale"] == "Local", "locale_name"]).astype(int)
        parte["corte"] = corte
        parte["fecha"] = fecha
        if con_objetivo:
            pos = d.fechas.get_indexer([fecha])[0]
            parte["objetivo"] = d.ventas[pos] if pos >= 0 else np.nan
        partes.append(parte)
    return categorizar(pd.concat(partes, ignore_index=True))


def categorizar(df: pd.DataFrame) -> pd.DataFrame:
    """Columnas categóricas con el mismo tipo con que se entrenó (el parquet no siempre lo conserva)."""
    for col in CATEGORICAS:
        df[col] = df[col].astype(str if col in ("family", "tipo") else "int64").astype("category")
    return df


def leer(ruta) -> pd.DataFrame:
    return categorizar(pd.read_parquet(ruta))


def dataset(d: Datos, cortes: list, horizonte: int) -> pd.DataFrame:
    """Features y objetivo de varias fechas de corte; solo filas cuyo valor real ya se conoce."""
    df = pd.concat([features(d, c, horizonte, con_objetivo=True) for c in cortes], ignore_index=True)
    return df[df["objetivo"].notna()].reset_index(drop=True)
