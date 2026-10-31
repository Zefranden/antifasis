"""Persistencia en PostgreSQL: esquema, upsert idempotente y consultas por fecha."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import psycopg
from psycopg.rows import dict_row

from .medios import Medio
from .modelos import Noticia, ResultadoMedio
from .texto import hash_url

LOG = logging.getLogger(__name__)

RUTA_ESQUEMA = Path(__file__).resolve().parent / "sql" / "esquema.sql"

SQL_UPSERT = """
INSERT INTO noticias (
    medio_id, fecha, fecha_publicacion, fecha_estimada, titular, resumen, url,
    url_hash, seccion, autor, guid, imagen_url, idioma, origen
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (medio_id, url_hash) DO UPDATE SET
    fecha = CASE
        WHEN noticias.fecha_estimada AND NOT EXCLUDED.fecha_estimada THEN EXCLUDED.fecha
        ELSE noticias.fecha
    END,
    fecha_publicacion = COALESCE(EXCLUDED.fecha_publicacion, noticias.fecha_publicacion),
    fecha_estimada = noticias.fecha_estimada AND EXCLUDED.fecha_estimada,
    titular = EXCLUDED.titular,
    resumen = COALESCE(EXCLUDED.resumen, noticias.resumen),
    seccion = COALESCE(EXCLUDED.seccion, noticias.seccion),
    autor = COALESCE(EXCLUDED.autor, noticias.autor),
    guid = COALESCE(EXCLUDED.guid, noticias.guid),
    imagen_url = COALESCE(EXCLUDED.imagen_url, noticias.imagen_url),
    origen = CASE
        WHEN noticias.origen = 'rss' OR EXCLUDED.origen = 'rss' THEN 'rss'
        WHEN noticias.origen = 'descubierto' OR EXCLUDED.origen = 'descubierto' THEN 'descubierto'
        ELSE 'html'
    END,
    actualizado_en = now()
RETURNING (xmax = 0) AS nueva
"""


class ErrorBaseDatos(Exception):
    """Error de conexión, esquema o escritura en PostgreSQL."""


def _mensaje_conexion(exc: Exception) -> str:
    detalle = str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc)
    if "does not exist" in detalle:
        return (
            f"La base de datos indicada en DATABASE_URL no existe o el usuario no puede acceder.\n"
            f"Detalle: {detalle}\n"
            "Crea la base con Docker (docker compose up -d db) o con createdb."
        )
    if "Connection refused" in detalle or "could not connect" in detalle.lower():
        return (
            "No se puede conectar a PostgreSQL. ¿Está arrancado?\n"
            "  docker compose up -d db\n"
            f"Detalle: {detalle}"
        )
    return f"No se pudo conectar a PostgreSQL: {detalle}"


class BaseDatos:
    """Conexión única; las escrituras se agrupan en transacciones por medio."""

    def __init__(self, dsn: str):
        try:
            self.conn = psycopg.connect(
                dsn,
                connect_timeout=10,
                row_factory=dict_row,
                autocommit=True,
            )
        except psycopg.OperationalError as exc:
            raise ErrorBaseDatos(_mensaje_conexion(exc)) from exc

    def __enter__(self) -> "BaseDatos":
        return self

    def __exit__(self, *_exc) -> None:
        self.cerrar()

    def cerrar(self) -> None:
        try:
            self.conn.close()
        except Exception:  # pragma: no cover
            pass

    # ------------------------------------------------------------------
    # Esquema y catálogo
    # ------------------------------------------------------------------
    def ejecutar_script(self, sql: str) -> None:
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql)
            self.conn.commit()
        except psycopg.Error as exc:
            self.conn.rollback()
            raise ErrorBaseDatos(f"Error al aplicar el esquema: {exc}") from exc

    def verificar_esquema(self) -> None:
        try:
            fila = self.conn.execute(
                "SELECT to_regclass('noticias') AS noticias, "
                "       to_regclass('medios') AS medios"
            ).fetchone()
        except psycopg.Error as exc:
            raise ErrorBaseDatos(f"No se pudo comprobar el esquema: {exc}") from exc
        if not fila or fila["noticias"] is None or fila["medios"] is None:
            raise ErrorBaseDatos(
                "Falta el esquema de la base de datos. Ejecuta primero:\n"
                "  python -m antifasis init-db"
            )

    def sincronizar_medios(self, medios: Iterable[Medio]) -> Dict[str, int]:
        """Inserta o actualiza el catálogo y devuelve clave -> id."""
        sql = """
            INSERT INTO medios (clave, nombre, ambito, comunidad, url_base, feed_url, metodo, idioma)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (clave) DO UPDATE SET
                nombre = EXCLUDED.nombre,
                ambito = EXCLUDED.ambito,
                comunidad = EXCLUDED.comunidad,
                url_base = EXCLUDED.url_base,
                feed_url = EXCLUDED.feed_url,
                metodo = EXCLUDED.metodo,
                idioma = EXCLUDED.idioma,
                actualizado_en = now()
        """
        parametros = [
            (m.clave, m.nombre, m.ambito, m.comunidad, m.url_base, m.feed_url, m.metodo, m.idioma)
            for m in medios
        ]
        try:
            with self.conn.transaction():
                with self.conn.cursor() as cursor:
                    cursor.executemany(sql, parametros)
            filas = self.conn.execute("SELECT id, clave FROM medios").fetchall()
        except psycopg.Error as exc:
            raise ErrorBaseDatos(f"No se pudo sincronizar el catálogo de medios: {exc}") from exc
        return {fila["clave"]: fila["id"] for fila in filas}

    # ------------------------------------------------------------------
    # Capturas
    # ------------------------------------------------------------------
    def iniciar_captura(self, medio_id: int, iniciada_en: datetime) -> int:
        try:
            with self.conn.transaction():
                fila = self.conn.execute(
                    """
                    INSERT INTO capturas (medio_id, iniciada_en, estado)
                    VALUES (%s, %s, 'en_curso')
                    RETURNING id
                    """,
                    (medio_id, iniciada_en),
                ).fetchone()
        except psycopg.Error as exc:
            raise ErrorBaseDatos(f"No se pudo registrar la captura: {exc}") from exc
        return int(fila["id"])

    def finalizar_captura(
        self,
        captura_id: int,
        resultado: ResultadoMedio,
        nuevas: int,
        actualizadas: int,
    ) -> None:
        try:
            with self.conn.transaction():
                self.conn.execute(
                    """
                    UPDATE capturas SET
                        finalizada_en = now(),
                        estado = %s,
                        metodo = %s,
                        http_status = %s,
                        noticias_recibidas = %s,
                        noticias_nuevas = %s,
                        noticias_actualizadas = %s,
                        error = %s,
                        duracion_ms = %s
                    WHERE id = %s
                    """,
                    (
                        resultado.estado,
                        resultado.metodo,
                        resultado.http_status,
                        resultado.total,
                        nuevas,
                        actualizadas,
                        resultado.error_resumen or None,
                        resultado.duracion_ms,
                        captura_id,
                    ),
                )
        except psycopg.Error as exc:
            raise ErrorBaseDatos(f"No se pudo cerrar la captura {captura_id}: {exc}") from exc

    def marcar_captura_error(self, captura_id: int, mensaje: str, duracion_ms: int = 0) -> None:
        try:
            with self.conn.transaction():
                self.conn.execute(
                    """
                    UPDATE capturas SET
                        finalizada_en = now(),
                        estado = 'error',
                        error = %s,
                        duracion_ms = %s
                    WHERE id = %s
                    """,
                    ((mensaje or "Error desconocido")[:2000], duracion_ms, captura_id),
                )
        except psycopg.Error:
            LOG.exception("No se pudo marcar como error la captura %s", captura_id)

    # ------------------------------------------------------------------
    # Noticias
    # ------------------------------------------------------------------
    def guardar_noticias(self, medio_id: int, noticias: Sequence[Noticia]) -> Tuple[int, int]:
        """Upsert por (medio_id, url_hash). Devuelve (nuevas, actualizadas)."""
        nuevas = 0
        actualizadas = 0
        if not noticias:
            return nuevas, actualizadas

        vistos = set()
        try:
            with self.conn.transaction():
                with self.conn.cursor() as cursor:
                    for noticia in noticias:
                        firma = hash_url(noticia.url)
                        if firma in vistos:
                            continue
                        vistos.add(firma)
                        cursor.execute(
                            SQL_UPSERT,
                            (
                                medio_id,
                                noticia.fecha,
                                noticia.fecha_publicacion,
                                noticia.fecha_estimada,
                                noticia.titular,
                                noticia.resumen,
                                noticia.url,
                                firma,
                                noticia.seccion,
                                noticia.autor,
                                noticia.guid,
                                noticia.imagen_url,
                                noticia.idioma,
                                noticia.origen,
                            ),
                        )
                        fila = cursor.fetchone()
                        if fila and fila["nueva"]:
                            nuevas += 1
                        else:
                            actualizadas += 1
        except psycopg.Error as exc:
            raise ErrorBaseDatos(
                f"No se pudieron guardar las noticias del medio {medio_id}: {exc}"
            ) from exc

        return nuevas, actualizadas

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def resumen_por_fecha(self, desde: date, hasta: date) -> List[dict]:
        return self.conn.execute(
            """
            SELECT fecha, count(*)::integer AS noticias
            FROM noticias
            WHERE fecha BETWEEN %s AND %s
            GROUP BY fecha
            ORDER BY fecha
            """,
            (desde, hasta),
        ).fetchall()

    def resumen_por_medio(self, desde: date, hasta: date) -> List[dict]:
        return self.conn.execute(
            """
            SELECT m.clave, m.nombre, m.ambito, m.comunidad, count(*)::integer AS noticias
            FROM noticias n
            JOIN medios m ON m.id = n.medio_id
            WHERE n.fecha BETWEEN %s AND %s
            GROUP BY m.clave, m.nombre, m.ambito, m.comunidad
            ORDER BY noticias DESC, m.nombre
            """,
            (desde, hasta),
        ).fetchall()

    def total_noticias(self, desde: date, hasta: date) -> int:
        fila = self.conn.execute(
            "SELECT count(*)::integer AS total FROM noticias WHERE fecha BETWEEN %s AND %s",
            (desde, hasta),
        ).fetchone()
        return int(fila["total"]) if fila else 0

    def exportar(
        self, desde: date, hasta: date, medio_clave: Optional[str] = None
    ) -> List[dict]:
        sql = """
            SELECT
                n.fecha,
                n.fecha_publicacion,
                m.clave AS medio_clave,
                m.nombre AS medio,
                m.ambito,
                m.comunidad,
                n.seccion,
                n.titular,
                n.resumen,
                n.url,
                n.autor,
                n.fecha_estimada,
                n.origen
            FROM noticias n
            JOIN medios m ON m.id = n.medio_id
            WHERE n.fecha BETWEEN %s AND %s
        """
        parametros: List[object] = [desde, hasta]
        if medio_clave:
            sql += " AND m.clave = %s"
            parametros.append(medio_clave)
        sql += " ORDER BY n.fecha, m.nombre, n.fecha_publicacion NULLS LAST, n.id"
        return self.conn.execute(sql, parametros).fetchall()

    def ultima_captura_por_medio(self) -> List[dict]:
        return self.conn.execute(
            """
            SELECT DISTINCT ON (m.clave)
                m.clave, m.nombre, c.iniciada_en, c.estado, c.metodo,
                c.noticias_recibidas, c.noticias_nuevas, c.error
            FROM medios m
            LEFT JOIN capturas c ON c.medio_id = m.id
            ORDER BY m.clave, c.iniciada_en DESC NULLS LAST
            """
        ).fetchall()

    # ------------------------------------------------------------------
    # Mantenimiento
    # ------------------------------------------------------------------
    def contar_anteriores(self, fecha: date) -> int:
        fila = self.conn.execute(
            "SELECT count(*)::integer AS total FROM noticias WHERE fecha < %s", (fecha,)
        ).fetchone()
        return int(fila["total"]) if fila else 0

    def borrar_anteriores(self, fecha: date) -> int:
        try:
            with self.conn.transaction():
                cursor = self.conn.execute("DELETE FROM noticias WHERE fecha < %s", (fecha,))
                borradas = cursor.rowcount
        except psycopg.Error as exc:
            raise ErrorBaseDatos(f"No se pudieron borrar noticias antiguas: {exc}") from exc
        return int(borradas)

    def borrar_capturas_anteriores(self, limite: datetime) -> int:
        try:
            with self.conn.transaction():
                cursor = self.conn.execute("DELETE FROM capturas WHERE iniciada_en < %s", (limite,))
                borradas = cursor.rowcount
        except psycopg.Error as exc:
            raise ErrorBaseDatos(f"No se pudieron borrar capturas antiguas: {exc}") from exc
        return int(borradas)


def leer_esquema() -> str:
    if not RUTA_ESQUEMA.is_file():
        raise ErrorBaseDatos(f"No se encuentra el esquema SQL en {RUTA_ESQUEMA}")
    return RUTA_ESQUEMA.read_text(encoding="utf-8")


def fecha_limite(dias: int, hoy: Optional[date] = None) -> date:
    return (hoy or date.today()) - timedelta(days=dias)


def ahora_utc() -> datetime:
    return datetime.now(tz=timezone.utc)
