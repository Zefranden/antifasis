from datetime import date, datetime, timezone

import pytest

from antifasis.fechas import (
    fecha_desde_url,
    fecha_local,
    fecha_para_noticia,
    parsear_fecha,
    parsear_fecha_cli,
    validar_publicacion,
)


def test_parsear_iso_con_z():
    valor = parsear_fecha("2026-10-27T23:30:00Z")
    assert valor == datetime(2026, 10, 27, 23, 30, tzinfo=timezone.utc)


def test_parsear_rfc822():
    valor = parsear_fecha("Tue, 27 Oct 2026 20:00:00 +0100")
    assert valor == datetime(2026, 10, 27, 19, 0, tzinfo=timezone.utc)


def test_fecha_local_cambia_de_dia_en_madrid():
    valor = datetime(2026, 10, 27, 23, 30, tzinfo=timezone.utc)
    assert fecha_local(valor, "Europe/Madrid") == date(2026, 10, 28)


def test_validar_publicacion_rechaza_futuro_y_fechas_antiguas():
    ahora = datetime(2026, 10, 27, 22, 0, tzinfo=timezone.utc)
    assert validar_publicacion(datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc), ahora) is None
    assert validar_publicacion(datetime(1980, 1, 1, tzinfo=timezone.utc), ahora) is None
    assert validar_publicacion(datetime(2026, 10, 27, 21, 0, tzinfo=timezone.utc), ahora) is not None


@pytest.mark.parametrize(
    "url, esperada",
    [
        ("https://x.com/espana/2026-10-27/noticia_1", date(2026, 10, 27)),
        ("https://x.com/espana/2026/10/26/noticia", date(2026, 10, 26)),
        ("https://x.com/es/politica/20261025/noticia-123", date(2026, 10, 25)),
        ("https://x.com/politica/noticia", None),
        ("https://x.com/espana/2026-13-40/noticia", None),
    ],
)
def test_fecha_desde_url(url, esperada):
    assert fecha_desde_url(url) == esperada


def test_fecha_para_noticia_prioriza_publicacion():
    ahora = datetime(2026, 10, 27, 22, 0, tzinfo=timezone.utc)
    fecha, estimada = fecha_para_noticia(
        datetime(2026, 10, 26, 23, 30, tzinfo=timezone.utc),
        "https://x.com/2026-10-27/noticia",
        "Europe/Madrid",
        ahora,
    )
    assert fecha == date(2026, 10, 27)
    assert estimada is False


def test_fecha_para_noticia_usa_url_si_no_hay_publicacion():
    fecha, estimada = fecha_para_noticia(
        None, "https://x.com/2026-10-20/noticia", "Europe/Madrid"
    )
    assert fecha == date(2026, 10, 20)
    assert estimada is False


def test_fecha_para_noticia_cae_en_captura():
    ahora = datetime(2026, 10, 27, 22, 0, tzinfo=timezone.utc)
    fecha, estimada = fecha_para_noticia(None, "https://x.com/noticia", "Europe/Madrid", ahora)
    assert fecha == date(2026, 10, 27)
    assert estimada is True


def test_parsear_fecha_cli():
    assert parsear_fecha_cli("2026-10-27") == date(2026, 10, 27)
    assert parsear_fecha_cli(None) is None
    with pytest.raises(ValueError):
        parsear_fecha_cli("27/10/2026")
