import os
from datetime import date, datetime, timezone

import pytest

from antifasis.db import BaseDatos, ErrorBaseDatos, leer_esquema
from antifasis.medios import Medio
from antifasis.modelos import Noticia

DSN = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.integracion

MEDIO = Medio(
    clave="pruebas_integracion",
    nombre="Medio de Pruebas",
    ambito="nacional",
    comunidad="España",
    url_base="https://example.com/",
    feed_url="https://example.com/rss",
)


@pytest.fixture(scope="module")
def base():
    if not DSN:
        pytest.skip("Define TEST_DATABASE_URL para ejecutar las pruebas de integración.")
    db = BaseDatos(DSN)
    db.ejecutar_script(leer_esquema())
    ids = db.sincronizar_medios([MEDIO])
    yield db, ids[MEDIO.clave]
    db.conn.execute("DELETE FROM noticias WHERE medio_id = %s", (ids[MEDIO.clave],))
    db.conn.execute("DELETE FROM capturas WHERE medio_id = %s", (ids[MEDIO.clave],))
    db.conn.execute("DELETE FROM medios WHERE clave = %s", (MEDIO.clave,))
    db.cerrar()


def test_flujo_completo_de_persistencia(base):
    db, medio_id = base
    fecha = date(1999, 1, 1)
    noticia = Noticia(
        medio_clave=MEDIO.clave,
        titular="Titular de prueba de integración",
        url="https://example.com/politica/1999/01/01/prueba-integracion",
        fecha=fecha,
        fecha_publicacion=datetime(1999, 1, 1, 12, 0, tzinfo=timezone.utc),
        fecha_estimada=False,
        resumen="Resumen de prueba de integración.",
        seccion="Política",
        autor="Autora de Pruebas",
        origen="rss",
    )

    nuevas, actualizadas = db.guardar_noticias(medio_id, [noticia, noticia])
    assert (nuevas, actualizadas) == (1, 0)

    noticia.titular = "Titular actualizado de integración"
    noticia.resumen = None
    nuevas, actualizadas = db.guardar_noticias(medio_id, [noticia])
    assert (nuevas, actualizadas) == (0, 1)

    assert db.total_noticias(fecha, fecha) == 1
    filas = db.exportar(fecha, fecha, MEDIO.clave)
    assert len(filas) == 1
    assert filas[0]["titular"] == "Titular actualizado de integración"
    assert filas[0]["resumen"] == "Resumen de prueba de integración."

    resumen = db.resumen_por_fecha(fecha, fecha)
    assert resumen[0]["noticias"] == 1

    captura = db.iniciar_captura(medio_id, datetime.now(tz=timezone.utc))
    assert captura > 0
    from antifasis.modelos import ResultadoMedio

    resultado = ResultadoMedio(
        medio=MEDIO,
        noticias=[noticia],
        estado="ok",
        metodo="rss",
        http_status=200,
        duracion_ms=123,
    )
    db.finalizar_captura(captura, resultado, nuevas=0, actualizadas=1)
    ultima = db.ultima_captura_por_medio()
    assert any(f["clave"] == MEDIO.clave and f["estado"] == "ok" for f in ultima)


def test_esquema_inexistente_da_error_claro():
    if not DSN:
        pytest.skip("Define TEST_DATABASE_URL para ejecutar las pruebas de integración.")
    db = BaseDatos(DSN)
    db.conn.execute("CREATE SCHEMA IF NOT EXISTS pruebas_vacias")
    db.conn.execute("SET search_path TO pruebas_vacias")
    try:
        with pytest.raises(ErrorBaseDatos):
            db.verificar_esquema()
    finally:
        db.conn.execute("SET search_path TO public")
        db.conn.execute("DROP SCHEMA pruebas_vacias CASCADE")
        db.cerrar()
