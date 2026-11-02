# Antifasis

Agregador en Python que extrae **titulares, entradillas y metadatos** de los 20 principales medios españoles en internet —12 nacionales y 8 regionales— y los guarda en **PostgreSQL indexados por fecha de publicación**.

El programa no descarga el texto completo de las noticias: guarda el titular, el resumen que publica el medio, la URL, la sección, el autor y la fecha. Así se respeta mejor el trabajo editorial y los términos de uso de cada medio.

## Qué incluye

- **20 medios**: El País, El Mundo, ABC, La Vanguardia, elDiario.es, El Confidencial, El Periódico, La Razón, El Español, 20 minutos, Expansión, infoLibre, La Voz de Galicia, El Correo, Heraldo de Aragón, Diario Sur, Levante-EMV, La Nueva España, Canarias7 y Última Hora.
- **RSS como fuente principal** y **respaldo HTML** para los medios que ya no publican feed (El Periódico y La Voz de Galicia) o cuando el feed devuelve muy pocas piezas (El Confidencial).
- **Descubrimiento automático del feed** en la portada si la URL configurada deja de funcionar.
- **Deduplicación por URL canónica** y `UPSERT` idempotente: ejecutar dos veces no duplica noticias.
- **Fecha civil en Europe/Madrid** (`fecha`), instante exacto en UTC (`fecha_publicacion`) y marca de fecha estimada.
- **CLI**: inicializar la base, actualizar, resumir por día, exportar a CSV/JSONL y borrar datos antiguos.
- **API Flask** protegida por token para lanzar la captura desde Render o cualquier cron mediante `POST /actualizar`.
- **robots.txt**, reintentos con espera exponencial, límite de tamaño y user-agent identificable.
- **Pruebas unitarias** y una prueba de integración opcional contra PostgreSQL.

## Requisitos

- Python **3.9 o superior**.
- PostgreSQL **12 o superior** (16 recomendado). También puedes levantar la base con Docker.
- Conexión a internet.

## Puesta en marcha rápida

```bash
# 1. Base de datos (opción Docker)
docker compose up -d db

# 2. Entorno de Python
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. Configuración
cp .env.example .env

# 4. Esquema y catálogo de medios
python -m antifasis init-db

# 5. Primera captura
python -m antifasis actualizar

# 6. Consulta del día
python -m antifasis resumen --fecha "$(date +%F)"
```

La configuración por defecto usa `postgresql://antifasis:antifasis@localhost:5432/antifasis`, que coincide con el `docker-compose.yml`.

Si ya tienes PostgreSQL instalado y no usas Docker:

```bash
createdb antifasis
export DATABASE_URL="postgresql://tu_usuario:tu_clave@localhost:5432/antifasis"
python -m antifasis init-db
```

## Medios configurados

| Medio | Clave | Ámbito | Fuente |
|---|---|---|---|
| El País | `elpais` | Nacional | RSS |
| El Mundo | `elmundo` | Nacional | RSS |
| ABC | `abc` | Nacional | RSS |
| La Vanguardia | `lavanguardia` | Nacional (Cataluña) | RSS |
| elDiario.es | `eldiario` | Nacional | RSS |
| El Confidencial | `elconfidencial` | Nacional | RSS + HTML |
| El Periódico | `elperiodico` | Nacional (Cataluña) | HTML |
| La Razón | `larazon` | Nacional | RSS |
| El Español | `elespanol` | Nacional | RSS |
| 20 minutos | `20minutos` | Nacional | RSS |
| Expansión | `expansion` | Nacional | RSS |
| infoLibre | `infolibre` | Nacional | RSS |
| La Voz de Galicia | `lavozdegalicia` | Regional (Galicia) | HTML |
| El Correo | `elcorreo` | Regional (País Vasco) | RSS |
| Heraldo de Aragón | `heraldo` | Regional (Aragón) | RSS |
| Diario Sur | `diariosur` | Regional (Andalucía) | RSS |
| Levante-EMV | `levante` | Regional (C. Valenciana) | RSS |
| La Nueva España | `lne` | Regional (Asturias) | RSS |
| Canarias7 | `canarias7` | Regional (Canarias) | RSS |
| Última Hora | `ultimahora` | Regional (Illes Balears) | RSS |

Puedes ver el catálogo completo, con las URLs exactas, con:

```bash
python -m antifasis listar-medios
```

## Comandos

```text
python -m antifasis init-db
python -m antifasis listar-medios
python -m antifasis actualizar [opciones]
python -m antifasis resumen [--fecha AAAA-MM-DD | --desde ... --hasta ...] [--json]
python -m antifasis exportar [--fecha ... | --desde ... --hasta ...] [--medio CLAVE]
python -m antifasis mantener [--dias 365] [--simular] [--si]
```

