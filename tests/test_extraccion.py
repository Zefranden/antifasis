from datetime import date, datetime, timezone

from antifasis.extractores import descubrir_feeds, extraer_feed, extraer_html, fusionar
from antifasis.medios import Medio

MEDIO = Medio(
    clave="ejemplo",
    nombre="Medio de Ejemplo",
    ambito="nacional",
    comunidad="España",
    url_base="https://example.com/",
    feed_url="https://example.com/rss",
)

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Ejemplo</title>
    <link>https://example.com/</link>
    <item>
      <title>Una noticia de prueba con un titular largo</title>
      <link>https://example.com/politica/2026/10/27/noticia-de-prueba/</link>
      <guid>https://example.com/politica/2026/10/27/noticia-de-prueba/</guid>
      <pubDate>Tue, 27 Oct 2026 20:00:00 +0100</pubDate>
      <description><![CDATA[<p>Este es el <b>resumen</b> &amp; la entradilla.</p>]]></description>
      <category>Política</category>
      <dc:creator>Ana Pérez</dc:creator>
    </item>
    <item>
      <title>Otra noticia de prueba con un titular largo</title>
      <link>https://example.com/espana/2026-10-27/otra-noticia/</link>
      <pubDate>Tue, 27 Oct 2026 21:30:00 +0100</pubDate>
      <description>Segundo resumen suficientemente largo.</description>
    </item>
  </channel>
</rss>
"""


def _ahora():
    return datetime(2026, 10, 27, 23, 59, tzinfo=timezone.utc)


def test_extraer_feed_normaliza_campos():
    noticias, errores = extraer_feed(RSS.encode("utf-8"), "https://example.com/rss", MEDIO, "Europe/Madrid", _ahora())
    assert errores == []
    assert len(noticias) == 2

    primera = noticias[0]
    assert primera.titular == "Una noticia de prueba con un titular largo"
    assert primera.fecha == date(2026, 10, 27)
    assert primera.fecha_publicacion == datetime(2026, 10, 27, 19, 0, tzinfo=timezone.utc)
    assert primera.fecha_estimada is False
    assert primera.resumen == "Este es el resumen & la entradilla."
    assert primera.seccion == "Política"
    assert primera.autor == "Ana Pérez"
    assert primera.origen == "rss"
    assert primera.url.endswith("/noticia-de-prueba")


def test_feed_vacio_o_invalido():
    noticias, errores = extraer_feed(b"<html>no soy un feed</html>", "https://example.com/rss", MEDIO, "Europe/Madrid", _ahora())
    assert noticias == []
    assert errores


def test_extraer_html_con_article_y_time():
    html = """
    <html><body>
      <nav><a href="/politica/">Política</a><a href="/">Portada</a></nav>
      <article>
        <h2><a href="/politica/2026/10/27/noticia-de-prueba-del-test">Una noticia de prueba del test</a></h2>
        <p>Entradilla de la noticia de prueba con la longitud suficiente.</p>
        <time datetime="2026-10-27T21:15:00+01:00"></time>
      </article>
    </body></html>
    """
    noticias = extraer_html(html, "https://example.com/", MEDIO, "Europe/Madrid", _ahora())
    assert len(noticias) == 1
    noticia = noticias[0]
    assert noticia.titular == "Una noticia de prueba del test"
    assert noticia.seccion == "Política"
    assert noticia.fecha == date(2026, 10, 27)
    assert noticia.fecha_publicacion == datetime(2026, 10, 27, 20, 15, tzinfo=timezone.utc)
    assert noticia.resumen == "Entradilla de la noticia de prueba con la longitud suficiente."


def test_extraer_html_desde_json_ld():
    html = """
    <html><head>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": "Titular desde JSON-LD de prueba",
        "url": "https://example.com/economia/2026-10-27/titular-json-ld",
        "datePublished": "2026-10-27T10:00:00+01:00",
        "description": "Descripción obtenida del marcado estructurado.",
        "articleSection": "Economía",
        "author": {"@type": "Person", "name": "Luis Gómez"}
      }
      </script>
    </head><body></body></html>
    """
    noticias = extraer_html(html, "https://example.com/", MEDIO, "Europe/Madrid", _ahora())
    assert len(noticias) == 1
    noticia = noticias[0]
    assert noticia.titular == "Titular desde JSON-LD de prueba"
    assert noticia.seccion == "Economía"
    assert noticia.autor == "Luis Gómez"
    assert noticia.origen == "html"


def test_extraer_html_deduplica_urls_con_tracking():
    html = """
    <html><body>
      <a href="/politica/2026/10/27/noticia-duplicada?utm_source=home">
        Una noticia duplicada en la portada
      </a>
      <a href="/politica/2026/10/27/noticia-duplicada">
        Una noticia duplicada en la portada
      </a>
    </body></html>
    """
    noticias = extraer_html(html, "https://example.com/", MEDIO, "Europe/Madrid", _ahora())
    assert len(noticias) == 1


def test_descubrir_feeds_prioriza_portada():
    html = """
    <html><head>
      <link rel="alternate" type="application/rss+xml" href="/rss/deportes.xml">
      <link rel="alternate" type="application/rss+xml" title="Portada" href="/rss/portada.xml">
    </head></html>
    """
    feeds = descubrir_feeds(html, "https://example.com/")
    assert feeds[0] == "https://example.com/rss/portada.xml"
    assert "https://example.com/rss/deportes.xml" in feeds


def test_fusionar_completa_campos():
    from antifasis.modelos import Noticia

    base = Noticia(
        medio_clave="ejemplo",
        titular="Una noticia de prueba con titular",
        url="https://example.com/politica/2026/10/27/noticia",
        fecha=date(2026, 10, 27),
        origen="html",
    )
    nueva = Noticia(
        medio_clave="ejemplo",
        titular="Una noticia de prueba con titular",
        url="https://example.com/politica/2026/10/27/noticia?utm_source=x",
        fecha=date(2026, 10, 27),
        resumen="Resumen que faltaba.",
        fecha_publicacion=datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc),
        origen="rss",
    )
    fusionadas = fusionar([base], [nueva])
    assert len(fusionadas) == 1
    assert fusionadas[0].resumen == "Resumen que faltaba."
    assert fusionadas[0].origen == "rss"
    assert fusionadas[0].fecha_publicacion is not None
