"""Modelos de datos compartidos por extractores, base de datos y CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:  # pragma: no cover
    from .medios import Medio


@dataclass
class Noticia:
    """Una noticia normalizada, lista para persistirse."""

    medio_clave: str
    titular: str
    url: str
    fecha: date
    fecha_publicacion: Optional[datetime] = None
    fecha_estimada: bool = True
    resumen: Optional[str] = None
    seccion: Optional[str] = None
    autor: Optional[str] = None
    guid: Optional[str] = None
    imagen_url: Optional[str] = None
    idioma: str = "es"
    origen: str = "rss"


@dataclass
class ResultadoMedio:
    """Resultado de intentar extraer las noticias de un medio."""

    medio: "Medio"
    noticias: List[Noticia] = field(default_factory=list)
    estado: str = "error"
    metodo: Optional[str] = None
    http_status: Optional[int] = None
    errores: List[str] = field(default_factory=list)
    iniciada_en: Optional[datetime] = None
    finalizada_en: Optional[datetime] = None
    duracion_ms: int = 0
    nuevas: int = 0
    actualizadas: int = 0

    @property
    def total(self) -> int:
        return len(self.noticias)

    @property
    def error_resumen(self) -> str:
        return "; ".join(self.errores)[:2000]

    def anotar_error(self, mensaje: str) -> None:
        mensaje = (mensaje or "").strip()
        if mensaje and mensaje not in self.errores:
            self.errores.append(mensaje)
