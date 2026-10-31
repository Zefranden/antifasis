-- Esquema de Antifasis
-- PostgreSQL 12 o superior.
--
-- La columna `fecha` es la fecha de publicación en la zona horaria configurada
-- (Europe/Madrid por defecto). Es la clave de consulta y exportación por día.
-- `fecha_publicacion` conserva el instante exacto cuando la fuente lo ofrece.

CREATE TABLE IF NOT EXISTS medios (
    id              smallserial PRIMARY KEY,
    clave           text        NOT NULL UNIQUE,
    nombre          text        NOT NULL,
    ambito          text        NOT NULL CHECK (ambito IN ('nacional', 'regional')),
    comunidad       text,
    url_base        text        NOT NULL,
    feed_url        text,
    metodo          text        NOT NULL DEFAULT 'rss' CHECK (metodo IN ('rss', 'auto', 'html')),
    idioma          text        NOT NULL DEFAULT 'es',
    activo          boolean     NOT NULL DEFAULT true,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    actualizado_en  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE medios IS 'Catálogo de medios configurados.';
COMMENT ON COLUMN medios.clave IS 'Identificador estable usado por la CLI (--medio).';
COMMENT ON COLUMN medios.metodo IS 'rss: solo RSS; auto: RSS + HTML si el feed es escaso; html: portada HTML.';

CREATE TABLE IF NOT EXISTS noticias (
    id                  bigserial   PRIMARY KEY,
    medio_id            smallint    NOT NULL REFERENCES medios (id) ON DELETE CASCADE,
    fecha               date        NOT NULL,
    fecha_publicacion   timestamptz,
    fecha_estimada      boolean     NOT NULL DEFAULT true,
    titular             text        NOT NULL CHECK (length(btrim(titular)) > 0),
    resumen             text,
    url                 text        NOT NULL,
    url_hash            char(64)    NOT NULL,
    seccion             text,
    autor               text,
    guid                text,
    imagen_url          text,
    idioma              text        NOT NULL DEFAULT 'es',
    origen              text        NOT NULL DEFAULT 'rss' CHECK (origen IN ('rss', 'html', 'descubierto')),
    fecha_captura       timestamptz NOT NULL DEFAULT now(),
    actualizado_en      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT noticias_medio_url_uk UNIQUE (medio_id, url_hash)
);

COMMENT ON TABLE noticias IS 'Titulares, resúmenes y metadatos; nunca el texto completo de la noticia.';
COMMENT ON COLUMN noticias.fecha IS 'Fecha de publicación en la zona horaria configurada (por defecto Europe/Madrid).';
COMMENT ON COLUMN noticias.fecha_publicacion IS 'Instante exacto de publicación en UTC, si la fuente lo proporciona.';
COMMENT ON COLUMN noticias.fecha_estimada IS 'true si la fecha se tomó de la captura porque la fuente no la aportaba.';
COMMENT ON COLUMN noticias.url_hash IS 'SHA-256 de la URL canónica; evita duplicados entre ejecuciones.';
COMMENT ON COLUMN noticias.origen IS 'Procedencia del registro: feed RSS, portada HTML o feed descubierto en la portada.';

CREATE INDEX IF NOT EXISTS noticias_fecha_idx
    ON noticias (fecha DESC, medio_id);

CREATE INDEX IF NOT EXISTS noticias_medio_fecha_idx
    ON noticias (medio_id, fecha DESC);

CREATE INDEX IF NOT EXISTS noticias_publicacion_idx
    ON noticias (fecha_publicacion DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS noticias_busqueda_idx
    ON noticias USING gin (to_tsvector('spanish', titular || ' ' || coalesce(resumen, '')));

CREATE TABLE IF NOT EXISTS capturas (
    id                      bigserial   PRIMARY KEY,
    medio_id                smallint    NOT NULL REFERENCES medios (id) ON DELETE CASCADE,
    iniciada_en             timestamptz NOT NULL DEFAULT now(),
    finalizada_en           timestamptz,
    estado                  text        NOT NULL DEFAULT 'en_curso'
                                        CHECK (estado IN ('en_curso', 'ok', 'parcial', 'error')),
    metodo                  text,
    http_status             integer,
    noticias_recibidas      integer     NOT NULL DEFAULT 0,
    noticias_nuevas         integer     NOT NULL DEFAULT 0,
    noticias_actualizadas   integer     NOT NULL DEFAULT 0,
    error                   text,
    duracion_ms             integer
);

COMMENT ON TABLE capturas IS 'Auditoría de cada intento de extracción por medio.';

CREATE INDEX IF NOT EXISTS capturas_medio_fecha_idx
    ON capturas (medio_id, iniciada_en DESC);

CREATE OR REPLACE VIEW v_resumen_diario AS
SELECT
    n.fecha,
    m.clave,
    m.nombre,
    m.ambito,
    m.comunidad,
    count(*)::integer AS noticias
FROM noticias n
JOIN medios m ON m.id = n.medio_id
GROUP BY n.fecha, m.clave, m.nombre, m.ambito, m.comunidad;

CREATE OR REPLACE VIEW v_ultimas_noticias AS
SELECT
    n.fecha,
    n.fecha_publicacion,
    m.nombre AS medio,
    m.ambito,
    n.seccion,
    n.titular,
    n.resumen,
    n.url
FROM noticias n
JOIN medios m ON m.id = n.medio_id
ORDER BY n.fecha_publicacion DESC NULLS LAST, n.id DESC;
