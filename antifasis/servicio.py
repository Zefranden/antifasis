"""Servicio de actualización compartido por la CLI y la API web.

La extracción se hace en paralelo, pero las escrituras en PostgreSQL se
serializan en el hilo principal. Así el comportamiento es el mismo tanto si
se lanza desde ``python -m antifasis actualizar`` como desde ``POST /actualizar``.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .config import Ajustes
from .db import BaseDatos, ErrorBaseDatos
from .extractores import extraer_medio
from .fechas import ahora_utc
from .http import SesionHTTP
from .medios import Medio
from .modelos import ResultadoMedio

LOG = logging.getLogger(__name__)

# (resultado, medios_completados, total_medios)
Progreso = Callable[[ResultadoMedio, int, int], None]


@dataclass
class ResultadoActualizacion:
    """Resumen serializable de una ejecución completa."""

    medios: List[ResultadoMedio]
    nuevas: int
    actualizadas: int
    recibidas: int
    estados: Dict[str, int]
    fallos: List[Tuple[str, str]]
    iniciada_en: datetime
    finalizada_en: datetime
    duracion_ms: int
    dry_run: bool = False

    @property
    def guardadas(self) -> int:
        return self.nuevas + self.actualizadas

    @property
    def ok(self) -> bool:
        return bool(self.medios) and self.estados.get("error", 0) == 0

    def a_dict(self) -> dict:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "iniciada_en": self.iniciada_en.isoformat(),
            "finalizada_en": self.finalizada_en.isoformat(),
            "duracion_ms": self.duracion_ms,
            "recibidas": self.recibidas,
            "nuevas": self.nuevas,
            "actualizadas": self.actualizadas,
            "guardadas": self.guardadas,
            "estados": self.estados,
            "fallos": [{"medio": nombre, "detalle": detalle} for nombre, detalle in self.fallos],
            "medios": [
                {
                    "clave": resultado.medio.clave,
                    "nombre": resultado.medio.nombre,
                    "estado": resultado.estado,
                    "metodo": resultado.metodo,
                    "http_status": resultado.http_status,
                    "noticias": resultado.total,
                    "nuevas": resultado.nuevas,
                    "actualizadas": resultado.actualizadas,
                    "duracion_ms": resultado.duracion_ms,
                    "errores": resultado.errores,
                }
                for resultado in self.medios
            ],
        }


def actualizar(
    ajustes: Ajustes,
    medios: Sequence[Medio],
    *,
    limite: Optional[int] = None,
    dias_max: Optional[int] = None,
    dry_run: bool = False,
    progreso: Optional[Progreso] = None,
) -> ResultadoActualizacion:
    """Extrae y persiste las noticias de los medios indicados.

    ``limite`` y ``dias_max`` permiten sobrescribir los valores de ``ajustes``.
    ``progreso`` se invoca en el hilo principal cada vez que termina un medio.
    """
    medios = list(medios)
    if not medios:
        raise ValueError("No hay medios que actualizar.")

    limite = ajustes.limite if limite is None else limite
    dias_max = ajustes.dias_max if dias_max is None else dias_max
    if not 0 <= limite <= 500:
        raise ValueError("El límite debe estar entre 0 y 500 (0 = sin límite).")
    if not 0 <= dias_max <= 3650:
        raise ValueError("La antigüedad máxima debe estar entre 0 y 3650 días.")

    ajustes = replace(ajustes, limite=limite, dias_max=dias_max)
    inicio = ahora_utc()
    t0 = time.monotonic()

    db: Optional[BaseDatos] = None
    ids: Dict[str, int] = {}
    resultados: List[ResultadoMedio] = []
    fallos: List[Tuple[str, str]] = []
    nuevas = actualizadas = recibidas = 0
    estados: Dict[str, int] = {}

    try:
        if not dry_run:
            db = BaseDatos(ajustes.database_url)
            db.verificar_esquema()
            ids = db.sincronizar_medios(medios)

        with SesionHTTP(ajustes) as cliente:
            with ThreadPoolExecutor(max_workers=min(ajustes.workers, len(medios))) as pool:
                futuros = {
                    pool.submit(extraer_medio, medio, cliente, ajustes): medio for medio in medios
                }
                for futuro in as_completed(futuros):
                    medio = futuros[futuro]
                    try:
                        resultado = futuro.result()
                    except Exception as exc:  # noqa: BLE001 - aislamos cada medio
                        LOG.exception("Fallo inesperado en %s", medio.clave)
                        resultado = ResultadoMedio(
                            medio=medio,
                            estado="error",
                            errores=[f"{type(exc).__name__}: {exc}"],
                            iniciada_en=ahora_utc(),
                            finalizada_en=ahora_utc(),
                        )

                    medio_nuevas = 0
                    medio_actualizadas = 0
                    captura_id: Optional[int] = None
                    fallo_db = False

                    if db is not None:
                        try:
                            captura_id = db.iniciar_captura(
                                ids[medio.clave], resultado.iniciada_en or ahora_utc()
                            )
                            medio_nuevas, medio_actualizadas = db.guardar_noticias(
                                ids[medio.clave], resultado.noticias
                            )
                            resultado.nuevas = medio_nuevas
                            resultado.actualizadas = medio_actualizadas
                            db.finalizar_captura(
                                captura_id, resultado, medio_nuevas, medio_actualizadas
                            )
                        except ErrorBaseDatos as exc:
                            if captura_id is not None:
                                db.marcar_captura_error(
                                    captura_id, str(exc), resultado.duracion_ms
                                )
                            resultado.estado = "error"
                            resultado.anotar_error(str(exc))
                            fallos.append((medio.nombre, str(exc)))
                            fallo_db = True

                    nuevas += medio_nuevas
                    actualizadas += medio_actualizadas
                    recibidas += resultado.total
                    estados[resultado.estado] = estados.get(resultado.estado, 0) + 1
                    if resultado.estado == "error" and not fallo_db:
                        fallos.append((medio.nombre, resultado.error_resumen or "sin noticias"))

                    resultados.append(resultado)
                    if progreso is not None:
                        try:
                            progreso(resultado, len(resultados), len(medios))
                        except Exception:  # pragma: no cover - un callback no debe romper la captura
                            LOG.exception("Error en el callback de progreso")
    finally:
        if db is not None:
            db.cerrar()

    fin = ahora_utc()
    return ResultadoActualizacion(
        medios=resultados,
        nuevas=nuevas,
        actualizadas=actualizadas,
        recibidas=recibidas,
        estados=estados,
        fallos=fallos,
        iniciada_en=inicio,
        finalizada_en=fin,
        duracion_ms=int((time.monotonic() - t0) * 1000),
        dry_run=dry_run,
    )
