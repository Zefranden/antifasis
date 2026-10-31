import pytest

from antifasis.medios import MEDIOS, ErrorMedio, seleccionar_medios


def test_catalogo_tiene_veinte_medios():
    assert len(MEDIOS) == 20
    assert len({m.clave for m in MEDIOS}) == 20


def test_reparto_nacional_y_regional():
    nacionales = [m for m in MEDIOS if m.ambito == "nacional"]
    regionales = [m for m in MEDIOS if m.ambito == "regional"]
    assert len(nacionales) == 12
    assert len(regionales) == 8


def test_todos_los_medios_rss_tienen_feed():
    for medio in MEDIOS:
        if medio.metodo in ("rss", "auto"):
            assert medio.feed_url, medio.clave
        assert medio.url_base.startswith("https://")


def test_seleccionar_medios_por_clave():
    seleccion = seleccionar_medios(["elpais", "elconfidencial"])
    assert [m.clave for m in seleccion] == ["elpais", "elconfidencial"]


def test_seleccionar_medios_admite_comas_y_repetidos():
    seleccion = seleccionar_medios(["elpais,abc", "elpais"])
    assert [m.clave for m in seleccion] == ["elpais", "abc"]


def test_medio_desconocido():
    with pytest.raises(ErrorMedio):
        seleccionar_medios(["no-existe"])
