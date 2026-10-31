"""Conversión y validación de fechas de publicación."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Optional
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .texto import PATRONES_FECHA_URL

UTC = timezone.utc


@lru_cache(maxsize=16)
def obtener_zona(nombre: str) -> ZoneInfo:
    """Devuelve una ZoneInfo, con UTC como último recurso."""
    try:
        return ZoneInfo(nombre)
    except Exception:
        return ZoneInfo("UTC")  # pragma: no cover - config lo valida antes


def ahora_utc() -> datetime:
    return datetime.now(tz=UTC)


def ahora_local(nombre_zona: str) -> datetime:
    return ahora_utc().astimezone(obtener_zona(nombre_zona))


def struct_a_datetime(estructura) -> Optional[datetime]:
    """Convierte el ``*_parsed`` de feedparser (struct_time UTC) a datetime UTC."""
    if not estructura:
        return None
    try:
        marca = calendar.timegm(estructura)
        return datetime.fromtimestamp(marca, tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def parsear_fecha(texto: Optional[str], nombre_zona: str = "Europe/Madrid") -> Optional[datetime]:
    """Interpreta fechas ISO 8601 o RFC 822 devueltas por los medios."""
    if not texto:
        return None
    crudo = str(texto).strip()
    if not crudo:
        return None

    candidato = crudo[:-1] + "+00:00" if crudo.endswith(("Z", "z")) else crudo
    try:
        valor = datetime.fromisoformat(candidato)
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=obtener_zona(nombre_zona))
        return valor.astimezone(UTC)
    except ValueError:
        pass

    try:
        valor = parsedate_to_datetime(crudo)
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=obtener_zona(nombre_zona))
        return valor.astimezone(UTC)
    except (TypeError, ValueError, IndexError):
        return None


def validar_publicacion(
    valor: Optional[datetime], ahora: Optional[datetime] = None
) -> Optional[datetime]:
    """Descarta fechas imposibles: anteriores a 1990 o con más de un día de futuro."""
    if valor is None:
        return None
    referencia = ahora or ahora_utc()
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    valor = valor.astimezone(UTC)
    if valor.year < 1990:
        return None
    if valor > referencia + timedelta(days=1):
        return None
    return valor


def fecha_local(valor: datetime, nombre_zona: str) -> date:
    """Fecha civil en la zona configurada (por defecto Europe/Madrid)."""
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return valor.astimezone(obtener_zona(nombre_zona)).date()


def fecha_desde_url(url: str) -> Optional[date]:
    """Extrae la fecha de publicación de rutas tipo /2026-10-27/ o /20261027/."""
    try:
        ruta = urlsplit(url).path
    except ValueError:
        return None
    for patron in PATRONES_FECHA_URL:
        coincidencia = patron.search(ruta)
        if not coincidencia:
            continue
        try:
            valor = date(
                int(coincidencia.group("anio")),
                int(coincidencia.group("mes")),
                int(coincidencia.group("dia")),
            )
        except ValueError:
            continue
        if 2000 <= valor.year <= 2100:
            return valor
    return None


def fecha_para_noticia(
    publicacion: Optional[datetime],
    url: str,
    nombre_zona: str,
    ahora: Optional[datetime] = None,
) -> tuple[date, bool]:
    """Devuelve (fecha, estimada) para indexar la noticia por día.

    Prioridad: instante de publicación -> fecha de la URL -> fecha de captura.
    ``estimada`` solo es True cuando se usa la fecha de captura.
    """
    referencia = ahora or ahora_utc()
    if publicacion is not None:
        return fecha_local(publicacion, nombre_zona), False
    en_url = fecha_desde_url(url)
    if en_url is not None:
        return en_url, False
    return fecha_local(referencia, nombre_zona), True


def formatear(valor: Optional[datetime], nombre_zona: str = "Europe/Madrid") -> str:
    if valor is None:
        return ""
    return valor.astimezone(obtener_zona(nombre_zona)).strftime("%Y-%m-%d %H:%M:%S")


ISO_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parsear_fecha_cli(texto: Optional[str]) -> Optional[date]:
    """Valida una fecha AAAA-MM-DD recibida por la línea de comandos."""
    if not texto:
        return None
    crudo = texto.strip()
    if not ISO_FECHA.match(crudo):
        raise ValueError(f"Fecha inválida: {texto!r}. Usa el formato AAAA-MM-DD.")
    try:
        return date.fromisoformat(crudo)
    except ValueError as exc:
        raise ValueError(f"Fecha inválida: {texto!r}.") from exc
