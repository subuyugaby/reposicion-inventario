"""Costos de negocio, cuantil del pedido y métricas del pronóstico."""

import numpy as np
import pandas as pd

from reposicion import config


def costos_familia(familias, costos: dict | None = None) -> pd.DataFrame:
    """Costo de faltante y de sobrante por familia, y el cuantil óptimo del pedido (newsvendor)."""
    costos = costos or config.costos()
    filas = []
    for familia in familias:
        grupo = "perecederos" if familia in costos["perecederos"]["familias"] else "por_defecto"
        filas.append({"family": str(familia), "faltante": costos[grupo]["faltante"],
                      "sobrante": costos[grupo]["sobrante"]})
    df = pd.DataFrame(filas)
    df["cuantil_pedido"] = df["faltante"] / (df["faltante"] + df["sobrante"])
    return df


def costo(real, pedido, faltante, sobrante) -> np.ndarray:
    real, pedido = np.asarray(real, float), np.asarray(pedido, float)
    return faltante * np.maximum(real - pedido, 0) + sobrante * np.maximum(pedido - real, 0)


def wape(real, pronostico) -> float:
    real = np.asarray(real, float)
    return float(np.abs(real - np.asarray(pronostico, float)).sum() / max(real.sum(), 1e-9))


def pinball(real, pronostico, q: float) -> float:
    diferencia = np.asarray(real, float) - np.asarray(pronostico, float)
    return float(np.mean(np.maximum(q * diferencia, (q - 1) * diferencia)))


def evaluar(modelo, datos: pd.DataFrame, cuantiles: list, costos: dict | None = None) -> dict:
    """Métricas técnicas y costo de negocio de un modelo sobre filas con valor real conocido."""
    c = datos[["family"]].astype(str).merge(costos_familia(datos["family"].unique(), costos), on="family", how="left")
    real = datos["objetivo"].to_numpy()
    p = {q: modelo.cuantil(datos, q) for q in cuantiles}
    pedido = modelo.cuantil(datos, c["cuantil_pedido"].to_numpy())
    total = costo(real, pedido, c["faltante"].to_numpy(), c["sobrante"].to_numpy()).sum()
    return {
        "wape": wape(real, p[0.5]),
        "pinball": float(np.mean([pinball(real, p[q], q) for q in cuantiles])),
        "cobertura": float(np.mean((real >= p[min(cuantiles)]) & (real <= p[max(cuantiles)]))),
        "costo": float(total),
        "costo_relativo": float(total / max(real.sum(), 1e-9)),
    }
