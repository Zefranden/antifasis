"""Cliente HTTP educado: reintentos, límite de tamaño, robots.txt y decodificación."""

from __future__ import annotations

import logging
import random
import re
import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import requests
from charset_normalizer import from_bytes

from .config import Ajustes
from .texto import normalizar_url

LOG = logging.getLogger(__name__)

MAX_BYTES = 15 * 1024 * 1024
CODIGOS_REINTENTABLES = {429, 500, 502, 503, 504}
TOKEN_ROBOTS = "Antifasis"


@dataclass
class Respuesta:
    url: str
    estado: Optional[int] = None
    contenido: bytes = b""
    tipo: str = ""
    codificacion: str = "utf-8"
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.estado is not None and 200 <= self.estado < 300

    def texto(self) -> str:
        if not self.contenido:
            return ""
        try:
            return self.contenido.decode(self.codificacion, errors="replace")
        except LookupError:
            return self.contenido.decode("utf-8", errors="replace")


def decodificar(contenido: bytes, tipo: str = "") -> Tuple[str, str]:
    """Adivina la codificación real, evitando el ISO-8859-1 por defecto de requests."""
    if not contenido:
        return "", "utf-8"

    meta = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?([\w.-]+)", contenido[:4096], re.IGNORECASE)
    if meta:
        declarada = meta.group(1).decode("ascii", errors="ignore").lower()
        try:
            return contenido.decode(declarada), declarada
        except (LookupError, UnicodeDecodeError):
            pass

    coincidencia = re.search(r"charset\s*=\s*[\"']?([\w.-]+)", tipo or "", re.IGNORECASE)
    if coincidencia:
        declarada = coincidencia.group(1).strip().lower()
        if declarada not in ("iso-8859-1", "latin-1", "latin1"):
            try:
                return contenido.decode(declarada), declarada
            except (LookupError, UnicodeDecodeError):
                pass

    try:
        return contenido.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        if coincidencia:
            declarada = coincidencia.group(1).strip().lower()
            try:
                return contenido.decode(declarada), declarada
            except (LookupError, UnicodeDecodeError):
                pass
        mejor = from_bytes(contenido).best()
        if mejor is not None and mejor.encoding:
            return str(mejor), mejor.encoding
        return contenido.decode("utf-8", errors="replace"), "utf-8"


class SesionHTTP:
    """Sesiones por hilo y caché de robots.txt por dominio."""

    def __init__(self, ajustes: Ajustes):
        self.ajustes = ajustes
        self._local = threading.local()
        self._sesiones: List[requests.Session] = []
        self._candado = threading.Lock()
        self._robots: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._candado_robots = threading.Lock()

    # ------------------------------------------------------------------
    # Sesiones
    # ------------------------------------------------------------------
    def _sesion(self) -> requests.Session:
        sesion = getattr(self._local, "sesion", None)
        if sesion is None:
            sesion = requests.Session()
            sesion.headers.update(
                {
                    "User-Agent": self.ajustes.user_agent,
                    "Accept": (
                        "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
                        "text/html;q=0.8, */*;q=0.5"
                    ),
                    "Accept-Language": "es-ES,es;q=0.9,ca;q=0.8,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "keep-alive",
                }
            )
            self._local.sesion = sesion
            with self._candado:
                self._sesiones.append(sesion)
        return sesion

    def cerrar(self) -> None:
        with self._candado:
            sesiones, self._sesiones = self._sesiones, []
        for sesion in sesiones:
            try:
                sesion.close()
            except Exception:  # pragma: no cover
                pass

    def __enter__(self) -> "SesionHTTP":
        return self

    def __exit__(self, *_exc) -> None:
        self.cerrar()

    # ------------------------------------------------------------------
    # robots.txt
    # ------------------------------------------------------------------
    def _cargar_robots(self, base: str) -> Optional[urllib.robotparser.RobotFileParser]:
        try:
            respuesta = self._sesion().get(base + "/robots.txt", timeout=min(8, self.ajustes.timeout))
        except requests.RequestException:
            return None
        if respuesta.status_code >= 400:
            return None
        parser = urllib.robotparser.RobotFileParser()
        try:
            parser.parse(respuesta.text.splitlines())
        except Exception:  # pragma: no cover
            return None
        return parser

    def permite_robots(self, url: str) -> Tuple[bool, Optional[str]]:
        if not self.ajustes.respetar_robots:
            return True, None
        partes = urlsplit(url)
        base = f"{partes.scheme}://{partes.netloc}"
        with self._candado_robots:
            if base not in self._robots:
                self._robots[base] = self._cargar_robots(base)
            parser = self._robots[base]
        if parser is None:
            return True, None
        if parser.can_fetch(TOKEN_ROBOTS, url):
            return True, None
        return False, f"robots.txt de {partes.netloc} no permite acceder a esta URL"

    # ------------------------------------------------------------------
    # Descargas
    # ------------------------------------------------------------------
    def descargar(
        self,
        url: str,
        *,
        comprobar_robots: bool = True,
        timeout: Optional[int] = None,
        reintentos: Optional[int] = None,
    ) -> Respuesta:
        normalizada = normalizar_url(url)
        if not normalizada:
            return Respuesta(url=url or "", error="URL inválida")

        if comprobar_robots:
            permitido, motivo = self.permite_robots(normalizada)
            if not permitido:
                return Respuesta(url=normalizada, error=motivo)

        espera = timeout or self.ajustes.timeout
        intentos = self.ajustes.reintentos if reintentos is None else reintentos
        sesion = self._sesion()
        ultimo_error = ""

        for intento in range(intentos + 1):
            try:
                respuesta = sesion.get(
                    normalizada,
                    timeout=(min(10, espera), espera),
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                ultimo_error = f"{type(exc).__name__}: {exc}"
                LOG.debug("Fallo al descargar %s (intento %s): %s", normalizada, intento + 1, ultimo_error)
                if intento < intentos:
                    self._esperar(intento)
                continue

            if respuesta.status_code in CODIGOS_REINTENTABLES and intento < intentos:
                LOG.debug("HTTP %s en %s; reintentando", respuesta.status_code, normalizada)
                self._esperar(intento, respuesta.headers.get("Retry-After"))
                continue

            if not 200 <= respuesta.status_code < 300:
                return Respuesta(
                    url=respuesta.url,
                    estado=respuesta.status_code,
                    tipo=respuesta.headers.get("Content-Type", ""),
                    error=f"HTTP {respuesta.status_code}",
                )

            contenido = respuesta.content
            if len(contenido) > MAX_BYTES:
                return Respuesta(
                    url=respuesta.url,
                    estado=respuesta.status_code,
                    tipo=respuesta.headers.get("Content-Type", ""),
                    error=f"Respuesta demasiado grande ({len(contenido)} bytes)",
                )

            _texto, codificacion = decodificar(contenido, respuesta.headers.get("Content-Type", ""))
            return Respuesta(
                url=respuesta.url,
                estado=respuesta.status_code,
                contenido=contenido,
                tipo=respuesta.headers.get("Content-Type", ""),
                codificacion=codificacion,
            )

        return Respuesta(url=normalizada, error=ultimo_error or "Error de red desconocido")

    @staticmethod
    def _esperar(intento: int, retry_after: Optional[str] = None) -> None:
        demora = min(8.0, 0.8 * (2**intento)) + random.uniform(0.0, 0.3)
        if retry_after:
            try:
                demora = min(10.0, max(demora, float(retry_after)))
            except (TypeError, ValueError):
                pass
        time.sleep(demora)
