from datetime import datetime, timezone

from antifasis.api import create_app
from antifasis.config import Ajustes
from antifasis.medios import MEDIOS
from antifasis.modelos import ResultadoMedio
from antifasis.servicio import ResultadoActualizacion


class EjecutorFalso:
    def __init__(self):
        self.llamadas = []

    def __call__(self, ajustes, medios, **kwargs):
        self.llamadas.append({"ajustes": ajustes, "medios": medios, **kwargs})
        ahora = datetime.now(timezone.utc)
        return ResultadoActualizacion(
            medios=[
                ResultadoMedio(
                    medio=medios[0],
                    estado="ok",
                    metodo="rss",
                    http_status=200,
                    nuevas=2,
                    actualizadas=1,
                )
            ],
            nuevas=2,
            actualizadas=1,
            recibidas=2,
            estados={"ok": 1},
            fallos=[],
            iniciada_en=ahora,
            finalizada_en=ahora,
            duracion_ms=10,
            dry_run=bool(kwargs.get("dry_run")),
        )


def _crear_app(monkeypatch, token="secreto"):
    monkeypatch.setenv("ANTIFASIS_API_TOKEN", token)
    monkeypatch.delenv("ANTIFASIS_AUTO_INIT", raising=False)
    fake = EjecutorFalso()
    app = create_app(
        ajustes=Ajustes(database_url="postgresql://localhost/no_usada", limite=40, dias_max=7),
        ejecutor=fake,
    )
    app.config["TESTING"] = True
    return app, fake


def test_health_es_publico(monkeypatch):
    app, _ = _crear_app(monkeypatch)
    respuesta = app.test_client().get("/health")
    assert respuesta.status_code == 200
    assert respuesta.get_json()["status"] == "ok"


def test_actualizar_sin_token_configurado(monkeypatch):
    monkeypatch.delenv("ANTIFASIS_API_TOKEN", raising=False)
    monkeypatch.delenv("ANTIFASIS_AUTO_INIT", raising=False)
    app = create_app(
        ajustes=Ajustes(database_url="postgresql://localhost/no_usada"), ejecutor=EjecutorFalso()
    )
    respuesta = app.test_client().post("/actualizar", headers={"Authorization": "Bearer x"})
    assert respuesta.status_code == 503


def test_actualizar_rechaza_token_incorrecto(monkeypatch):
    app, fake = _crear_app(monkeypatch)
    respuesta = app.test_client().post(
        "/actualizar", headers={"Authorization": "Bearer incorrecto"}
    )
    assert respuesta.status_code == 401
    assert not fake.llamadas


def test_actualizar_ejecuta_con_token(monkeypatch):
    app, fake = _crear_app(monkeypatch)
    respuesta = app.test_client().post(
        "/actualizar", headers={"Authorization": "Bearer secreto"}
    )
    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    assert datos["ok"] is True
    assert datos["nuevas"] == 2
    assert datos["actualizadas"] == 1
    assert fake.llamadas[0]["medios"][0].clave == MEDIOS[0].clave


def test_actualizar_acepta_payload(monkeypatch):
    app, fake = _crear_app(monkeypatch)
    respuesta = app.test_client().post(
        "/actualizar",
        headers={"Authorization": "Bearer secreto", "Content-Type": "application/json"},
        json={"medios": ["elpais"], "limite": 5, "dias_max": 2, "dry_run": True},
    )
    assert respuesta.status_code == 200
    llamada = fake.llamadas[0]
    assert [m.clave for m in llamada["medios"]] == ["elpais"]
    assert llamada["limite"] == 5
    assert llamada["dias_max"] == 2
    assert llamada["dry_run"] is True


def test_actualizar_valida_limite(monkeypatch):
    app, fake = _crear_app(monkeypatch)
    respuesta = app.test_client().post(
        "/actualizar",
        headers={"Authorization": "Bearer secreto", "Content-Type": "application/json"},
        json={"limite": 999},
    )
    assert respuesta.status_code == 400
    assert not fake.llamadas


def test_actualizar_no_solapa_ejecuciones(monkeypatch):
    app, fake = _crear_app(monkeypatch)
    app.config["ANTIFASIS_LOCK"].acquire()
    try:
        respuesta = app.test_client().post(
            "/actualizar", headers={"Authorization": "Bearer secreto"}
        )
    finally:
        app.config["ANTIFASIS_LOCK"].release()
    assert respuesta.status_code == 409
    assert not fake.llamadas


def test_ruta_desconocida_devuelve_json(monkeypatch):
    app, _ = _crear_app(monkeypatch)
    respuesta = app.test_client().get("/no-existe")
    assert respuesta.status_code == 404
    assert respuesta.is_json
