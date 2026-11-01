"""Modelos de pronóstico.

Cada modelo predice log(1 + ventas). La incertidumbre se expresa con los cuantiles de sus residuos en
validación, por familia: así se obtiene cualquier cuantil (y por lo tanto el pedido para cualquier costo)
sin reentrenar.
"""

import lightgbm as lgb
import numpy as np
import pandas as pd

from reposicion.features import FEATURES

GRILLA = np.round(np.linspace(0.01, 0.99, 99), 2)


class Modelo:
    tipo = ""

    def ajustar(self, datos: pd.DataFrame) -> "Modelo":
        return self

    def predecir_log(self, X: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError

    def calibrar(self, datos: pd.DataFrame) -> "Modelo":
        residuo = np.log1p(datos["objetivo"].to_numpy()) - self.predecir_log(datos)
        self.residuos = {"_todas": np.quantile(residuo, GRILLA)}
        for familia, idx in datos.groupby("family", observed=True).indices.items():
            self.residuos[familia] = np.quantile(residuo[idx], GRILLA)
        return self

    def cuantil(self, X: pd.DataFrame, q) -> np.ndarray:
        """Cuantil q del pronóstico; q puede ser un número o un valor por fila."""
        q = np.broadcast_to(np.asarray(q, dtype=float), (len(X),))
        ajuste = np.empty(len(X))
        for familia, idx in X.groupby("family", observed=True).indices.items():
            ajuste[idx] = np.interp(q[idx], GRILLA, self.residuos.get(familia, self.residuos["_todas"]))
        return np.clip(np.expm1(self.predecir_log(X) + ajuste), 0, None)


class Perfil(Modelo):
    """Baseline: promedio de los últimos cuatro días iguales de la semana."""
    tipo = "perfil"

    def predecir_log(self, X):
        return np.log1p(X["mismo_dia_4s"].fillna(X["m28"]).fillna(0).to_numpy())


class LightGBM(Modelo):
    """Modelo global para todas las series, con un horizonte directo (h es una feature).
    Objetivo Tweedie sobre las ventas: muchas series tienen ceros y una cola larga."""
    tipo = "lightgbm"

    def __init__(self, hiperparametros: dict, seed: int):
        self.hiperparametros = hiperparametros
        self.seed = seed

    def ajustar(self, datos):
        self.modelo = lgb.LGBMRegressor(**self.hiperparametros, random_state=self.seed,
                                        deterministic=True, force_row_wise=True, verbose=-1)
        self.modelo.fit(datos[FEATURES], datos["objetivo"])
        return self

    def predecir_log(self, X):
        return np.log1p(np.clip(self.modelo.predict(X[FEATURES]), 0, None))