### `actualizar`

```bash
# Todos los medios
python -m antifasis actualizar

# Solo algunos
python -m antifasis actualizar --medio elpais --medio elconfidencial

# Probar sin escribir en la base
python -m antifasis actualizar --dry-run --limite 10

# Guardar hasta 200 piezas por medio y aceptar noticias de los últimos 90 días
python -m antifasis actualizar --limite 200 --dias-max 90
```

Opciones:

| Opción | Efecto |
|---|---|
| `--medio CLAVE` | Repetible o separado por comas. |
| `--limite N` | Máximo de noticias por medio; `0` = sin límite. Por defecto 100. |
| `--dias-max N` | Descarta piezas con más de N días; `0` = sin límite. Por defecto 30. |
| `--dry-run` | Extrae y muestra, pero no escribe en PostgreSQL. |
| `--sin-robots` | No consulta `robots.txt` (no recomendado). |

### `resumen`

```bash
python -m antifasis resumen --fecha 2026-10-27
python -m antifasis resumen --desde 2026-10-01 --hasta 2026-10-31
python -m antifasis resumen --fecha 2026-10-27 --json
```

### `exportar`

```bash
# CSV del día a un fichero (UTF-8 con BOM, cómodo para Excel)
python -m antifasis exportar --fecha 2026-10-27 --formato csv --salida noticias.csv

# JSON Lines de un mes por stdout
python -m antifasis exportar --desde 2026-10-01 --hasta 2026-10-31 --formato jsonl

# Solo un medio
python -m antifasis exportar --fecha 2026-10-27 --medio elpais
```

Columnas del CSV: `fecha`, `hora_publicacion`, `medio`, `ambito`, `comunidad`, `seccion`, `titular`, `resumen`, `url`, `autor`, `fecha_estimada`, `origen`.

### `mantener`

```bash
# Ver cuánto se borraría
python -m antifasis mantener --dias 365 --simular

# Borrar sin preguntar (útil en cron)
python -m antifasis mantener --dias 365 --capturas-dias 90 --si
```

## API HTTP

La misma lógica de extracción se puede ejecutar desde una API Flask. La API está pensada para recibir una llamada de cron y ejecutar la captura de forma síncrona.

| Método | Ruta | Autenticación | Descripción |
|---|---|---|---|
| `GET` | `/` | No | Información básica y rutas disponibles. |
| `GET` | `/health` | No | Estado del servicio; pensado para el health check de Render. |
| `GET` | `/health/db` | No | Comprueba conexión y esquema de PostgreSQL. |
| `POST` | `/actualizar` | Bearer token | Ejecuta la captura y devuelve el resumen. |
| `GET` | `/resumen` | Bearer token | Resumen por fecha o rango. |

El token se configura en `ANTIFASIS_API_TOKEN`. Si no está definido, los endpoints protegidos responden `503`; si el token no coincide, responden `401`. No hay ningún endpoint de escritura sin autenticar.

### Ejecutar en local

```bash
export ANTIFASIS_API_TOKEN="dev-token"
python -m antifasis.api
```

En otra terminal:

```bash
curl -X POST http://127.0.0.1:8000/actualizar \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{}'
```

También se puede limitar la ejecución:

```bash
curl -X POST http://127.0.0.1:8000/actualizar \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"medios": ["elpais", "elconfidencial"], "limite": 20, "dias_max": 7}'
```

Cuerpo admitido:

| Campo | Tipo | Efecto |
|---|---|---|
| `medios` | lista de claves | Limita la captura a esos medios. |
| `limite` | entero 0-500 | Máximo de noticias por medio. |
| `dias_max` | entero 0-3650 | Antigüedad máxima en días. |
| `dry_run` | booleano | Extrae sin escribir en PostgreSQL. |

La respuesta incluye `nuevas`, `actualizadas`, `recibidas`, `estados`, `fallos` y el detalle por medio. Si ya hay una ejecución en curso, `POST /actualizar` devuelve `409`.

### Cron

El repositorio incluye [`scripts/render_cron.sh`](scripts/render_cron.sh), que llama a `POST /actualizar` con el token y falla si la API devuelve un error:

```bash
export ANTIFASIS_API_HOST="antifasis-api.onrender.com"
export ANTIFASIS_API_TOKEN="tu-token"
bash scripts/render_cron.sh
```

Para un cron externo (cron-job.org, GitHub Actions, crontab, etc.) basta con hacer un `POST` a la URL pública con la cabecera `Authorization: Bearer ...`.

