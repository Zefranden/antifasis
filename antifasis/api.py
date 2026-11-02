"""API HTTP de Antifasis.

Expone un endpoint protegido para lanzar la captura desde un cron externo o
desde un Cron Job de Render. La ejecución es síncrona: la respuesta incluye el
resumen completo de la actualización.
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
from datetime import date, datetime, timezone
from functools import wraps
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

from . import __version__
from .config import Ajustes, cargar_ajustes
from .db import BaseDatos, ErrorBaseDatos, leer_esquema
from .fechas import parsear_fecha_cli
from .medios import MEDIOS, ErrorMedio, seleccionar_medios
from .servicio import ResultadoActualizacion, actualizar as ejecutar_actualizacion

LOG = logging.getLogger("antifasis.api")
Ejecutor = Callable[..., ResultadoActualizacion]
_VALORES_VERDAD = {"1", "true", "yes", "si", "sí", "on"}


def _env_bool(nombre: str, defecto: bool = False) -> bool:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return defecto
    return valor.strip().lower() in _VALORES_VERDAD


def _entero(valor, nombre: str, defecto: int, minimo: int, maximo: int) -> int:
    if valor is None or valor == "":
        return defecto
    try:
        numero = int(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{nombre} debe ser un número entero.") from exc
    if not minimo <= numero <= maximo:
        raise ValueError(f"{nombre} debe estar entre {minimo} y {maximo}.")
    return numero


def _booleano(valor, defecto: bool = False) -> bool:
    if valor is None:
        return defecto
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in _VALORES_VERDAD


def _auto_inicializar(app: Flask, ajustes: Ajustes) -> None:
    """Aplica el esquema y siembra los medios al arrancar, si se solicita."""
    if not _env_bool("ANTIFASIS_AUTO_INIT"):
        return
    try:
        with BaseDatos(ajustes.database_url) as db:
            db.ejecutar_script(leer_esquema())
            db.sincronizar_medios(MEDIOS)
        app.logger.info("Esquema y catálogo de medios comprobados en el arranque.")
    except Exception:  # noqa: BLE001 - la API debe arrancar aunque la BD tarde
        app.logger.exception(
            "No se pudo inicializar la base de datos al arrancar; "
            "se reintentará en la próxima petición de actualización."
        )


def _rango_desde_args(ajustes: Ajustes) -> tuple[date, date]:
    fecha = parsear_fecha_cli(request.args.get("fecha"))
    if fecha is not None:
        return fecha, fecha
    desde = parsear_fecha_cli(request.args.get("desde"))
    hasta = parsear_fecha_cli(request.args.get("hasta"))
    if desde and not hasta:
        hasta = desde
    if hasta and not desde:
        desde = hasta
    if desde is None or hasta is None:
        hoy = datetime.now(ZoneInfo(ajustes.zona)).date()
        return hoy, hoy
    if desde > hasta:
        raise ValueError("--desde no puede ser posterior a --hasta.")
    return desde, hasta


def create_app(
    ajustes: Optional[Ajustes] = None,
    ejecutor: Optional[Ejecutor] = None,
) -> Flask:
    """Crea la aplicación Flask. ``ejecutor`` permite inyectar un doble en tests."""
    ajustes = ajustes or cargar_ajustes()
    ejecutor = ejecutor or ejecutar_actualizacion
    token_esperado = os.getenv("ANTIFASIS_API_TOKEN", "").strip()

    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 1_000_000
    app.config["ANTIFASIS_AJUSTES"] = ajustes
    app.config["ANTIFASIS_API_TOKEN"] = token_esperado
    app.config["ANTIFASIS_EJECUTOR"] = ejecutor
    app.config["ANTIFASIS_LOCK"] = threading.Lock()

    _auto_inicializar(app, ajustes)

    def _token_recibido() -> str:
        cabecera = request.headers.get("Authorization", "").strip()
        if cabecera.lower().startswith("bearer "):
            return cabecera[7:].strip()
        return request.headers.get("X-API-Token", "").strip()

    def requiere_token(funcion):
        @wraps(funcion)
        def envoltorio(*args, **kwargs):
            if not app.config["ANTIFASIS_API_TOKEN"]:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "ANTIFASIS_API_TOKEN no está configurado en el servidor.",
                        }
                    ),
                    503,
                )
            recibido = _token_recibido()
            if not recibido or not hmac.compare_digest(
                recibido, app.config["ANTIFASIS_API_TOKEN"]
            ):
                respuesta = jsonify({"ok": False, "error": "Token de API inválido."})
                respuesta.status_code = 401
                respuesta.headers["WWW-Authenticate"] = "Bearer"
                return respuesta
            return funcion(*args, **kwargs)

        return envoltorio

    @app.get("/")
    def indice():
        return jsonify(
            {
                "ok": True,
                "servicio": "antifasis",
                "version": __version__,
                "descripcion": "Agregador de medios españoles con PostgreSQL.",
                "endpoints": {
                    "GET /health": "Estado del servicio (público).",
                    "GET /health/db": "Comprueba la conexión y el esquema (público).",
                    "POST /actualizar": "Ejecuta la captura. Requiere Bearer token.",
                    "GET /resumen": "Resumen por fecha. Requiere Bearer token.",
                },
            }
        )

    @app.get("/health")
    def health():
        return jsonify(
            {
                "ok": True,
                "status": "ok",
                "servicio": "antifasis",
                "version": __version__,
                "hora": datetime.now(timezone.utc).isoformat(),
            }
        )

    @app.get("/health/db")
    def health_db():
        try:
            with BaseDatos(ajustes.database_url) as db:
                db.verificar_esquema()
        except ErrorBaseDatos:
            app.logger.exception("Health check de base de datos fallido")
            return jsonify({"ok": False, "status": "error", "database": "unavailable"}), 503
        return jsonify({"ok": True, "status": "ok", "database": "ok"})

    @app.post("/actualizar")
    @requiere_token
    def actualizar_endpoint():
        bloqueo = app.config["ANTIFASIS_LOCK"]
        if not bloqueo.acquire(blocking=False):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "Ya hay una actualización en curso. Inténtalo de nuevo más tarde.",
                    }
                ),
                409,
            )

        try:
            datos = request.get_json(silent=True)
            if datos is None:
                datos = {}
            if not isinstance(datos, dict):
                raise ValueError("El cuerpo JSON debe ser un objeto.")

            medios_raw = datos.get("medios")
            if medios_raw is None:
                medios_raw = request.args.getlist("medio") or None
            elif isinstance(medios_raw, str):
                medios_raw = [medios_raw]
            elif not isinstance(medios_raw, list):
                raise ValueError("`medios` debe ser una lista de claves.")
            medios = seleccionar_medios(medios_raw)

            limite = _entero(
                datos.get("limite", request.args.get("limite")),
                "limite",
                ajustes.limite,
                0,
                500,
            )
            dias_max = _entero(
                datos.get("dias_max", request.args.get("dias_max")),
                "dias_max",
                ajustes.dias_max,
                0,
                3650,
            )
            dry_run = _booleano(datos.get("dry_run"), False)

            resultado = app.config["ANTIFASIS_EJECUTOR"](
                ajustes,
                medios,
                limite=limite,
                dias_max=dias_max,
                dry_run=dry_run,
            )
            # 503 si no se pudo guardar nada; 200 si hubo al menos una captura
            # correcta, aunque algún medio concreto haya fallado.
            estado_http = 200 if resultado.ok or resultado.guardadas else 503
            return jsonify(resultado.a_dict()), estado_http

        except (ErrorMedio, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except ErrorBaseDatos as exc:
            app.logger.exception("Error de base de datos durante la actualización")
            return jsonify({"ok": False, "error": str(exc)}), 503
        except Exception:  # noqa: BLE001 - la API no debe devolver un traceback
            app.logger.exception("Error inesperado durante la actualización")
            return jsonify({"ok": False, "error": "Error interno al actualizar."}), 500
        finally:
            bloqueo.release()

    @app.get("/resumen")
    @requiere_token
    def resumen_endpoint():
        try:
            desde, hasta = _rango_desde_args(ajustes)
            with BaseDatos(ajustes.database_url) as db:
                db.verificar_esquema()
                por_fecha = db.resumen_por_fecha(desde, hasta)
                por_medio = db.resumen_por_medio(desde, hasta)
                total = db.total_noticias(desde, hasta)
            return jsonify(
                {
                    "ok": True,
                    "desde": desde.isoformat(),
                    "hasta": hasta.isoformat(),
                    "total": total,
                    "por_fecha": [
                        {"fecha": fila["fecha"].isoformat(), "noticias": fila["noticias"]}
                        for fila in por_fecha
                    ],
                    "por_medio": [
                        {
                            "clave": fila["clave"],
                            "medio": fila["nombre"],
                            "ambito": fila["ambito"],
                            "comunidad": fila["comunidad"],
                            "noticias": fila["noticias"],
                        }
                        for fila in por_medio
                    ],
                }
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except ErrorBaseDatos as exc:
            app.logger.exception("Error de base de datos en /resumen")
            return jsonify({"ok": False, "error": str(exc)}), 503

    @app.errorhandler(404)
    def no_encontrada(_error):
        return jsonify({"ok": False, "error": "Ruta no encontrada."}), 404

    @app.errorhandler(405)
    def metodo_no_permitido(_error):
        return jsonify({"ok": False, "error": "Método no permitido."}), 405

    return app


if __name__ == "__main__":  # pragma: no cover
    create_app().run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
