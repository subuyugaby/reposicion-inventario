"""Fuentes de datos: validación de la bandeja, carga a landing y datos disponibles en una fecha de corte.

Cada archivo de la bandeja es una entrega <fuente>_<AAAA-MM-DD>.csv. Una entrega puede traer filas de
varios días, incluidas correcciones de días ya entregados.
"""

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

from reposicion import config

FUENTES = {
    "ventas": {"columnas": ["date", "store_nbr", "family", "sales", "onpromotion"],
               "llave": ["date", "store_nbr", "family"]},
    "transacciones": {"columnas": ["date", "store_nbr", "transactions"], "llave": ["date", "store_nbr"]},
    "petroleo": {"columnas": ["date", "dcoilwtico"], "llave": ["date"]},
}
TIPOS = {"store_nbr": "int64", "onpromotion": "int64", "transactions": "int64",
         "sales": "float64", "dcoilwtico": "float64"}
PATRON = re.compile(r"^(?P<fuente>[a-z]+)_(?P<entrega>\d{4}-\d{2}-\d{2})$")


def tipar(df: pd.DataFrame, fuente: str) -> pd.DataFrame:
    """Columnas y tipos estándar de una fuente."""
    df = df[FUENTES[fuente]["columnas"]].copy()
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    for col, tipo in TIPOS.items():
        if col in df.columns:
            df[col] = df[col].astype(tipo)
    if "family" in df.columns:
        df["family"] = df["family"].astype(str)
    return df


def entrega_de(archivo: Path) -> date | None:
    m = PATRON.match(archivo.stem)
    return date.fromisoformat(m["entrega"]) if m else None


def entregas(carpeta: Path, fuente: str, hasta: date, extension: str) -> list[tuple[date, Path]]:
    """Archivos de una fuente con fecha de entrega <= hasta, en orden de entrega."""
    archivos = []
    for archivo in (carpeta / fuente).glob(f"{fuente}_*{extension}"):
        entrega = entrega_de(archivo)
        if entrega and entrega <= hasta:
            archivos.append((entrega, archivo))
    return sorted(archivos)


def maestros() -> tuple[set, set]:
    """Tiendas y familias válidas, tomadas de la carga histórica."""
    historico = config.ruta("historico")
    tiendas = set(pd.read_parquet(historico / "tiendas.parquet", columns=["store_nbr"])["store_nbr"])
    familias = set(pd.read_parquet(historico / "ventas.parquet", columns=["family"])["family"].unique())
    return tiendas, familias


def validar(crudo: pd.DataFrame, fuente: str, entrega: date, tiendas: set, familias: set):
    """Devuelve (datos tipados, []) si la entrega es válida, o (None, errores) si no lo es."""
    columnas = FUENTES[fuente]["columnas"]
    faltan = [c for c in columnas if c not in crudo.columns]
    if faltan:
        return None, [f"faltan columnas: {faltan}"]
    df = crudo[columnas].copy()
    errores = []
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    if df["date"].isna().any():
        errores.append("fechas no válidas")
    elif (df["date"] >= pd.Timestamp(entrega)).any():
        errores.append("fechas iguales o posteriores a la entrega")
    for col in TIPOS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("sales", "onpromotion", "transactions"):
        if col in df.columns and (df[col].isna() | (df[col] < 0)).any():
            errores.append(f"{col} vacío o negativo")
    if "dcoilwtico" in df.columns and (df["dcoilwtico"] <= 0).any():
        errores.append("dcoilwtico no positivo")
    if "store_nbr" in df.columns and not df["store_nbr"].isin(tiendas).all():
        errores.append("tiendas desconocidas")
    if "family" in df.columns and not df["family"].isin(familias).all():
        errores.append("familias desconocidas")
    if df.duplicated(FUENTES[fuente]["llave"]).any():
        errores.append("llaves duplicadas")
    if errores:
        return None, errores
    return tipar(df, fuente), []


def guardar(df: pd.DataFrame, destino: Path) -> None:
    """Escritura atómica: si la tarea falla a mitad, el archivo anterior queda intacto."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".tmp")
    df.to_parquet(temporal, index=False)
    temporal.replace(destino)


def ingerir(fuente: str, archivo: Path, maestros_: tuple[set, set]) -> str:
    """Valida una entrega y la copia a landing. Idempotente: una entrega ya cargada no se vuelve a escribir.
    Una entrega inválida no llega a landing; su motivo queda en cuarentena."""
    huella = config.md5(archivo)
    destino = config.ruta("landing") / fuente / f"{archivo.stem}.parquet"
    marca = destino.with_suffix(".md5")
    rechazo = config.ruta("cuarentena") / fuente / f"{archivo.stem}.json"
    if marca.exists() and marca.read_text() == huella:
        return "sin_cambios"
    try:
        crudo = pd.read_csv(archivo, dtype=str)
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as e:
        df, errores = None, [f"archivo ilegible: {e}"]
    else:
        df, errores = validar(crudo, fuente, entrega_de(archivo), *maestros_)
    if errores:
        rechazo.parent.mkdir(parents=True, exist_ok=True)
        rechazo.write_text(json.dumps({"md5": huella, "errores": errores}, ensure_ascii=False, indent=2))
        return "invalido"
    guardar(df, destino)
    marca.write_text(huella)
    rechazo.unlink(missing_ok=True)
    return "cargado"


def ingerir_entregas(hasta: date, fuentes: list[str] | None = None, solo_ese_dia: bool = False) -> dict:
    """Carga las entregas con fecha <= hasta (o solo las de ese día). Devuelve el estado de cada archivo."""
    m = maestros()
    estados = {}
    for fuente in fuentes or FUENTES:
        for entrega, archivo in entregas(config.ruta("bandeja"), fuente, hasta, ".csv"):
            if not solo_ese_dia or entrega == hasta:
                estados[archivo.name] = ingerir(fuente, archivo, m)
    return estados


def panel(fuente: str, corte: date) -> pd.DataFrame:
    """La fuente tal como se conocía en la fecha de corte: carga histórica más entregas con fecha <= corte.
    Si una fila llegó más de una vez, vale la entrega más reciente (las correcciones reemplazan)."""
    partes = [pd.read_parquet(config.ruta("historico") / f"{fuente}.parquet")]
    partes += [pd.read_parquet(a) for _, a in entregas(config.ruta("landing"), fuente, corte, ".parquet")]
    llave = FUENTES[fuente]["llave"]
    df = pd.concat(partes, ignore_index=True)
    return df.drop_duplicates(llave, keep="last").sort_values(llave, ignore_index=True)


def huella_datos(corte: date) -> str:
    """Huella de todos los datos de entrada disponibles en la fecha de corte."""
    archivos = sorted(config.ruta("historico").glob("*.parquet"))
    for fuente in FUENTES:
        archivos += [a for _, a in entregas(config.ruta("landing"), fuente, corte, ".parquet")]
    return hashlib.md5("".join(config.md5(a) for a in archivos).encode()).hexdigest()