## Variables de entorno

Se leen del entorno y, si existe, de un fichero `.env` en el directorio actual o en la raíz del proyecto.

| Variable | Por defecto | Descripción |
|---|---|---|
| `DATABASE_URL` | `postgresql://antifasis:antifasis@localhost:5432/antifasis` | Cadena de conexión. |
| `ANTIFASIS_ZONA` | `Europe/Madrid` | Zona para calcular `fecha`. |
| `ANTIFASIS_TIMEOUT` | `20` | Timeout de lectura en segundos. |
| `ANTIFASIS_REINTENTOS` | `2` | Reintentos por petición. |
| `ANTIFASIS_WORKERS` | `6` | Medios descargados en paralelo. |
| `ANTIFASIS_LIMITE` | `100` | Máximo de noticias por medio (`0` = sin límite). |
| `ANTIFASIS_DIAS_MAX` | `30` | Antigüedad máxima en días (`0` = sin límite). |
| `ANTIFASIS_RESPETAR_ROBOTS` | `true` | Comprobar `robots.txt`. |
| `ANTIFASIS_USER_AGENT` | navegador + `Antifasis/1.0` | User-agent de las peticiones. |
| `ANTIFASIS_API_TOKEN` | vacío | Token de `POST /actualizar` y `GET /resumen`. |
| `ANTIFASIS_AUTO_INIT` | `false` | Aplica el esquema y registra los medios al arrancar la API. |

También puedes pasar la conexión por CLI, después del subcomando:

```bash
python -m antifasis actualizar --base-datos "postgresql://usuario:clave@host:5432/antifasis"
```

## Modelo de datos

El esquema está en [`antifasis/sql/esquema.sql`](antifasis/sql/esquema.sql). Tablas principales:

### `medios`

Catálogo con `clave` estable, nombre, ámbito (`nacional`/`regional`), comunidad, URL base, feed y método de extracción.

### `noticias`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `bigserial` | PK. |
| `medio_id` | `smallint` | FK a `medios`. |
| `fecha` | `date` | **Fecha de publicación en Europe/Madrid**. Es la clave de consulta diaria. |
| `fecha_publicacion` | `timestamptz` | Instante exacto en UTC, si el medio lo publica. |
| `fecha_estimada` | `boolean` | `true` si se usó la fecha de captura porque la fuente no daba fecha. |
| `titular` | `text` | Titular limpio. |
| `resumen` | `text` | Entradilla recortada a 600 caracteres. |
| `url` | `text` | URL limpia (sin `utm_*` ni fragmentos). |
| `url_hash` | `char(64)` | SHA-256 de la URL canónica. |
| `seccion`, `autor`, `guid`, `imagen_url` | | Metadatos opcionales. |
| `origen` | `text` | `rss`, `html` o `descubierto`. |
| `fecha_captura`, `actualizado_en` | `timestamptz` | Auditoría. |

Restricción `UNIQUE (medio_id, url_hash)`: la misma URL no se duplica en el mismo medio. El `UPSERT` actualiza titular, resumen y metadatos si el medio corrige la pieza.

### `capturas`

Registra cada intento por medio: estado (`ok`, `parcial`, `error`), método, HTTP, noticias recibidas/nuevas/actualizadas, error y duración.

### Vistas

- `v_resumen_diario`: noticias por fecha y medio.
- `v_ultimas_noticias`: últimas piezas con el nombre del medio.

### Consultas de ejemplo

```sql
-- Noticias de hoy
SELECT m.nombre, n.seccion, n.titular, n.url
FROM noticias n
JOIN medios m ON m.id = n.medio_id
WHERE n.fecha = (now() AT TIME ZONE 'Europe/Madrid')::date
ORDER BY m.nombre, n.fecha_publicacion DESC NULLS LAST;

-- Resumen del día por medio
SELECT * FROM v_resumen_diario
WHERE fecha = (now() AT TIME ZONE 'Europe/Madrid')::date
ORDER BY noticias DESC;

-- Serie diaria del último mes
SELECT fecha, count(*) AS noticias
FROM noticias
WHERE fecha >= (now() AT TIME ZONE 'Europe/Madrid')::date - INTERVAL '30 days'
GROUP BY fecha
ORDER BY fecha;

-- Búsqueda full-text en español
SELECT fecha, titular, url
FROM noticias
WHERE to_tsvector('spanish', titular || ' ' || coalesce(resumen, ''))
      @@ plainto_tsquery('spanish', 'vivienda');

-- Estado de la última captura de cada medio
SELECT DISTINCT ON (m.clave)
       m.nombre, c.iniciada_en, c.estado, c.noticias_recibidas, c.error
FROM medios m
LEFT JOIN capturas c ON c.medio_id = m.id
ORDER BY m.clave, c.iniciada_en DESC NULLS LAST;
```

