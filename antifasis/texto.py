"""Utilidades de texto: limpieza de HTML, URLs canónicas y secciones."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

# Parámetros de seguimiento que no identifican el contenido.
PARAMETROS_SEGUIMIENTO = {
    "_ga",
    "_gl",
    "campaign",
    "cmpid",
    "dclid",
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "msclkid",
    "oly_anon_id",
    "oly_enc_id",
    "pk_campaign",
    "pk_kwd",
    "ref",
    "referrer",
    "s_cid",
    "source",
    "vero_id",
}

PATRONES_FECHA_URL = (
    re.compile(r"/(?P<anio>20\d{2})-(?P<mes>\d{2})-(?P<dia>\d{2})(?:/|$)"),
    re.compile(r"/(?P<anio>20\d{2})/(?P<mes>\d{2})/(?P<dia>\d{2})(?:/|$)"),
    re.compile(r"/(?P<anio>20\d{2})(?P<mes>\d{2})(?P<dia>\d{2})(?!\d)"),
)

SECCIONES_URL = {
    "actualidad": "Actualidad",
    "africa": "África",
    "america": "América",
    "america-latina": "América Latina",
    "asia": "Asia",
    "andalucia": "Andalucía",
    "aragon": "Aragón",
    "asturias": "Asturias",
    "baleares": "Illes Balears",
    "baskonia": "Deportes",
    "bolsa": "Bolsa",
    "cantabria": "Cantabria",
    "canarias": "Canarias",
    "castilla-la-mancha": "Castilla-La Mancha",
    "castilla-y-leon": "Castilla y León",
    "cataluna": "Cataluña",
    "ceuta": "Ceuta",
    "ciencia": "Ciencia",
    "comunidad-valenciana": "Comunidad Valenciana",
    "cultura": "Cultura",
    "deportes": "Deportes",
    "economia": "Economía",
    "educacion": "Educación",
    "eeuu": "Estados Unidos",
    "elecciones": "Elecciones",
    "europa": "Europa",
    "empresa": "Empresa",
    "empresas": "Empresas",
    "espana": "España",
    "estilo": "Estilo",
    "extremadura": "Extremadura",
    "finanzas": "Finanzas",
    "formacion": "Formación",
    "galicia": "Galicia",
    "gastronomia": "Gastronomía",
    "gente": "Gente",
    "gradario": "Deportes",
    "internacional": "Internacional",
    "la-rioja": "La Rioja",
    "madrid": "Madrid",
    "medio-ambiente": "Medio ambiente",
    "melilla": "Melilla",
    "mercados": "Mercados",
    "moda": "Moda",
    "motor": "Motor",
    "mundial": "Mundial",
    "mundo": "Mundo",
    "murcia": "Murcia",
    "nacional": "Nacional",
    "navarra": "Navarra",
    "ocio": "Ocio",
    "ocio-y-cultura": "Ocio y cultura",
    "opinion": "Opinión",
    "pais-vasco": "País Vasco",
    "politica": "Política",
    "salud": "Salud",
    "sociedad": "Sociedad",
    "somosagro": "Somos Agro",
    "somosmar": "Somos Mar",
    "sucesos": "Sucesos",
    "tecnologia": "Tecnología",
    "television": "Televisión",
    "turismo": "Turismo",
    "viajes": "Viajes",
    "vivienda": "Vivienda",
}

_ESPACIOS = re.compile(r"\s+")
_CARACTERES_INVISIBLES = re.compile(r"[\u200b\u200c\u200d\ufeff\u00ad]")


def limpiar_html(valor: Optional[str]) -> str:
    """Convierte HTML en texto plano y normaliza espacios."""
    if not valor:
        return ""
    texto = str(valor)
    if "<" in texto and ">" in texto:
        sopa = BeautifulSoup(texto, "html.parser")
        for etiqueta in sopa(["script", "style", "noscript"]):
            etiqueta.decompose()
        texto = sopa.get_text(" ", strip=True)
    texto = html.unescape(texto)
    texto = _CARACTERES_INVISIBLES.sub("", texto)
    return _ESPACIOS.sub(" ", texto).strip()


def limpiar_titular(valor: Optional[str]) -> str:
    """Limpia y acota un titular."""
    return truncar(limpiar_html(valor), 500)


def limpiar_autor(valor: Optional[str]) -> Optional[str]:
    """Normaliza el autor; devuelve None si no aporta información."""
    if not valor:
        return None
    autor = limpiar_html(valor)
    autor = re.sub(r"^(por|by)\s+", "", autor, flags=re.IGNORECASE).strip(" ,;|-")
    if not autor or len(autor) < 2:
        return None
    return truncar(autor, 160)


def truncar(texto: str, maximo: int) -> str:
    """Recorta por palabra y añade puntos suspensivos."""
    texto = (texto or "").strip()
    if maximo <= 1:
        return ""
    if len(texto) <= maximo:
        return texto
    corte = texto[: maximo - 1].rsplit(" ", 1)[0].rstrip(" ,;:.·-")
    if not corte:
        corte = texto[: maximo - 1].rstrip()
    return corte + "…"


def normalizar_url(url: Optional[str], base: Optional[str] = None) -> Optional[str]:
    """Devuelve una URL http(s) absoluta sin fragmento ni parámetros de tracking."""
    if not url:
        return None
    url = str(url).strip()
    if not url or url.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    if base:
        url = urljoin(base, url)

    try:
        partes = urlsplit(url)
        puerto = partes.port
    except ValueError:
        return None

    esquema = partes.scheme.lower()
    if esquema not in ("http", "https"):
        return None

    host = (partes.hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        return None
    if partes.username or partes.password:
        return None

    if puerto and not ((esquema == "http" and puerto == 80) or (esquema == "https" and puerto == 443)):
        host = f"{host}:{puerto}"

    ruta = re.sub(r"/{2,}", "/", partes.path or "/")
    if ruta != "/":
        ruta = ruta.rstrip("/")

    consulta = []
    for clave, valor in parse_qsl(partes.query, keep_blank_values=True):
        clave_min = clave.lower()
        if clave_min in PARAMETROS_SEGUIMIENTO or clave_min.startswith("utm_"):
            continue
        consulta.append((clave, valor))
    consulta.sort()

    return urlunsplit((esquema, host, ruta, urlencode(consulta, doseq=True), ""))


def url_canonica(url: str) -> str:
    """Forma canónica usada solo para calcular el hash de deduplicación."""
    limpia = normalizar_url(url)
    partes = urlsplit(limpia or url)
    host = (partes.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    ruta = partes.path.rstrip("/") or "/"
    consulta = urlencode(sorted(parse_qsl(partes.query, keep_blank_values=True)), doseq=True)
    return urlunsplit(("https", host, ruta, consulta, ""))


def hash_url(url: str) -> str:
    """SHA-256 de la URL canónica."""
    return hashlib.sha256(url_canonica(url).encode("utf-8")).hexdigest()


def mismo_dominio(url_a: str, url_b: str) -> bool:
    """Compara dominios ignorando ``www.``."""
    host_a = (urlsplit(url_a).hostname or "").lower()
    host_b = (urlsplit(url_b).hostname or "").lower()
    return host_a.removeprefix("www.") == host_b.removeprefix("www.")


def es_url_probable_articulo(url: str) -> bool:
    """Heurística para descartar portadas, secciones y páginas de servicio."""
    partes = urlsplit(url)
    ruta = partes.path.lower()
    if ruta in ("", "/"):
        return False
    if re.search(
        r"/(rss|feed|tag|tags|autor|autores|firmas|newsletter|newsletters|buscar|search|"
        r"login|registro|suscripcion|publicidad|patrocinado|branded|todos-contamos|ideas)(/|$)",
        ruta,
    ):
        return False
    if ruta.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".mp3", ".mp4", ".zip")):
        return False
    if any(patron.search(ruta) for patron in PATRONES_FECHA_URL):
        return True

    segmentos = [s for s in ruta.split("/") if s]
    if len(segmentos) < 2:
        return False
    ultimo = segmentos[-1]
    if len(ultimo) >= 25 and ultimo.count("-") >= 3:
        return True
    if ultimo.endswith((".html", ".htm", ".shtml")) and len(ultimo) >= 15:
        return True
    return False


def seccion_desde_url(url: str) -> Optional[str]:
    """Deduce una sección legible a partir de la ruta de la URL."""
    try:
        ruta = urlsplit(url).path.lower()
    except ValueError:
        return None
    for segmento in ruta.split("/"):
        if segmento in SECCIONES_URL:
            return SECCIONES_URL[segmento]
    return None


def extraer_primera_imagen(valor: Optional[str], base: Optional[str] = None) -> Optional[str]:
    """Devuelve la primera imagen de un fragmento HTML."""
    if not valor or "<" not in valor:
        return None
    sopa = BeautifulSoup(valor, "html.parser")
    for img in sopa.find_all("img"):
        for atributo in ("src", "data-src", "data-lazy-src"):
            candidata = img.get(atributo)
            if candidata:
                return normalizar_url(candidata, base)
    return None


def parece_titular(valor: str) -> bool:
    """Filtro mínimo para no guardar migas de pan ni etiquetas de navegación."""
    texto = limpiar_html(valor)
    if len(texto) < 20 or len(texto) > 300:
        return False
    if texto.lower() in {
        "portada",
        "inicio",
        "última hora",
        "ultima hora",
        "noticias",
        "actualidad",
        "menú",
        "menu",
        "buscar",
        "suscríbete",
        "suscribete",
        "iniciar sesión",
        "iniciar sesion",
    }:
        return False
    return True
