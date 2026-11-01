"""Simulación del sistema de origen: carga histórica y bandeja de entregas a partir de los archivos de Kaggle.

Reglas de llegada (una entrega por fecha y por fuente):
- ventas: las de un día llegan al día siguiente; algunos días llegan de 2 a 4 días tarde; algunos días
  llegan con un error en una tienda y la corrección llega de 4 a 7 días después; algunas entregas traen
  datos inválidos y su contenido se reenvía en la entrega del día siguiente.
- transacciones: cada lunes, las de la semana anterior.
- petróleo: el precio de un día hábil llega al día siguiente.
- feriados y tiendas: son datos maestros conocidos de antemano; van completos en la carga histórica.
"""

import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from reposicion.fuentes import FUENTES, tipar

ARCHIVOS = {"ventas": "train.csv", "transacciones": "transactions.csv", "petroleo": "oil.csv"}
DIA = pd.Timedelta(days=1)


def leer_kaggle(kaggle: Path):
    datos = {fuente: tipar(pd.read_csv(kaggle / archivo), fuente) for fuente, archivo in ARCHIVOS.items()}
    feriados = pd.read_csv(kaggle / "holidays_events.csv")
    # Un feriado trasladado no se celebra ese día; un "Work Day" es un día laboral que recupera un puente.
    feriados = feriados[(feriados["type"] != "Work Day") & ~feriados["transferred"].astype(bool)].copy()
    feriados["date"] = pd.to_datetime(feriados["date"]).astype("datetime64[ns]")
    tiendas = pd.read_csv(kaggle / "stores.csv")
    return datos, feriados[["date", "type", "locale", "locale_name", "description"]], tiendas


def generar(kaggle: Path, historico: Path, bandeja: Path, inicio, p: dict, seed: int) -> dict:
    datos, feriados, tiendas = leer_kaggle(kaggle)
    inicio = pd.Timestamp(inicio)
    historico.mkdir(parents=True, exist_ok=True)
    for fuente, df in datos.items():
        df[df["date"] < inicio].to_parquet(historico / f"{fuente}.parquet", index=False)
    feriados.to_parquet(historico / "feriados.parquet", index=False)
    tiendas.to_parquet(historico / "tiendas.parquet", index=False)

    rng = np.random.default_rng(seed)
    entregas = defaultdict(list)  # (fuente, fecha de entrega) -> partes
    ventas = datos["ventas"][datos["ventas"]["date"] >= inicio]
    for fecha, grupo in ventas.groupby("date"):
        u = rng.random()
        if u < p["prob_retraso_ventas"]:
            entregas[("ventas", fecha + DIA * int(rng.integers(2, 5)))].append(grupo)
        elif u < p["prob_retraso_ventas"] + p["prob_correccion_ventas"]:
            afectada = grupo["store_nbr"] == rng.choice(grupo["store_nbr"].unique())
            erroneo = grupo.copy()
            erroneo.loc[afectada, "sales"] = (erroneo.loc[afectada, "sales"] * 0.5).round(3)
            entregas[("ventas", fecha + DIA)].append(erroneo)
            entregas[("ventas", fecha + DIA * int(rng.integers(4, 8)))].append(grupo[afectada])
        else:
            entregas[("ventas", fecha + DIA)].append(grupo)
    for fecha, grupo in datos["transacciones"][datos["transacciones"]["date"] >= inicio].groupby("date"):
        entregas[("transacciones", fecha + DIA * (7 - fecha.dayofweek))].append(grupo)
    for fecha, grupo in datos["petroleo"][datos["petroleo"]["date"] >= inicio].groupby("date"):
        entregas[("petroleo", fecha + DIA)].append(grupo)

    invalidas = set()
    for clave in sorted(k for k in entregas if k[0] == "ventas"):
        if rng.random() < p["prob_archivo_invalido"]:
            invalidas.add(clave)
            reenvio = ("ventas", clave[1] + DIA)
            entregas[reenvio] = list(entregas[clave]) + entregas.get(reenvio, [])

    if bandeja.exists():
        shutil.rmtree(bandeja)
    for (fuente, entrega), partes in sorted(entregas.items()):
        llave = FUENTES[fuente]["llave"]
        df = pd.concat(partes).drop_duplicates(llave, keep="last").sort_values(llave)
        if (fuente, entrega) in invalidas:
            df.iloc[0, df.columns.get_loc("sales")] = -1.0
        destino = bandeja / fuente / f"{fuente}_{entrega:%Y-%m-%d}.csv"
        destino.parent.mkdir(parents=True, exist_ok=True)
        df.assign(date=df["date"].dt.strftime("%Y-%m-%d")).to_csv(destino, index=False)
    return {"entregas": len(entregas), "invalidas": sorted(f"{f}_{e:%Y-%m-%d}" for f, e in invalidas)}
