"""Rutas, parámetros y huellas del proyecto."""

import hashlib
import os
from pathlib import Path

import yaml


def raiz() -> Path:
    return Path(os.environ.get("REPOSICION_RAIZ", Path(__file__).resolve().parents[2]))


def cargar_yaml(ruta: Path) -> dict:
    return yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))


def params() -> dict:
    return cargar_yaml(raiz() / "params.yaml")


def costos() -> dict:
    return cargar_yaml(raiz() / "configs" / "costos.yaml")


def ruta(nombre: str) -> Path:
    """Carpeta definida en params.yaml. En Docker la bandeja se monta aparte, en solo lectura."""
    if nombre == "bandeja" and os.environ.get("REPOSICION_BANDEJA"):
        return Path(os.environ["REPOSICION_BANDEJA"])
    return raiz() / params()["rutas"][nombre]


def md5(ruta: Path) -> str:
    h = hashlib.md5()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def git_commit() -> str:
    """Commit actual, leído de .git (la imagen de Airflow no necesita el binario de git)."""
    git = raiz() / ".git"
    try:
        if git.is_file():  # worktree: .git apunta a su carpeta dentro del repositorio principal
            git = Path(git.read_text().split("gitdir:")[1].strip())
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        if (git / ref).exists():
            return (git / ref).read_text().strip()
        for linea in (git / "packed-refs").read_text().splitlines():
            if linea.endswith(" " + ref):
                return linea.split()[0]
    except OSError:
        pass
    return "desconocido"
