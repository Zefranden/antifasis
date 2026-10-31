"""Extracción de noticias desde RSS y, como respaldo, desde portadas HTML."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import feedparser
from bs4 import BeautifulSoup

from .config import Ajustes
from .fechas import (
    ahora_utc,
    fecha_local,
    fecha_para_noticia,
    parsear_fecha,
    struct_a_datetime,
    validar_publicacion,
)
from .http import Respuesta, SesionHTTP
from .medios import Medio
from .modelos import Noticia, ResultadoMedio
from .texto import (
    es_url_probable_articulo,
    extraer_primera_imagen,
    hash_url,
    limpiar_autor,
    limpiar_html,
    limpiar_titular,
    mismo_dominio,
    normalizar_url,
    parece_titular,
    seccion_desde_url,
    truncar,
)

LOG = logging.getLogger(__name__)

MAX_RESUMEN = 600
MAX_ENTRADAS_FEED = 1000

TIPOS_ARTICULO = {
    "Article",
    "AdvertiserContentArticle",
    "AnalysisNewsArticle",
    "BackgroundNewsArticle",
    "NewsArticle",
    "OpinionNewsArticle",
    "ReportageNewsArticle",
    "ReviewNewsArticle",
    "SatiricalArticle",
    "ScholarlyArticle",
    "TechArticle",
}

SECCIONES_GENERICAS = {
    "actualidad",
    "home",
    "inicio",
    "noticias",
    "portada",
    "principal",
    "última hora",
    "ultima hora",
}

TEXTO_RUIDO = {
    "actualidad",
    "buscar",
    "ciencia",
    "cultura",
    "deportes",
    "economía",
    "economia",
    "educación",
    "educacion",
    "el tiempo",
    "empresas",
    "inicio",
    "internacional",
    "menú",
    "menu",
    "motor",
    "noticias",
    "opinión",
    "opinion",
    "política",
    "politica",
    "portada",
    "salud",
    "sociedad",
    "suscríbete",
    "suscribete",
    "tecnología",
    "tecnologia",
    "turismo",
    "última hora",
    "ultima hora",
    "viajes",
    "vídeos",
    "videos",
}

RUTAS_RUIDO = re.compile(
    r"/(rss|feed|tag|tags|autor|autores|firmas|newsletter|newsletters|buscar|search|"
    r"login|registro|suscripcion|aviso-legal|politica-de-privacidad|contacto|"
    r"publicidad|patrocinado|branded|todos-contamos)(/|$)",
    re.IGNORECASE,
)


# ----------------------------------------------------------------------
# Construcción común
# ----------------------------------------------------------------------
def _construir_noticia(
    medio: Medio,
    titular: str,
    url: str,
    zona: str,
    ahora: datetime,
    *,
    fecha_publicacion: Optional[datetime] = None,
    resumen: Optional[str] = None,
    seccion: Optional[str] = None,
    autor: Optional[str] = None,
    guid: Optional[str] = None,
    imagen_url: Optional[str] = None,
    origen: str = "rss",
) -> Optional[Noticia]:
    titular = limpiar_titular(titular)
    url_normalizada = normalizar_url(url)
    if not url_normalizada or not parece_titular(titular):
        return None

    publicacion = validar_publicacion(fecha_publicacion, ahora)
    fecha, estimada = fecha_para_noticia(publicacion, url_normalizada, zona, ahora)

    resumen_limpio = truncar(limpiar_html(resumen), MAX_RESUMEN) if resumen else ""
    if len(resumen_limpio) < 20 or resumen_limpio.lower() == titular.lower():
        resumen_limpio = ""

    return Noticia(
        medio_clave=medio.clave,
        titular=titular,
        url=url_normalizada,
        fecha=fecha,
        fecha_publicacion=publicacion,
        fecha_estimada=estimada,
        resumen=resumen_limpio or None,
        seccion=truncar(limpiar_html(seccion), 80) if seccion else seccion_desde_url(url_normalizada),
        autor=limpiar_autor(autor),
        guid=truncar(str(guid), 500) if guid else None,
        imagen_url=normalizar_url(imagen_url) if imagen_url else None,
        idioma=medio.idioma,
        origen=origen,
    )


def _fecha_de_entrada(entrada, zona: str) -> Optional[datetime]:
    for clave in ("published_parsed", "updated_parsed", "created_parsed"):
        valor = struct_a_datetime(entrada.get(clave))
        if valor is not None:
            return valor
    for clave in ("published", "updated", "created", "dc_date"):
        valor = parsear_fecha(entrada.get(clave), zona)
        if valor is not None:
            return valor
    return None


def _seccion_de_tags(entrada) -> Optional[str]:
    for etiqueta in entrada.get("tags") or []:
        termino = etiqueta.get("term") if isinstance(etiqueta, dict) else str(etiqueta)
        termino = limpiar_html(termino)
        if not termino or len(termino) > 40:
            continue
        minusculas = termino.lower()
        if minusculas in SECCIONES_GENERICAS or minusculas.startswith("artículos"):
            continue
        return termino[:1].upper() + termino[1:]
    return None


def _autor_de_entrada(entrada) -> Optional[str]:
    autor = entrada.get("author")
    if not autor and entrada.get("authors"):
        nombres = []
        for persona in entrada.get("authors") or []:
            if isinstance(persona, dict) and persona.get("name"):
                nombres.append(persona["name"])
        autor = ", ".join(nombres)
    return limpiar_autor(autor)


def _imagen_de_entrada(entrada) -> Optional[str]:
    for clave in ("media_content", "media_thumbnail"):
        for medio in entrada.get(clave) or []:
            if isinstance(medio, dict) and medio.get("url"):
                return normalizar_url(medio["url"])
    for enlace in entrada.get("links") or []:
        if enlace.get("rel") == "enclosure" and str(enlace.get("type", "")).startswith("image/"):
            return normalizar_url(enlace.get("href"))
    for contenido in entrada.get("content") or []:
        imagen = extraer_primera_imagen(contenido.get("value"))
        if imagen:
            return imagen
    return extraer_primera_imagen(entrada.get("summary"))


def _url_de_entrada(entrada, url_feed: str) -> Optional[str]:
    enlace = entrada.get("link")
    if not enlace:
        for candidato in entrada.get("links") or []:
            if candidato.get("href") and candidato.get("rel") in (None, "alternate"):
                enlace = candidato["href"]
                break
    if not enlace:
        identificador = entrada.get("id") or entrada.get("guid")
        if identificador and str(identificador).startswith(("http://", "https://")):
            enlace = identificador
    return normalizar_url(enlace, url_feed) if enlace else None


def _resumen_de_entrada(entrada) -> Optional[str]:
    resumen = entrada.get("summary") or entrada.get("description")
    if not resumen:
        for contenido in entrada.get("content") or []:
            if contenido.get("value"):
                resumen = contenido["value"]
                break
    return resumen


def extraer_feed(
    contenido: bytes,
    url_feed: str,
    medio: Medio,
    zona: str,
    ahora: Optional[datetime] = None,
    origen: str = "rss",
) -> Tuple[List[Noticia], List[str]]:
    """Convierte un feed RSS/Atom en noticias normalizadas."""
    ahora = ahora or ahora_utc()
    errores: List[str] = []
    analizado = feedparser.parse(contenido)

    if analizado.bozo and not analizado.entries:
        detalle = getattr(analizado, "bozo_exception", "formato no reconocido")
        errores.append(f"RSS no válido: {detalle}")
        return [], errores
    if not analizado.entries:
        errores.append("El feed no contiene entradas")
        return [], errores

    noticias: List[Noticia] = []
    for entrada in analizado.entries[:MAX_ENTRADAS_FEED]:
        url = _url_de_entrada(entrada, url_feed)
        if not url:
            continue

        titular = entrada.get("title") or ""
        publicacion = _fecha_de_entrada(entrada, zona)
        noticia = _construir_noticia(
            medio,
            titular,
            url,
            zona,
            ahora,
            fecha_publicacion=publicacion,
            resumen=_resumen_de_entrada(entrada),
            seccion=seccion_desde_url(url) or _seccion_de_tags(entrada),
            autor=_autor_de_entrada(entrada),
            guid=entrada.get("id") or entrada.get("guid"),
            imagen_url=_imagen_de_entrada(entrada),
            origen=origen,
        )
        if noticia is not None:
            noticias.append(noticia)

    if not noticias and analizado.entries:
        errores.append("El feed no contiene titulares utilizables")
    return noticias, errores


# ----------------------------------------------------------------------
# Descubrimiento de feeds
# ----------------------------------------------------------------------
def _puntuacion_feed(url: str) -> int:
    minusculas = url.lower()
    puntos = 0
    if any(palabra in minusculas for palabra in ("portada", "home", "ultima-hora", "última-hora")):
        puntos += 3
    if "rss" in minusculas or "feed" in minusculas or "atom" in minusculas:
        puntos += 1
    if minusculas.endswith((".xml", ".rss")):
        puntos += 1
    return puntos


def descubrir_feeds(html: str, url_pagina: str) -> List[str]:
    """Busca enlaces RSS/Atom declarados en la portada."""
    sopa = BeautifulSoup(html, "html.parser")
    candidatos: List[str] = []

    for enlace in sopa.find_all("link", href=True):
        tipo = (enlace.get("type") or "").lower()
        if "rss" in tipo or "atom" in tipo:
            url = normalizar_url(enlace["href"], url_pagina)
            if url:
                candidatos.append(url)

    for ancla in sopa.find_all("a", href=True):
        href = ancla["href"]
        if re.search(r"(rss|feed|atom)", href, re.IGNORECASE):
            url = normalizar_url(href, url_pagina)
            if url:
                candidatos.append(url)

    vistos = set()
    unicos = []
    for url in candidatos:
        if url in vistos:
            continue
        vistos.add(url)
        unicos.append(url)

    unicos.sort(key=_puntuacion_feed, reverse=True)
    return unicos[:5]


# ----------------------------------------------------------------------
# Extracción desde HTML
# ----------------------------------------------------------------------
def _recorrer_json_ld(dato) -> Iterator[dict]:
    if isinstance(dato, dict):
        yield dato
        for valor in dato.values():
            yield from _recorrer_json_ld(valor)
    elif isinstance(dato, list):
        for elemento in dato:
            yield from _recorrer_json_ld(elemento)


def _tipos_json_ld(objeto: dict) -> set:
    tipos = objeto.get("@type")
    if isinstance(tipos, str):
        return {tipos}
    if isinstance(tipos, list):
        return {str(t) for t in tipos}
    return set()


def _autores_json_ld(valor) -> Optional[str]:
    if isinstance(valor, str):
        return valor
    if isinstance(valor, dict):
        return valor.get("name")
    if isinstance(valor, list):
        nombres = [_autores_json_ld(item) for item in valor]
        return ", ".join(n for n in nombres if n) or None
    return None


def _imagen_json_ld(valor) -> Optional[str]:
    if isinstance(valor, str):
        return valor
    if isinstance(valor, dict):
        return valor.get("url") or valor.get("contentUrl")
    if isinstance(valor, list):
        for item in valor:
            encontrada = _imagen_json_ld(item)
            if encontrada:
                return encontrada
    return None


def _desde_json_ld(
    sopa: BeautifulSoup, url_pagina: str, medio: Medio, zona: str, ahora: datetime
) -> List[Noticia]:
    noticias: List[Noticia] = []
    for etiqueta in sopa.find_all("script", attrs={"type": "application/ld+json"}):
        crudo = etiqueta.string or etiqueta.get_text()
        if not crudo or not crudo.strip():
            continue
        try:
            datos = json.loads(crudo)
        except (json.JSONDecodeError, TypeError):
            continue

        for objeto in _recorrer_json_ld(datos):
            if not (_tipos_json_ld(objeto) & TIPOS_ARTICULO):
                continue

            titular = objeto.get("headline") or objeto.get("name")
            enlace = objeto.get("url") or objeto.get("mainEntityOfPage") or objeto.get("@id")
            if isinstance(enlace, dict):
                enlace = enlace.get("@id") or enlace.get("url")
            if not titular or not enlace:
                continue

            url = normalizar_url(enlace, url_pagina)
            if not url or not mismo_dominio(url, url_pagina):
                continue

            publicacion = parsear_fecha(objeto.get("datePublished") or objeto.get("dateCreated"), zona)
            noticia = _construir_noticia(
                medio,
                titular,
                url,
                zona,
                ahora,
                fecha_publicacion=publicacion,
                resumen=objeto.get("description"),
                seccion=objeto.get("articleSection") or seccion_desde_url(url),
                autor=_autores_json_ld(objeto.get("author")),
                guid=objeto.get("@id"),
                imagen_url=_imagen_json_ld(objeto.get("image")),
                origen="html",
            )
            if noticia is not None:
                noticias.append(noticia)
    return noticias


def _desde_articulos(
    sopa: BeautifulSoup, url_pagina: str, medio: Medio, zona: str, ahora: datetime
) -> List[Noticia]:
    noticias: List[Noticia] = []

    for articulo in sopa.find_all("article"):
        encabezado = articulo.find(["h1", "h2", "h3", "h4"])
        enlace = None
        titular = ""

        if encabezado is not None:
            titular = limpiar_titular(encabezado.get_text(" ", strip=True))
            if encabezado.name == "a" and encabezado.get("href"):
                enlace = encabezado
            else:
                enlace = encabezado.find("a", href=True) or encabezado.find_parent("a", href=True)

        if enlace is None:
            for ancla in articulo.find_all("a", href=True):
                texto = limpiar_titular(ancla.get_text(" ", strip=True))
                if 30 <= len(texto) <= 250:
                    enlace = ancla
                    if not titular:
                        titular = texto
                    break

        if enlace is None or not enlace.get("href"):
            continue

        if not titular:
            titular = limpiar_titular(enlace.get("title") or enlace.get_text(" ", strip=True))

        url = normalizar_url(enlace["href"], url_pagina)
        if not url or not mismo_dominio(url, url_pagina) or not es_url_probable_articulo(url):
            continue

        resumen = None
        for parrafo in articulo.find_all("p")[:5]:
            texto = limpiar_html(parrafo.get_text(" ", strip=True))
            if len(texto) >= 60 and texto.lower() != titular.lower() and texto.lower() not in titular.lower():
                resumen = texto
                break

        publicacion = None
        marca_tiempo = articulo.find("time")
        if marca_tiempo is not None:
            publicacion = parsear_fecha(
                marca_tiempo.get("datetime") or marca_tiempo.get_text(" ", strip=True), zona
            )

        noticia = _construir_noticia(
            medio,
            titular,
            url,
            zona,
            ahora,
            fecha_publicacion=publicacion,
            resumen=resumen,
            seccion=seccion_desde_url(url),
            origen="html",
        )
        if noticia is not None:
            noticias.append(noticia)

    return noticias


def _es_ruido(url: str, titular: str) -> bool:
    ruta = urlsplit(url).path.lower()
    if RUTAS_RUIDO.search(ruta):
        return True
    minusculas = titular.lower().strip(" »·-|")
    if minusculas in TEXTO_RUIDO:
        return True
    if minusculas.startswith(("ver ", "más ", "mas ", "todos ", "todas ", "ir a ")):
        return True
    return False


def _desde_enlaces(
    sopa: BeautifulSoup, url_pagina: str, medio: Medio, zona: str, ahora: datetime
) -> List[Noticia]:
    noticias: List[Noticia] = []
    vistos = set()

    for ancla in sopa.find_all("a", href=True):
        if ancla.get("aria-hidden") == "true":
            continue

        titular = limpiar_titular(ancla.get_text(" ", strip=True))
        if not parece_titular(titular):
            titular = limpiar_titular(ancla.get("title") or "")
        if not parece_titular(titular):
            continue

        url = normalizar_url(ancla["href"], url_pagina)
        if not url or not mismo_dominio(url, url_pagina):
            continue
        if not es_url_probable_articulo(url) or _es_ruido(url, titular):
            continue
        if url in vistos:
            continue
        vistos.add(url)

        noticia = _construir_noticia(
            medio,
            titular,
            url,
            zona,
            ahora,
            seccion=seccion_desde_url(url),
            origen="html",
        )
        if noticia is not None:
            noticias.append(noticia)

    return noticias


def _completar(destino: Noticia, origen: Noticia) -> None:
    if not destino.resumen and origen.resumen:
        destino.resumen = origen.resumen
    if not destino.seccion and origen.seccion:
        destino.seccion = origen.seccion
    if not destino.autor and origen.autor:
        destino.autor = origen.autor
    if not destino.imagen_url and origen.imagen_url:
        destino.imagen_url = origen.imagen_url
    if not destino.guid and origen.guid:
        destino.guid = origen.guid
    if destino.fecha_publicacion is None and origen.fecha_publicacion is not None:
        destino.fecha_publicacion = origen.fecha_publicacion
        destino.fecha = origen.fecha
        destino.fecha_estimada = origen.fecha_estimada
    if destino.origen == "html" and origen.origen == "rss":
        destino.origen = "rss"


def fusionar(actuales: Sequence[Noticia], nuevas: Iterable[Noticia]) -> List[Noticia]:
    """Une dos lotes sin duplicar URLs y completa campos que falten."""
    por_hash: Dict[str, Noticia] = {}
    orden: List[Noticia] = []

    for noticia in list(actuales) + list(nuevas):
        clave = hash_url(noticia.url)
        existente = por_hash.get(clave)
        if existente is None:
            por_hash[clave] = noticia
            orden.append(noticia)
        else:
            _completar(existente, noticia)
    return orden


def extraer_html(
    html: str,
    url_pagina: str,
    medio: Medio,
    zona: str,
    ahora: Optional[datetime] = None,
    limite: int = 100,
) -> List[Noticia]:
    """Extrae titulares de una portada HTML combinando JSON-LD, <article> y enlaces."""
    ahora = ahora or ahora_utc()
    sopa = BeautifulSoup(html, "html.parser")
    tope = limite if limite else 500

    noticias = _desde_json_ld(sopa, url_pagina, medio, zona, ahora)

    for etiqueta in sopa(["script", "style", "noscript", "template", "svg"]):
        etiqueta.decompose()

    noticias.extend(_desde_articulos(sopa, url_pagina, medio, zona, ahora))
    if len(noticias) < tope:
        noticias.extend(_desde_enlaces(sopa, url_pagina, medio, zona, ahora))

    return fusionar([], noticias)[:tope]


# ----------------------------------------------------------------------
# Orquestación por medio
# ----------------------------------------------------------------------
def extraer_medio(
    medio: Medio,
    cliente: SesionHTTP,
    ajustes: Ajustes,
    ahora: Optional[datetime] = None,
    limite: Optional[int] = None,
) -> ResultadoMedio:
    """Extrae un medio probando RSS, descubrimiento en portada y HTML."""
    inicio = ahora_utc()
    ahora = ahora or inicio
    tope = ajustes.limite if limite is None else limite
    resultado = ResultadoMedio(medio=medio, iniciada_en=inicio)
    t0 = time.monotonic()

    noticias: List[Noticia] = []
    metodo: Optional[str] = None
    ultimo_estado: Optional[int] = None
    portada: Optional[Respuesta] = None
    portada_intentada = False

    def cargar_portada() -> Optional[Respuesta]:
        nonlocal portada, portada_intentada, ultimo_estado
        if not portada_intentada:
            portada_intentada = True
            portada = cliente.descargar(medio.url_base)
            ultimo_estado = portada.estado or ultimo_estado
            if not portada.ok:
                resultado.anotar_error(f"Portada: {portada.error}")
        return portada

    # 1. Feed configurado.
    if medio.metodo in ("rss", "auto") and medio.feed_url:
        respuesta = cliente.descargar(medio.feed_url)
        ultimo_estado = respuesta.estado or ultimo_estado
        if respuesta.ok:
            lote, errores = extraer_feed(respuesta.contenido, respuesta.url, medio, ajustes.zona, ahora)
            for error in errores:
                resultado.anotar_error(error)
            if lote:
                noticias = lote
                metodo = "rss"
        else:
            resultado.anotar_error(f"RSS: {respuesta.error}")

    # 2. Si no hay nada, descubrir el feed en la portada. En modo `html`
    #    vamos directamente a la portada para no intentar feeds roto.
    if not noticias and medio.metodo in ("rss", "auto"):
        home = cargar_portada()
        if home is not None and home.ok:
            descubiertos = descubrir_feeds(home.texto(), home.url)
            for candidato in descubiertos:
                if candidato == medio.feed_url:
                    continue
                respuesta = cliente.descargar(candidato)
                ultimo_estado = respuesta.estado or ultimo_estado
                if not respuesta.ok:
                    continue
                lote, errores = extraer_feed(
                    respuesta.contenido, respuesta.url, medio, ajustes.zona, ahora, origen="descubierto"
                )
                for error in errores:
                    resultado.anotar_error(error)
                if lote:
                    noticias = lote
                    metodo = "rss (descubierto)"
                    break
            if not noticias:
                resultado.anotar_error("No se encontró un feed alternativo en la portada")

    # 3. Respaldo HTML.
    necesita_html = medio.metodo == "html" or (
        medio.metodo == "auto" and len(noticias) < medio.minimo_antes_de_html
    )
    if necesita_html:
        home = cargar_portada()
        if home is not None and home.ok:
            margen = max(20, (tope - len(noticias)) if tope else 200)
            lote = extraer_html(home.texto(), home.url, medio, ajustes.zona, ahora, margen)
            if lote:
                noticias = fusionar(noticias, lote)
                metodo = f"{metodo}+html" if metodo else "html"
            else:
                resultado.anotar_error("No se encontraron titulares en la portada HTML")
        elif home is not None:
            resultado.anotar_error(f"No se pudo leer la portada: {home.error}")

    # Deduplicación final (un mismo feed puede repetir la misma URL).
    noticias = fusionar([], noticias)

    # Los feeds suelen arrastrar piezas antiguas o páginas de agenda. Se
    # descartan antes de aplicar el límite para no gastar cupo en ellas.
    if ajustes.dias_max:
        corte = fecha_local(ahora, ajustes.zona) - timedelta(days=ajustes.dias_max)
        noticias = [n for n in noticias if n.fecha >= corte]

    if tope:
        noticias = noticias[:tope]

    resultado.noticias = noticias
    resultado.metodo = metodo
    resultado.http_status = ultimo_estado
    resultado.finalizada_en = ahora_utc()
    resultado.duracion_ms = int((time.monotonic() - t0) * 1000)

    if noticias and not resultado.errores:
        resultado.estado = "ok"
    elif noticias:
        resultado.estado = "parcial"
    else:
        resultado.estado = "error"
        if not resultado.errores:
            resultado.anotar_error("Sin noticias")
    return resultado