## Despliegue en Render + Supabase

### 1. Base de datos en Supabase

1. Crea un proyecto en Supabase y copia la cadena de conexión de **Project Settings → Database**.
2. Si Render no tiene salida IPv6, usa la cadena del **Session pooler** o **Transaction pooler** (suele ser el host `*.pooler.supabase.com`).
3. Define esa cadena como `DATABASE_URL` en Render. La aplicación añade `sslmode=require` automáticamente si detecta un host de Supabase y desactiva las sentencias preparadas para que funcione también con PgBouncer.
4. La primera vez hay que crear las tablas. El `render.yaml` activa `ANTIFASIS_AUTO_INIT=true`, así que el propio arranque aplica [`antifasis/sql/esquema.sql`](antifasis/sql/esquema.sql) y registra los 20 medios. Si prefieres hacerlo a mano, ejecuta `python -m antifasis init-db` desde la Shell de Render.

### 2. Repositorio

El proyecto se publica en:

- GitHub: <https://github.com/Zefranden/antifasis.git>
- Forgejo local: `http://192.168.1.44:3000/administrador/antifasis.git`

Render despliega desde GitHub, así que el repositorio de GitHub es el que debe estar conectado al Blueprint.

### 3. Blueprint de Render

El fichero [`render.yaml`](render.yaml) define dos recursos:

- **`antifasis-api`**: servicio web Python con Gunicorn, health check en `/health` y arranque con `ANTIFASIS_AUTO_INIT=true`.
- **`antifasis-cron`**: Cron Job que ejecuta `bash scripts/render_cron.sh` a las `06:00` y `18:00` UTC. Cambia `schedule` si quieres otra frecuencia.

Al aplicar el Blueprint, Render pedirá el valor de `DATABASE_URL`. El token de API se genera automáticamente y el cron lo hereda del servicio web mediante `fromService`; también hereda el host público. Si cambias el nombre del servicio web, actualiza las referencias `fromService` del cron.

Si tu plan no incluye Cron Jobs, crea un cron externo que haga:

```bash
curl -fsS -X POST "https://TU-SERVICIO.onrender.com/actualizar" \
  -H "Authorization: Bearer TU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Los servicios gratuitos de Render se suspenden por inactividad: la primera llamada del cron puede tardar unos segundos en despertar el servicio. El `--max-time 240` del script deja margen suficiente.

### 4. Comprobaciones tras desplegar

```bash
curl https://TU-SERVICIO.onrender.com/health
curl https://TU-SERVICIO.onrender.com/health/db
```

La primera debe devolver `status: ok`; la segunda comprueba que el esquema está aplicado. Si `/health/db` falla, revisa `DATABASE_URL`, la contraseña y que hayas usado la cadena del pooler correcta.

## Programación automática

El repositorio incluye [`scripts/cron_diario.sh`](scripts/cron_diario.sh), que ejecuta una captura y escribe el resultado en `logs/antifasis.log`.

```bash
chmod +x scripts/cron_diario.sh
```

Ejemplo de `crontab -e` para capturar a las 07:00 y a las 19:00:

```cron
0 7,19 * * * /ruta/a/antifasis/scripts/cron_diario.sh
```

El script hace `cd` a la raíz del proyecto, así que `.env` y `.venv` se resuelven correctamente. Si tienes un `PATH` de Python distinto, define `PYTHON_BIN`:

```bash
PYTHON_BIN=/usr/bin/python3 scripts/cron_diario.sh
```

## Pruebas

```bash
# Unitarias (sin red ni base de datos)
pytest

# Integración: crea el esquema en una base de pruebas y valida el UPSERT
TEST_DATABASE_URL="postgresql://antifasis:antifasis@localhost:5432/antifasis_test" pytest -m integracion
```

La prueba de integración crea y borra sus propios datos, pero conviene usar una base dedicada (`antifasis_test`). No ejecutes `init-db` contra producción desde las pruebas.

## Estructura del proyecto

```text
antifasis/
  cli.py           # comandos y presentación
  config.py        # entorno, .env y validación
  db.py            # conexión, esquema, UPSERT y consultas
  extractores.py   # RSS, JSON-LD, <article>, enlaces y descubrimiento
  fechas.py        # UTC ↔ Europe/Madrid, fechas de URL
  http.py          # reintentos, robots.txt, decodificación
  medios.py        # catálogo de los 20 medios
  modelos.py       # Noticia y ResultadoMedio
  servicio.py      # extracción + persistencia compartida por CLI y API
  api.py           # API Flask
  texto.py         # limpieza, URLs canónicas, secciones
  sql/esquema.sql
