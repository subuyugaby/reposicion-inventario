import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from reposicion.fuentes import tipar

RAIZ = Path(__file__).resolve().parents[1]


def ventas_sinteticas(desde: str, hasta: str, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    filas = [{"date": f, "store_nbr": t, "family": fam, "onpromotion": 0,
              "sales": float(10 * t + (5 if fam == "B" else 0) + f.dayofweek + rng.poisson(3))}
             for f in pd.date_range(desde, hasta) for t in (1, 2) for fam in ("A", "B")]
    return pd.DataFrame(filas)


def tiendas_sinteticas() -> pd.DataFrame:
    return pd.DataFrame({"store_nbr": [1, 2], "city": ["Quito", "Guayaquil"], "state": ["Pichincha", "Guayas"],
                         "type": ["A", "B"], "cluster": [1, 2]})


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    """Proyecto mínimo con una carga histórica sintética de 2 tiendas y 2 familias (enero–abril de 2016)."""
    (tmp_path / "configs").mkdir()
    shutil.copy(RAIZ / "params.yaml", tmp_path / "params.yaml")
    shutil.copy(RAIZ / "configs" / "costos.yaml", tmp_path / "configs" / "costos.yaml")
    monkeypatch.setenv("REPOSICION_RAIZ", str(tmp_path))
    monkeypatch.delenv("REPOSICION_BANDEJA", raising=False)

    historico = tmp_path / "data" / "historico"
    historico.mkdir(parents=True)
    ventas = tipar(ventas_sinteticas("2016-01-01", "2016-04-30"), "ventas")
    ventas.to_parquet(historico / "ventas.parquet")
    trans = ventas.groupby(["date", "store_nbr"], as_index=False)["sales"].sum()
    tipar(trans.rename(columns={"sales": "transactions"}), "transacciones").to_parquet(historico / "transacciones.parquet")
    tipar(pd.DataFrame({"date": pd.date_range("2016-01-01", "2016-04-30"), "dcoilwtico": 50.0}),
          "petroleo").to_parquet(historico / "petroleo.parquet")
    pd.DataFrame({"date": pd.to_datetime(["2016-04-15"]).astype("datetime64[ns]"), "type": ["Holiday"],
                  "locale": ["National"], "locale_name": ["Ecuador"], "description": ["feriado"]}
                 ).to_parquet(historico / "feriados.parquet")
    tiendas_sinteticas().to_parquet(historico / "tiendas.parquet")
    return tmp_path


def entregar(raiz: Path, fuente: str, entrega: str, df: pd.DataFrame) -> Path:
    destino = raiz / "bandeja" / fuente / f"{fuente}_{entrega}.csv"
    destino.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(destino, index=False)
    return destino
