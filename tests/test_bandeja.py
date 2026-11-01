import pandas as pd

from conftest import tiendas_sinteticas, ventas_sinteticas
from reposicion import bandeja
from reposicion.fuentes import FUENTES, entrega_de


def test_bandeja_no_adelanta_fechas_y_reconstruye_las_ventas(tmp_path):
    kaggle = tmp_path / "kaggle"
    kaggle.mkdir()
    ventas = ventas_sinteticas("2016-01-01", "2016-03-31")
    ventas.assign(date=ventas["date"].dt.strftime("%Y-%m-%d")).to_csv(kaggle / "train.csv", index_label="id")
    trans = ventas.groupby(["date", "store_nbr"], as_index=False)["sales"].sum().rename(columns={"sales": "transactions"})
    trans.to_csv(kaggle / "transactions.csv", index=False)
    pd.DataFrame({"date": pd.bdate_range("2016-01-01", "2016-03-31"), "dcoilwtico": 40.0}).to_csv(kaggle / "oil.csv", index=False)
    pd.DataFrame({"date": ["2016-02-08"], "type": ["Holiday"], "locale": ["National"], "locale_name": ["Ecuador"],
                  "description": ["Carnaval"], "transferred": [False]}).to_csv(kaggle / "holidays_events.csv", index=False)
    tiendas_sinteticas().to_csv(kaggle / "stores.csv", index=False)

    p = {"prob_retraso_ventas": 0.2, "prob_correccion_ventas": 0.2, "prob_archivo_invalido": 0.1}
    resumen = bandeja.generar(kaggle, tmp_path / "historico", tmp_path / "bandeja", "2016-03-01", p, seed=1)

    for archivo in (tmp_path / "bandeja").rglob("*.csv"):
        fechas = pd.to_datetime(pd.read_csv(archivo)["date"])
        assert (fechas < pd.Timestamp(entrega_de(archivo))).all(), archivo.name

    # Sin las entregas inválidas y con la última entrega de cada fila, se recuperan las ventas originales.
    validos = [a for a in sorted((tmp_path / "bandeja" / "ventas").glob("*.csv")) if a.stem not in resumen["invalidas"]]
    llave = FUENTES["ventas"]["llave"]
    reconstruido = (pd.concat([pd.read_csv(a, parse_dates=["date"]) for a in validos])
                    .drop_duplicates(llave, keep="last").sort_values(llave, ignore_index=True))
    original = ventas[ventas["date"] >= "2016-03-01"].sort_values(llave, ignore_index=True)
    assert reconstruido["sales"].tolist() == original["sales"].tolist()
