"""Catálogo de los 20 medios configurados por defecto.

La lista combina 12 medios nacionales y 8 regionales. Las URLs se comprobaron
en octubre de 2026; si un medio cambia su feed, el programa intenta descubrir
el RSS en la portada y, para los marcados como ``html`` o ``auto``, extrae los
titulares directamente del HTML.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


class ErrorMedio(Exception):
    """El medio solicitado no existe en el catálogo."""


@dataclass(frozen=True)
class Medio:
    clave: str
    nombre: str
    ambito: str
    comunidad: str
    url_base: str
    feed_url: Optional[str]
    metodo: str = "rss"
    idioma: str = "es"
    # En modo `auto`, si el RSS devuelve menos titulares que este umbral se
    # complementa con la portada HTML.
    minimo_antes_de_html: int = 10

    @property
    def es_nacional(self) -> bool:
        return self.ambito == "nacional"


MEDIOS: Tuple[Medio, ...] = (
    # ------------------------------------------------------------------
    # Nacionales
    # ------------------------------------------------------------------
    Medio(
        clave="elpais",
        nombre="El País",
        ambito="nacional",
        comunidad="España",
        url_base="https://elpais.com/",
        feed_url="https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
    ),
    Medio(
        clave="elmundo",
        nombre="El Mundo",
        ambito="nacional",
        comunidad="España",
        url_base="https://www.elmundo.es/",
        feed_url="https://www.elmundo.es/rss/portada.xml",
    ),
    Medio(
        clave="abc",
        nombre="ABC",
        ambito="nacional",
        comunidad="España",
        url_base="https://www.abc.es/",
        feed_url="https://www.abc.es/rss/2.0/portada/",
    ),
    Medio(
        clave="lavanguardia",
        nombre="La Vanguardia",
        ambito="nacional",
        comunidad="Cataluña",
        url_base="https://www.lavanguardia.com/",
        feed_url="https://www.lavanguardia.com/rss/home.xml",
    ),
    Medio(
        clave="eldiario",
        nombre="elDiario.es",
        ambito="nacional",
        comunidad="España",
        url_base="https://www.eldiario.es/",
        feed_url="https://www.eldiario.es/rss/",
    ),
    Medio(
        clave="elconfidencial",
        nombre="El Confidencial",
        ambito="nacional",
        comunidad="España",
        url_base="https://www.elconfidencial.com/",
        feed_url="https://rss.elconfidencial.com/",
        metodo="auto",
        minimo_antes_de_html=12,
    ),
    Medio(
        clave="elperiodico",
        nombre="El Periódico",
        ambito="nacional",
        comunidad="Cataluña",
        url_base="https://www.elperiodico.com/es/",
        feed_url=None,
        metodo="html",
    ),
    Medio(
        clave="larazon",
        nombre="La Razón",
        ambito="nacional",
        comunidad="España",
        url_base="https://www.larazon.es/",
        feed_url="https://www.larazon.es/?outputType=xml",
    ),
    Medio(
        clave="elespanol",
        nombre="El Español",
        ambito="nacional",
        comunidad="España",
        url_base="https://www.elespanol.com/",
        feed_url="https://www.elespanol.com/rss/",
    ),
    Medio(
        clave="20minutos",
        nombre="20 minutos",
        ambito="nacional",
        comunidad="España",
        url_base="https://www.20minutos.es/",
        feed_url="https://www.20minutos.es/rss/",
    ),
    Medio(
        clave="expansion",
        nombre="Expansión",
        ambito="nacional",
        comunidad="España",
        url_base="https://www.expansion.com/",
        feed_url="https://www.expansion.com/rss/portada.xml",
    ),
    Medio(
        clave="infolibre",
        nombre="infoLibre",
        ambito="nacional",
        comunidad="España",
        url_base="https://www.infolibre.es/",
        feed_url="https://www.infolibre.es/rss/",
    ),
    # ------------------------------------------------------------------
    # Regionales
    # ------------------------------------------------------------------
    Medio(
        clave="lavozdegalicia",
        nombre="La Voz de Galicia",
        ambito="regional",
        comunidad="Galicia",
        url_base="https://www.lavozdegalicia.es/",
        feed_url=None,
        metodo="html",
    ),
    Medio(
        clave="elcorreo",
        nombre="El Correo",
        ambito="regional",
        comunidad="País Vasco",
        url_base="https://www.elcorreo.com/",
        feed_url="https://www.elcorreo.com/rss/2.0/?section=",
    ),
    Medio(
        clave="heraldo",
        nombre="Heraldo de Aragón",
        ambito="regional",
        comunidad="Aragón",
        url_base="https://www.heraldo.es/",
        feed_url="https://www.heraldo.es/rss/",
    ),
    Medio(
        clave="diariosur",
        nombre="Diario Sur",
        ambito="regional",
        comunidad="Andalucía",
        url_base="https://www.diariosur.es/",
        feed_url="https://www.diariosur.es/rss/2.0/?section=",
    ),
    Medio(
        clave="levante",
        nombre="Levante-EMV",
        ambito="regional",
        comunidad="Comunidad Valenciana",
        url_base="https://www.levante-emv.com/",
        feed_url="https://www.levante-emv.com/rss/",
    ),
    Medio(
        clave="lne",
        nombre="La Nueva España",
        ambito="regional",
        comunidad="Asturias",
        url_base="https://www.lne.es/",
        feed_url="https://www.lne.es/rss/",
    ),
    Medio(
        clave="canarias7",
        nombre="Canarias7",
        ambito="regional",
        comunidad="Canarias",
        url_base="https://www.canarias7.es/",
        feed_url="https://www.canarias7.es/rss/portada.xml",
    ),
    Medio(
        clave="ultimahora",
        nombre="Última Hora",
        ambito="regional",
        comunidad="Illes Balears",
        url_base="https://www.ultimahora.es/",
        feed_url="https://www.ultimahora.es/feed.rss",
    ),
)

POR_CLAVE: Dict[str, Medio] = {m.clave: m for m in MEDIOS}


def validar_catalogo(medios: Iterable[Medio] = MEDIOS) -> None:
    """Comprueba invariantes básicas del catálogo."""
    claves = set()
    for medio in medios:
        if medio.clave in claves:
            raise ValueError(f"Clave de medio duplicada: {medio.clave}")
        claves.add(medio.clave)
        if medio.metodo not in ("rss", "auto", "html"):
            raise ValueError(f"Método inválido para {medio.clave}: {medio.metodo}")
        if medio.metodo in ("rss", "auto") and not medio.feed_url:
            raise ValueError(f"{medio.clave} usa RSS pero no tiene feed_url")
    if not claves:
        raise ValueError("El catálogo de medios está vacío")


def medios_activos() -> List[Medio]:
    return list(MEDIOS)


def obtener_medio(clave: str) -> Medio:
    try:
        return POR_CLAVE[clave]
    except KeyError as exc:
        raise ErrorMedio(f"Medio desconocido: {clave!r}") from exc


def seleccionar_medios(claves: Optional[Iterable[str]]) -> List[Medio]:
    """Filtra el catálogo por claves, conservando el orden del catálogo.

    Acepta valores repetidos y listas separadas por comas.
    """
    if not claves:
        return medios_activos()

    solicitadas = []
    for valor in claves:
        solicitadas.extend(parte.strip() for parte in str(valor).split(",") if parte.strip())

    desconocidas = [c for c in solicitadas if c not in POR_CLAVE]
    if desconocidas:
        disponibles = ", ".join(sorted(POR_CLAVE))
        raise ErrorMedio(
            f"Medio(s) desconocido(s): {', '.join(desconocidas)}. Disponibles: {disponibles}"
        )

    pedidas = set(solicitadas)
    return [m for m in MEDIOS if m.clave in pedidas]


validar_catalogo()
