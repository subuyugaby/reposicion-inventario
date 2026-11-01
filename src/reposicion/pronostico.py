"""Preparación, pronóstico, pedido sugerido y publicación para una fecha de corte."""

import json
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from reposicion import config, entrenamiento, fuentes, negocio
from reposicion.features import datos_al_corte, features, leer
from reposicion.fuentes import guardar


class SinDatosRecientes(Exception):
    """No hay ventas recientes antes del corte: es una situación esperada, no un error."""


def carpeta(nombre: str, corte: date) -> Path:
    return config.ruta(nombre) / f"corte={corte.isoformat()}"


def verificar_frescura(corte: date) -> date:
    ventas = fuentes.panel("ventas", corte)
    ultimo = ventas.loc[ventas["date"] < pd.Timestamp(corte), "date"].max()
    limite = config.params()["pronostico"]["max_dias_sin_ventas"]
    if pd.isna(ultimo) or (pd.Timestamp(corte) - ultimo).days > limite:
        raise SinDatosRecientes(f"corte {corte}: la última venta conocida es {ultimo}; no se publica")
    return ultimo.date()


def calcular_pronostico(X: pd.DataFrame, modelo, cuantiles: list) -> pd.DataFrame:
    df = X[["corte", "fecha", "h", "store_nbr", "family"]].astype({"store_nbr": "int64", "family": str})
    for q in cuantiles:
        df[f"p{round(q * 100)}"] = np.round(modelo.cuantil(X, q), 3)
    return df


def calcular_pedido(X: pd.DataFrame, modelo, dias_pedido: int, costos: dict | None = None) -> pd.DataFrame:
    """Pedido por día, tienda y familia: el cuantil faltante / (faltante + sobrante) del pronóstico."""
    X = X[X["h"] <= dias_pedido].reset_index(drop=True)
    c = X[["family"]].astype(str).merge(negocio.costos_familia(X["family"].unique(), costos), on="family", how="left")
    df = X[["corte", "fecha", "store_nbr", "family"]].astype({"store_nbr": "int64", "family": str})
    df["cuantil_pedido"] = c["cuantil_pedido"].round(4)
    df["pedido"] = np.ceil(modelo.cuantil(X, c["cuantil_pedido"].to_numpy()))
    return df


def preparar(corte: date) -> dict:
    ultimo = verificar_frescura(corte)
    X = features(datos_al_corte(corte), corte, config.params()["pronostico"]["horizonte"])
    guardar(X, carpeta("procesado", corte) / "features.parquet")
    return {"filas": len(X), "ultimo_dia_ventas": ultimo.isoformat()}


def pronosticar(corte: date) -> dict:
    p = config.params()
    X = leer(carpeta("procesado", corte) / "features.parquet")
    version = entrenamiento.vigente(corte)
    pronostico = calcular_pronostico(X, entrenamiento.cargar(version), p["pronostico"]["cuantiles"])
    destino = carpeta("publicado", corte)
    guardar(pronostico, destino / "pronostico.parquet")
    metadata = {
        "corte": corte.isoformat(),
        "modelo": {k: version[k] for k in ("version", "tipo", "corte", "ruta")},
        "git_commit": config.git_commit(),
        "huella_datos": fuentes.huella_datos(corte),
        "costos_md5": config.md5(config.raiz() / "configs" / "costos.yaml"),
        "params_md5": config.md5(config.raiz() / "params.yaml"),
        "filas": len(pronostico),
    }
    (destino / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    return metadata


def generar_pedido(corte: date) -> dict:
    destino = carpeta("publicado", corte)
    metadata = json.loads((destino / "metadata.json").read_text())
    X = leer(carpeta("procesado", corte) / "features.parquet")
    modelo = joblib.load(config.raiz() / metadata["modelo"]["ruta"])
    pedido = calcular_pedido(X, modelo, config.params()["pronostico"]["dias_pedido"])
    guardar(pedido, destino / "pedido.parquet")
    return {"filas": len(pedido), "unidades": float(pedido["pedido"].sum())}
