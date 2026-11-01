"""Reproduce un pronóstico publicado y lo compara con el archivo versionado.

Uso (desde una versión de código y datos obtenida con git checkout + dvc pull):
    python scripts/reproducir_pronostico.py --corte 2017-03-06
"""

import argparse
import json
from datetime import date

import joblib
import pandas as pd

from reposicion import config, fuentes, pronostico
from reposicion.features import datos_al_corte, features


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--corte", required=True)
    corte = date.fromisoformat(args.parse_args().corte)
    p = config.params()
    publicado = pronostico.carpeta("publicado", corte)
    metadata = json.loads((publicado / "metadata.json").read_text())

    huella = fuentes.huella_datos(corte)
    X = features(datos_al_corte(corte), corte, p["pronostico"]["horizonte"])
    modelo = joblib.load(config.raiz() / metadata["modelo"]["ruta"])
    nuevo = pronostico.calcular_pronostico(X, modelo, p["pronostico"]["cuantiles"])
    pedido = pronostico.calcular_pedido(X, modelo, p["pronostico"]["dias_pedido"])

    pd.testing.assert_frame_equal(nuevo, pd.read_parquet(publicado / "pronostico.parquet"), check_exact=False, atol=1e-6)
    pd.testing.assert_frame_equal(pedido, pd.read_parquet(publicado / "pedido.parquet"), check_exact=False, atol=1e-6)
    print(f"corte:               {corte}")
    print(f"modelo:              v{metadata['modelo']['version']} ({metadata['modelo']['tipo']}) {metadata['modelo']['ruta']}")
    print(f"commit publicado:    {metadata['git_commit']}")
    print(f"commit actual:       {config.git_commit()}")
    print(f"huella de datos:     {huella} ({'igual' if huella == metadata['huella_datos'] else 'DISTINTA'})")
    print(f"pronóstico y pedido: idénticos al publicado ({len(nuevo):,} y {len(pedido):,} filas)")


if __name__ == "__main__":
    main()
