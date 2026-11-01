"""Seguimiento del desempeño: pronósticos y pedidos publicados contra las ventas reales ya conocidas."""

from datetime import date

import numpy as np
import pandas as pd

from reposicion import config, fuentes, negocio
from reposicion.fuentes import guardar

LLAVE = ["fecha", "store_nbr", "family"]


def evaluar(fecha: date) -> pd.DataFrame:
    """Una fila por pronóstico publicado antes de la fecha, con las ventas reales conocidas en esa fecha."""
    reales = (fuentes.panel("ventas", fecha)
              .rename(columns={"date": "fecha", "sales": "real"})[LLAVE + ["real"]])
    filas = []
    for publicado in sorted(config.ruta("publicado").glob("corte=*")):
        corte = date.fromisoformat(publicado.name.split("=")[1])
        if corte >= fecha or not (publicado / "pedido.parquet").exists():
            continue
        pron = pd.read_parquet(publicado / "pronostico.parquet").merge(reales, on=LLAVE)
        if pron.empty:
            continue
        ped = pd.read_parquet(publicado / "pedido.parquet").merge(reales, on=LLAVE)
        c = ped[["family"]].merge(negocio.costos_familia(ped["family"].unique()), on="family", how="left")
        costo = negocio.costo(ped["real"], ped["pedido"], c["faltante"], c["sobrante"]).sum()
        filas.append({
            "corte": corte.isoformat(),
            "dias_con_real": int(pron["fecha"].nunique()),
            "wape_p50": negocio.wape(pron["real"], pron["p50"]),
            "cobertura_80": float(np.mean((pron["real"] >= pron["p10"]) & (pron["real"] <= pron["p90"]))),
            "ventas_reales": float(ped["real"].sum()),
            "unidades_pedidas": float(ped["pedido"].sum()),
            "faltante": float(np.maximum(ped["real"] - ped["pedido"], 0).sum()),
            "sobrante": float(np.maximum(ped["pedido"] - ped["real"], 0).sum()),
            "costo_pedido": float(costo),
            "costo_relativo": float(costo / max(ped["real"].sum(), 1e-9)),
        })
    df = pd.DataFrame(filas)
    guardar(df, config.ruta("seguimiento") / f"fecha={fecha.isoformat()}.parquet")
    escribir_reporte(df, fecha)
    return df


def escribir_reporte(df: pd.DataFrame, fecha: date) -> None:
    lineas = [f"# Seguimiento del desempeño al {fecha.isoformat()}", "",
              "Pronósticos y pedidos publicados comparados con las ventas reales conocidas a esa fecha. "
              "WAPE de la mediana (p50), cobertura del intervalo p10–p90 y costo del pedido sugerido "
              "con configs/costos.yaml (costo relativo = costo / ventas reales).", ""]
    if df.empty:
        lineas.append("Todavía no hay pronósticos con ventas reales conocidas.")
    else:
        lineas += ["| Corte | Días con real | WAPE p50 | Cobertura 80 % | Ventas reales | Pedido | Faltante | Sobrante | Costo relativo |",
                   "|---|---|---|---|---|---|---|---|---|"]
        for f in df.itertuples():
            lineas.append(f"| {f.corte} | {f.dias_con_real} | {f.wape_p50:.3f} | {f.cobertura_80:.1%} | "
                          f"{f.ventas_reales:,.0f} | {f.unidades_pedidas:,.0f} | {f.faltante:,.0f} | "
                          f"{f.sobrante:,.0f} | {f.costo_relativo:.3f} |")
        total = df["costo_pedido"].sum() / df["ventas_reales"].sum()
        lineas += ["", f"Costo relativo de todos los pedidos evaluados: {total:.3f}."]
    destino = config.ruta("reportes") / "seguimiento.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
