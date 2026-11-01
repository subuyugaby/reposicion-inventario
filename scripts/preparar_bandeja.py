"""Construye la carga histórica (data/historico/) y la bandeja (bandeja/) a partir de data/kaggle/.

Se puede ejecutar varias veces: con la misma semilla produce exactamente los mismos archivos.
"""

import json
from datetime import date

from reposicion import bandeja, config


def main() -> None:
    p = config.params()
    resumen = bandeja.generar(config.ruta("kaggle"), config.ruta("historico"),
                              config.raiz() / p["rutas"]["bandeja"],
                              date.fromisoformat(p["bandeja"]["inicio"]), p["bandeja"], p["seed"])
    print(json.dumps(resumen, indent=2))


if __name__ == "__main__":
    main()