wsgi.py            # entrada WSGI para Gunicorn/Render
render.yaml        # web + cron job de Render
tests/
scripts/cron_diario.sh
scripts/render_cron.sh
docker-compose.yml
```

### Cómo se decide la fecha

1. Si el RSS trae `pubDate`, se usa ese instante y se convierte a `Europe/Madrid` para `fecha`.
2. Si no hay instante pero la URL contiene la fecha (`/2026-10-27/`, `/2026/10/27/`, `/20261027/`), se usa esa fecha.
3. Si no hay ninguna de las dos, se usa la fecha de captura y `fecha_estimada = true`.

Los registros con más de `ANTIFASIS_DIAS_MAX` días se descartan antes de aplicar el límite, para que las piezas de agenda o el contenido antiguo que arrastran algunos feeds no ocupen el cupo.

## Añadir o cambiar medios

Edita [`antifasis/medios.py`](antifasis/medios.py) y añade un `Medio`:

```python
Medio(
    clave="mi-medio",
    nombre="Mi Medio",
    ambito="regional",           # nacional | regional
    comunidad="Mi Comunidad",
    url_base="https://www.mimedio.es/",
    feed_url="https://www.mimedio.es/rss/",  # None si solo hay HTML
    metodo="rss",                # rss | auto | html
)
```

Después ejecuta `python -m antifasis init-db` para sincronizar el catálogo. No hace falta migrar la base: `medios` se actualiza por `clave`.

- `rss`: usa el feed; si falla, intenta descubrir otro en la portada.
- `auto`: como `rss`, pero si el feed devuelve menos de `minimo_antes_de_html` piezas, completa con la portada HTML.
- `html`: extrae de la portada con JSON-LD, `<article>` y enlaces.

## Limitaciones y notas

- **Solo titulares y resúmenes**, no el cuerpo completo. Los medios con muro de pago pueden no incluir resumen en el RSS; en ese caso queda `NULL`.
- **Los feeds no son un archivo**: suelen exponer entre 20 y 200 piezas recientes. Para histórico completo haría falta suscripción, API o archivo propio.
- **Historias en directo**: pueden reaparecer con la misma URL y distinto titular; el `UPSERT` conserva una sola fila y actualiza el titular.
- **Duplicados entre medios**: la misma noticia de agencia puede aparecer en varios medios. Se deduplica por medio, no entre medios, porque cada uno la publica con su propio enfoque.
- **Cambios de diseño**: si un medio cambia su portada o su feed, el respaldo HTML y el descubrimiento automático suelen mantener la captura, pero conviene revisar `capturas.error` y los avisos de la CLI.
- **robots.txt**: se respeta por defecto. Si un medio lo prohíbe, la captura de ese medio quedará como error; no lo eludas sin revisar sus condiciones.
- **Uso responsable**: identifícate con un `ANTIFASIS_USER_AGENT` con contacto real si despliegas esto de forma pública, no bajes el timeout ni aumentes los workers sin necesidad y revisa los términos de uso de cada medio. Este proyecto es un agregador de enlaces y metadatos, no un sustituto de visitar las webs.

## Solución de problemas

**`No se puede conectar a PostgreSQL`**  
Comprueba que el contenedor está arriba (`docker compose ps`) y que `DATABASE_URL` coincide con usuario, contraseña, host y base.

**`Falta el esquema de la base de datos`**  
Ejecuta `python -m antifasis init-db` con la misma `DATABASE_URL`.

**Un medio devuelve `error` o `parcial`**  
Mira el detalle en la salida y en `SELECT * FROM capturas ORDER BY id DESC LIMIT 20;`. Puede ser un cambio de feed, un 403 temporal o una caída del medio. El resto de medios no se ve afectado.

**`psycopg_binary` falla en macOS**  
Instala libpq (`brew install libpq`) y usa `pip install "psycopg[c]"`, o ejecuta con el Python del sistema. En Linux y Windows los wheels de `psycopg[binary]` funcionan sin problemas.

**Las fechas no coinciden con las de la web**  
Revisa `ANTIFASIS_ZONA`. `fecha` es la fecha civil en esa zona; `fecha_publicacion` se guarda en UTC y se muestra convertida al exportar.

## Licencia

MIT. Consulta [`LICENSE`](LICENSE).
