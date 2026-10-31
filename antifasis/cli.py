"""Interfaz de línea de comandos de Antifasis."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import __version__
from .config import Ajustes, ErrorConfiguracion, cargar_ajustes
from .db import BaseDatos, ErrorBaseDatos, leer_esquema
from .extractores import extraer_medio
from .fechas import parsear_fecha_cli
from .http import SesionHTTP
from .medios import MEDIOS, ErrorMedio, seleccionar_medios
from .modelos import ResultadoMedio

LOG = logging.getLogger("antifasis")

CAMPOS_CSV = [
    "fecha",
    "hora_publicacion",
    "medio",
    "ambito",
    "comunidad",
    "seccion",
    "titular",
    "resumen",
    "url",
    "autor",
    "fecha_estimada",
    "origen",
]


# ----------------------------------------------------------------------
# Utilidades de presentación
# ----------------------------------------------------------------------
def _num(valor: int) -> str:
    return f"{valor:,}".replace(",", ".")


def _segundos(ms: int) -> str:
    return f"{ms / 1000:.1f} s".replace(".", ",")


def _hoy(ajustes: Ajustes) -> date:
    from zoneinfo import ZoneInfo

    try:
        return datetime.now(ZoneInfo(ajustes.zona)).date()
    except Exception:  # pragma: no cover
        return date.today()


def _rango_fechas(args, ajustes: Ajustes, por_defecto_hoy: bool = True) -> Tuple[date, date]:
    if args.fecha and (args.desde or args.hasta):
        raise ValueError("Usa --fecha o --desde/--hasta, no ambas opciones a la vez.")

    hasta = parsear_fecha_cli(getattr(args, "hasta", None))
    desde = parsear_fecha_cli(getattr(args, "desde", None))
    unica = parsear_fecha_cli(getattr(args, "fecha", None))

    if unica:
        return unica, unica
    if desde and not hasta:
        hasta = desde
    if hasta and not desde:
        desde = hasta
    if not desde and not hasta:
        if not por_defecto_hoy:
            raise ValueError("Indica --fecha o --desde/--hasta.")
        hoy = _hoy(ajustes)
        return hoy, hoy
    if desde is None or hasta is None:
        raise ValueError("Rango de fechas incompleto.")
    if desde > hasta:
        raise ValueError("--desde no puede ser posterior a --hasta.")
    return desde, hasta


def _error(mensaje: str) -> None:
    print(f"Error: {mensaje}", file=sys.stderr)


def _tabla(cabeceras: Sequence[str], filas: Iterable[Sequence[object]], alinear_derecha=()) -> str:
    filas = [[str(c) for c in fila] for fila in filas]
    anchos = [len(c) for c in cabeceras]
    for fila in filas:
        for i, celda in enumerate(fila):
            anchos[i] = max(anchos[i], len(celda))

    def linea(valores):
        celdas = []
        for i, valor in enumerate(valores):
            if i in alinear_derecha:
                celdas.append(valor.rjust(anchos[i]))
            else:
                celdas.append(valor.ljust(anchos[i]))
        return "  ".join(celdas).rstrip()

    salida = [linea(cabeceras), linea(["-" * a for a in anchos])]
    salida.extend(linea(fila) for fila in filas)
    return "\n".join(salida)


# ----------------------------------------------------------------------
# Comandos
# ----------------------------------------------------------------------
def cmd_init_db(ajustes: Ajustes, _args) -> int:
    esquema = leer_esquema()
    with BaseDatos(ajustes.database_url) as db:
        db.ejecutar_script(esquema)
        ids = db.sincronizar_medios(MEDIOS)
    print(f"Esquema aplicado y {len(ids)} medios registrados.")
    print("Siguiente paso: python -m antifasis actualizar")
    return 0


def cmd_listar_medios(_ajustes: Ajustes, _args) -> int:
    filas = []
    for medio in MEDIOS:
        metodo = {"rss": "RSS", "auto": "RSS + HTML", "html": "HTML"}[medio.metodo]
        filas.append(
            (
                medio.clave,
                medio.nombre,
                medio.ambito,
                medio.comunidad,
                metodo,
                medio.feed_url or "(portada)",
            )
        )
    print(
        _tabla(
            ["CLAVE", "MEDIO", "ÁMBITO", "COMUNIDAD", "MÉTODO", "FUENTE"],
            filas,
        )
    )
    print(f"\n{len(filas)} medios configurados.")
    return 0


def cmd_actualizar(ajustes: Ajustes, args) -> int:
    medios = seleccionar_medios(args.medio)

    limite = ajustes.limite if args.limite is None else args.limite
    if not 0 <= limite <= 500:
        raise ValueError("--limite debe estar entre 0 y 500 (0 = sin límite).")

    dias_max = ajustes.dias_max if args.dias_max is None else args.dias_max
    if not 0 <= dias_max <= 3650:
        raise ValueError("--dias-max debe estar entre 0 y 3650 (0 = sin límite).")

    ajustes = replace(
        ajustes,
        limite=limite,
        dias_max=dias_max,
        respetar_robots=False if args.sin_robots else ajustes.respetar_robots,
    )

    print(
        f"Antifasis {__version__} · {len(medios)} medios · zona {ajustes.zona} · "
        f"límite {limite or 'sin límite'} · antigüedad {dias_max or 'sin límite'} días · "
        f"robots {'no' if args.sin_robots else 'sí'}"
    )
    if args.dry_run:
        print("Modo simulación: no se escribirá en PostgreSQL.\n")

    db: Optional[BaseDatos] = None
    ids: Dict[str, int] = {}
    if not args.dry_run:
        db = BaseDatos(ajustes.database_url)
        db.verificar_esquema()
        ids = db.sincronizar_medios(medios)

    totales = {"nuevas": 0, "actualizadas": 0, "recibidas": 0}
    estados: Dict[str, int] = {}
    fallos: List[Tuple[str, str]] = []
    completados = 0

    try:
        with SesionHTTP(ajustes) as cliente:
            with ThreadPoolExecutor(max_workers=min(ajustes.workers, len(medios))) as pool:
                futuros = {pool.submit(extraer_medio, medio, cliente, ajustes): medio for medio in medios}
                for futuro in as_completed(futuros):
                    medio = futuros[futuro]
                    completados += 1
                    try:
                        resultado = futuro.result()
                    except Exception as exc:  # noqa: BLE001 - aislamos cada medio
                        LOG.exception("Fallo inesperado en %s", medio.clave)
                        resultado = ResultadoMedio(
                            medio=medio,
                            estado="error",
                            errores=[f"{type(exc).__name__}: {exc}"],
                        )

                    nuevas = 0
                    actualizadas = 0
                    captura_id: Optional[int] = None

                    if db is not None:
                        try:
                            captura_id = db.iniciar_captura(
                                ids[medio.clave], resultado.iniciada_en or datetime.now().astimezone()
                            )
                            nuevas, actualizadas = db.guardar_noticias(
                                ids[medio.clave], resultado.noticias
                            )
                            db.finalizar_captura(captura_id, resultado, nuevas, actualizadas)
                        except ErrorBaseDatos as exc:
                            if captura_id is not None:
                                db.marcar_captura_error(
                                    captura_id, str(exc), resultado.duracion_ms
                                )
                            resultado.estado = "error"
                            resultado.anotar_error(str(exc))
                            fallos.append((medio.nombre, str(exc)))

                    totales["nuevas"] += nuevas
                    totales["actualizadas"] += actualizadas
                    totales["recibidas"] += resultado.total
                    estados[resultado.estado] = estados.get(resultado.estado, 0) + 1
                    if resultado.estado == "error":
                        fallos.append(
                            (medio.nombre, resultado.error_resumen or "sin noticias")
                        )

                    etiqueta = f"[{completados:>2}/{len(medios)}]"
                    metodo = resultado.metodo or "-"
                    contador = (
                        f"{resultado.total:>3} noticias"
                        if args.dry_run
                        else f"{resultado.total:>3} noticias · {nuevas:>3} nuevas · {actualizadas:>3} act."
                    )
                    print(
                        f"{etiqueta} {medio.nombre[:26]:<26} {resultado.estado:<8} "
                        f"{metodo[:16]:<16} {contador:>34}  {_segundos(resultado.duracion_ms):>7}",
                        flush=True,
                    )
                    if resultado.errores:
                        for error in resultado.errores[:2]:
                            print(f"         · {error[:150]}", flush=True)
    finally:
        if db is not None:
            db.cerrar()

    print("\n" + "-" * 78)
    if args.dry_run:
        print(
            f"Simulación: {_num(totales['recibidas'])} noticias en {len(medios)} medios · "
            f"estados: {', '.join(f'{k}={v}' for k, v in sorted(estados.items()))}"
        )
    else:
        print(
            f"Total: {_num(totales['recibidas'])} noticias · "
            f"{_num(totales['nuevas'])} nuevas · {_num(totales['actualizadas'])} actualizadas · "
            f"estados: {', '.join(f'{k}={v}' for k, v in sorted(estados.items()))}"
        )

    if fallos:
        print("\nIncidencias:")
        for nombre, detalle in fallos[:20]:
            print(f"  - {nombre}: {detalle[:180]}")

    if not args.dry_run and totales["nuevas"] + totales["actualizadas"] == 0:
        _error("No se ha guardado ninguna noticia. Revisa la conexión y los avisos.")
        return 1
    return 0


def cmd_resumen(ajustes: Ajustes, args) -> int:
    desde, hasta = _rango_fechas(args, ajustes)
    with BaseDatos(ajustes.database_url) as db:
        db.verificar_esquema()
        por_fecha = db.resumen_por_fecha(desde, hasta)
        por_medio = db.resumen_por_medio(desde, hasta)
        total = db.total_noticias(desde, hasta)

    if args.json:
        print(
            json.dumps(
                {
                    "desde": desde.isoformat(),
                    "hasta": hasta.isoformat(),
                    "total": total,
                    "por_fecha": [
                        {"fecha": f["fecha"].isoformat(), "noticias": f["noticias"]}
                        for f in por_fecha
                    ],
                    "por_medio": [
                        {
                            "clave": m["clave"],
                            "medio": m["nombre"],
                            "ambito": m["ambito"],
                            "comunidad": m["comunidad"],
                            "noticias": m["noticias"],
                        }
                        for m in por_medio
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    etiqueta = desde.isoformat() if desde == hasta else f"{desde.isoformat()} .. {hasta.isoformat()}"
    print(f"Periodo: {etiqueta} · {_num(total)} noticias\n")
    if not por_fecha:
        print("No hay noticias guardadas en ese periodo.")
        return 0

    print("Por fecha")
    print(
        _tabla(
            ["FECHA", "NOTICIAS"],
            [(f["fecha"].isoformat(), _num(f["noticias"])) for f in por_fecha],
            alinear_derecha=(1,),
        )
    )
    print("\nPor medio")
    print(
        _tabla(
            ["MEDIO", "ÁMBITO", "COMUNIDAD", "NOTICIAS"],
            [
                (m["nombre"], m["ambito"], m["comunidad"] or "", _num(m["noticias"]))
                for m in por_medio
            ],
            alinear_derecha=(3,),
        )
    )
    return 0


def _fila_exportacion(fila: dict, ajustes: Ajustes) -> dict:
    publicacion = fila.get("fecha_publicacion")
    if publicacion is not None:
        try:
            from zoneinfo import ZoneInfo

            publicacion = publicacion.astimezone(ZoneInfo(ajustes.zona))
        except Exception:  # pragma: no cover
            pass
    return {
        "fecha": fila["fecha"].isoformat(),
        "hora_publicacion": publicacion.strftime("%Y-%m-%d %H:%M:%S") if publicacion else "",
        "medio": fila["medio"],
        "ambito": fila["ambito"],
        "comunidad": fila["comunidad"] or "",
        "seccion": fila["seccion"] or "",
        "titular": fila["titular"],
        "resumen": fila["resumen"] or "",
        "url": fila["url"],
        "autor": fila["autor"] or "",
        "fecha_estimada": "si" if fila["fecha_estimada"] else "no",
        "origen": fila["origen"],
    }


def cmd_exportar(ajustes: Ajustes, args) -> int:
    desde, hasta = _rango_fechas(args, ajustes)
    if args.medio:
        seleccionar_medios([args.medio])  # valida la clave

    with BaseDatos(ajustes.database_url) as db:
        db.verificar_esquema()
        filas = db.exportar(desde, hasta, args.medio)

    if not filas:
        print("No hay noticias que exportar en ese periodo.", file=sys.stderr)
        return 0

    datos = [_fila_exportacion(fila, ajustes) for fila in filas]
    salida_stdout = args.salida in (None, "-")

    if salida_stdout:
        destino = sys.stdout
        cerrar = False
    else:
        destino = open(args.salida, "w", encoding="utf-8-sig" if args.formato == "csv" else "utf-8", newline="")
        cerrar = True

    try:
        if args.formato == "csv":
            escritor = csv.DictWriter(destino, fieldnames=CAMPOS_CSV, extrasaction="ignore")
            escritor.writeheader()
            escritor.writerows(datos)
        else:
            for fila in datos:
                destino.write(json.dumps(fila, ensure_ascii=False) + "\n")
    finally:
        if cerrar:
            destino.close()

    if salida_stdout:
        print(f"Exportadas {_num(len(datos))} noticias por stdout.", file=sys.stderr)
    else:
        print(f"Exportadas {_num(len(datos))} noticias a {Path(args.salida)}")
    return 0


def cmd_mantener(ajustes: Ajustes, args) -> int:
    if args.dias < 1:
        raise ValueError("--dias debe ser al menos 1.")
    if args.capturas_dias < 1:
        raise ValueError("--capturas-dias debe ser al menos 1.")

    corte = _hoy(ajustes) - timedelta(days=args.dias)
    corte_capturas = datetime.now().astimezone() - timedelta(days=args.capturas_dias)

    with BaseDatos(ajustes.database_url) as db:
        db.verificar_esquema()
        noticias = db.contar_anteriores(corte)
        print(
            f"Se borrarán {_num(noticias)} noticias anteriores a {corte.isoformat()} "
            f"y las capturas anteriores a {corte_capturas.strftime('%Y-%m-%d %H:%M')}."
        )
        if args.simular:
            print("Simulación: no se ha borrado nada.")
            return 0

        if not args.si:
            if not sys.stdin.isatty():
                raise ValueError("Sin terminal interactiva: repite el comando con --si.")
            respuesta = input("¿Continuar? [s/N] ").strip().lower()
            if respuesta not in ("s", "si", "sí", "y", "yes"):
                print("Cancelado.")
                return 0

        borradas = db.borrar_anteriores(corte)
        capturas = db.borrar_capturas_anteriores(corte_capturas)

    print(f"Borradas {_num(borradas)} noticias y {_num(capturas)} capturas.")
    return 0


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------
def construir_parser() -> argparse.ArgumentParser:
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument(
        "--base-datos",
        metavar="DSN",
        help="Cadena de conexión PostgreSQL (por defecto DATABASE_URL).",
    )
    comun.add_argument("-v", "--verbose", action="store_true", help="Muestra trazas detalladas.")

    parser = argparse.ArgumentParser(
        prog="antifasis",
        description=(
            "Extrae titulares de los 20 principales medios españoles y los guarda en "
            "PostgreSQL, indexados por fecha de publicación."
        ),
        epilog=(
            "Ejemplos:\n"
            "  python -m antifasis init-db\n"
            "  python -m antifasis actualizar\n"
            "  python -m antifasis actualizar --medio elpais --medio elconfidencial\n"
            "  python -m antifasis resumen --fecha 2026-10-27\n"
            "  python -m antifasis exportar --desde 2026-10-01 --hasta 2026-10-31 --formato csv\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"Antifasis {__version__}")

    sub = parser.add_subparsers(dest="comando", metavar="COMANDO")

    p_init = sub.add_parser("init-db", parents=[comun], help="Crea el esquema y registra los medios.")
    p_init.set_defaults(func=cmd_init_db)

    p_listar = sub.add_parser("listar-medios", parents=[comun], help="Muestra el catálogo de medios.")
    p_listar.set_defaults(func=cmd_listar_medios)

    p_act = sub.add_parser(
        "actualizar",
        parents=[comun],
        help="Descarga las noticias y las guarda en PostgreSQL.",
    )
    p_act.add_argument(
        "--medio",
        action="append",
        metavar="CLAVE",
        help="Limita la ejecución a uno o varios medios (repetible o separado por comas).",
    )
    p_act.add_argument(
        "--limite",
        type=int,
        metavar="N",
        help="Máximo de noticias por medio (0 = sin límite; por defecto ANTIFASIS_LIMITE).",
    )
    p_act.add_argument(
        "--dias-max",
        type=int,
        metavar="N",
        help="Descarta noticias con más de N días (0 = sin límite; por defecto 30).",
    )
    p_act.add_argument(
        "--sin-robots",
        action="store_true",
        help="No comprobar robots.txt (no recomendado).",
    )
    p_act.add_argument(
        "--dry-run",
        action="store_true",
        help="Extrae y muestra resultados sin escribir en la base de datos.",
    )
    p_act.set_defaults(func=cmd_actualizar)

    p_res = sub.add_parser(
        "resumen", parents=[comun], help="Cuenta las noticias guardadas por fecha y medio."
    )
    p_res.add_argument("--fecha", metavar="AAAA-MM-DD", help="Día concreto (por defecto, hoy).")
    p_res.add_argument("--desde", metavar="AAAA-MM-DD", help="Primer día del rango.")
    p_res.add_argument("--hasta", metavar="AAAA-MM-DD", help="Último día del rango.")
    p_res.add_argument("--json", action="store_true", help="Salida JSON.")
    p_res.set_defaults(func=cmd_resumen)

    p_exp = sub.add_parser(
        "exportar", parents=[comun], help="Exporta titulares a CSV o JSON Lines."
    )
    p_exp.add_argument("--fecha", metavar="AAAA-MM-DD", help="Día concreto (por defecto, hoy).")
    p_exp.add_argument("--desde", metavar="AAAA-MM-DD", help="Primer día del rango.")
    p_exp.add_argument("--hasta", metavar="AAAA-MM-DD", help="Último día del rango.")
    p_exp.add_argument("--medio", metavar="CLAVE", help="Filtra por un medio.")
    p_exp.add_argument(
        "--formato", choices=["csv", "jsonl"], default="csv", help="Formato de salida (csv por defecto)."
    )
    p_exp.add_argument(
        "--salida", metavar="RUTA", default="-", help="Fichero de salida; '-' para stdout (por defecto)."
    )
    p_exp.set_defaults(func=cmd_exportar)

    p_mant = sub.add_parser(
        "mantener", parents=[comun], help="Borra noticias y capturas antiguas."
    )
    p_mant.add_argument("--dias", type=int, default=365, help="Conserva los últimos N días (365).")
    p_mant.add_argument(
        "--capturas-dias", type=int, default=90, help="Conserva las capturas de los últimos N días (90)."
    )
    p_mant.add_argument("--simular", action="store_true", help="Solo muestra cuánto se borraría.")
    p_mant.add_argument("--si", action="store_true", help="No pide confirmación.")
    p_mant.set_defaults(func=cmd_mantener)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "comando", None):
        parser.print_help()
        return 0

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    try:
        ajustes = cargar_ajustes(args.base_datos)
        return int(args.func(ajustes, args))
    except BrokenPipeError:  # pragma: no cover - al canalizar a head
        return 0
    except (ErrorConfiguracion, ErrorMedio, ErrorBaseDatos, ValueError, OSError) as exc:
        _error(str(exc))
        return 2
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130
