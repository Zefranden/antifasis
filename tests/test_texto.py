from antifasis.texto import (
    es_url_probable_articulo,
    hash_url,
    limpiar_html,
    limpiar_titular,
    normalizar_url,
    parece_titular,
    seccion_desde_url,
    truncar,
)


def test_normalizar_url_quita_tracking_y_ordena_query():
    url = (
        "https://www.Example.com/politica/una-noticia/?utm_source=tw&b=2&a=1"
        "&fbclid=abc#comentarios"
    )
    assert normalizar_url(url) == "https://www.example.com/politica/una-noticia?a=1&b=2"


def test_normalizar_url_resuelve_relativas():
    assert normalizar_url("/politica/noticia", "https://elpais.com/portada") == (
        "https://elpais.com/politica/noticia"
    )


def test_normalizar_url_rechaza_esquemas_peligrosos():
    assert normalizar_url("javascript:alert(1)") is None
    assert normalizar_url("mailto:alguien@example.com") is None
    assert normalizar_url("") is None


def test_hash_ignora_www_esquema_y_barra_final():
    assert hash_url("http://www.elpais.com/politica/noticia/") == hash_url(
        "https://elpais.com/politica/noticia"
    )


def test_limpiar_html_y_titular():
    assert limpiar_html("<p>Hola&nbsp;<b>mundo</b> &amp; cía</p>") == "Hola mundo & cía"
    assert limpiar_titular("  <strong>Titular</strong>\n  de prueba  ") == "Titular de prueba"


def test_truncar_por_palabra():
    assert truncar("uno dos tres cuatro", 12) == "uno dos…"
    assert truncar("corto", 20) == "corto"


def test_es_url_probable_articulo():
    assert es_url_probable_articulo(
        "https://www.elpais.com/internacional/2026-10-27/una-noticia-de-prueba.html"
    )
    assert es_url_probable_articulo(
        "https://www.lavozdegalicia.es/noticia/galicia/2026/10/27/noticia-de-prueba/0003.htm"
    )
    assert not es_url_probable_articulo("https://www.elpais.com/politica/")
    assert not es_url_probable_articulo("https://www.elpais.com/tags/politica/")
    assert not es_url_probable_articulo("https://www.elpais.com/rss/")


def test_seccion_desde_url():
    assert seccion_desde_url("https://x.com/politica/2026/10/27/noticia") == "Política"
    assert seccion_desde_url("https://x.com/ocio-y-cultura/20261027/noticia") == "Ocio y cultura"
    assert seccion_desde_url("https://x.com/noticia/somosmar/2026/10/27/x") == "Somos Mar"
    assert seccion_desde_url("https://x.com/") is None


def test_parece_titular():
    assert parece_titular("Una noticia con un titular suficientemente largo")
    assert not parece_titular("Portada")
    assert not parece_titular("Corto")
    assert not parece_titular("x" * 400)
