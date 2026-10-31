"""Configuración de Antifasis leída de variables de entorno y de un fichero .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

RUTA_PROYECTO = Path(__file__).resolve().parent.parent

DSN_POR_DEFECTO = "postgresql://antifasis:antifasis@localhost:5432/antifasis"

USER_AGENT_POR_DEFECTO = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
    "Antifasis/1.0"
)


class ErrorConfiguracion(Exception):
    """La configuración contiene un valor inválido."""


@dataclass(frozen=True)
class Ajustes:
    """Parámetros de ejecución del agregador."""

    database_url: str = DSN_POR_DEFECTO
    zona: str = "Europe/Madrid"
    timeout: int = 20
    reintentos: int = 2
    workers: int = 6
    limite: int = 100
    dias_max: int = 30
    respetar_robots: bool = True
    user_agent: str = USER_AGENT_POR_DEFECTO

    def con_base_datos(self, database_url: Optional[str]) -> "Ajustes":
        """Devuelve una copia con otra cadena de conexión."""
        if not database_url:
            return self
        return Ajustes(
            database_url=database_url,
            zona=self.zona,
            timeout=self.timeout,
            reintentos=self.reintentos,
            workers=self.workers,
            limite=self.limite,
            dias_max=self.dias_max,
            respetar_robots=self.respetar_robots,
            user_agent=self.user_agent,
        )


def cargar_dotenv(ruta: Optional[Path] = None) -> None:
    """Carga un .env sencillo sin dependencias externas.

    No pisa variables que ya existan en el entorno. Ignora comentarios y líneas
    sin ``=``. Admite valores entre comillas simples o dobles.
    """
    if ruta is None:
        candidatas = [Path.cwd() / ".env", RUTA_PROYECTO / ".env"]
        ruta = next((c for c in candidatas if c.is_file()), None)
    if ruta is None or not Path(ruta).is_file():
        return

    for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip()
        if clave.startswith("export "):
            clave = clave[len("export ") :].strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ("'", '"'):
            valor = valor[1:-1]
        if clave and clave not in os.environ:
            os.environ[clave] = valor


def _entero(nombre: str, defecto: int, minimo: int, maximo: int) -> int:
    crudo = os.getenv(nombre)
    if crudo is None or crudo.strip() == "":
        return defecto
    try:
        valor = int(crudo)
    except ValueError as exc:
        raise ErrorConfiguracion(f"{nombre} debe ser un número entero (recibido: {crudo!r}).") from exc
    if not minimo <= valor <= maximo:
        raise ErrorConfiguracion(f"{nombre} debe estar entre {minimo} y {maximo} (recibido: {valor}).")
    return valor


def _booleano(nombre: str, defecto: bool) -> bool:
    crudo = os.getenv(nombre)
    if crudo is None or crudo.strip() == "":
        return defecto
    valor = crudo.strip().lower()
    if valor in ("1", "true", "yes", "si", "sí", "on"):
        return True
    if valor in ("0", "false", "no", "off"):
        return False
    raise ErrorConfiguracion(f"{nombre} debe ser true/false (recibido: {crudo!r}).")


def cargar_ajustes(base_datos: Optional[str] = None) -> Ajustes:
    """Construye los ajustes efectivos a partir del entorno."""
    cargar_dotenv()

    ajustes = Ajustes(
        database_url=os.getenv("DATABASE_URL", DSN_POR_DEFECTO).strip() or DSN_POR_DEFECTO,
        zona=os.getenv("ANTIFASIS_ZONA", "Europe/Madrid").strip() or "Europe/Madrid",
        timeout=_entero("ANTIFASIS_TIMEOUT", 20, 3, 120),
        reintentos=_entero("ANTIFASIS_REINTENTOS", 2, 0, 5),
        workers=_entero("ANTIFASIS_WORKERS", 6, 1, 16),
        limite=_entero("ANTIFASIS_LIMITE", 100, 0, 500),
        dias_max=_entero("ANTIFASIS_DIAS_MAX", 30, 0, 3650),
        respetar_robots=_booleano("ANTIFASIS_RESPETAR_ROBOTS", True),
        user_agent=os.getenv("ANTIFASIS_USER_AGENT", USER_AGENT_POR_DEFECTO).strip()
        or USER_AGENT_POR_DEFECTO,
    )

    # Valida la zona horaria aquí para dar un error claro al arrancar.
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(ajustes.zona)
    except Exception as exc:  # ZoneInfoNotFoundError o base de datos tz ausente
        raise ErrorConfiguracion(
            f"ANTIFASIS_ZONA={ajustes.zona!r} no es una zona horaria IANA válida."
        ) from exc

    return ajustes.con_base_datos(base_datos)


def variables_publicas(ajustes: Ajustes) -> Dict[str, str]:
    """Resumen legible de la configuración (sin secretos de la DSN)."""
    return {
        "zona": ajustes.zona,
        "timeout": str(ajustes.timeout),
        "reintentos": str(ajustes.reintentos),
        "workers": str(ajustes.workers),
        "limite": str(ajustes.limite) if ajustes.limite else "sin límite",
        "dias_max": str(ajustes.dias_max) if ajustes.dias_max else "sin límite",
        "robots": "sí" if ajustes.respetar_robots else "no",
    }
