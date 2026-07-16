# Validia — CUFE Scraper v2

Validación automática de facturas electrónicas colombianas contra el portal DIAN.
Extrae datos completos incluyendo detalle de productos directamente del PDF oficial.

## Stack

- **FastAPI** — API + UI de demo
- **Playwright** — scraping del portal DIAN (bypasea Cloudflare Turnstile)
- **CapSolver** — resolución automática del captcha Turnstile
- **pdfplumber** — extracción estructurada del PDF de la factura
- **Railway** — hosting en producción

## Variables de entorno

Copia `.env.example` a `.env` y completa los valores:

| Variable | Requerida | Descripción |
|---|---|---|
| `CUFE_API_KEY` | Sí | Clave que deben enviar los clientes de la API en el header `X-API-Key`. Sin esta variable, todas las rutas protegidas devuelven `401`. |
| `CAPSOLVER_API_KEY` | Sí | API key de CapSolver usada por el scraper para resolver los retos Turnstile de la DIAN. |
| `PORT` | No (default `8000`) | Puerto en el que escucha el servicio. |

```bash
cp .env.example .env
```

## Instalación local

```bash
# 1. Clonar el repositorio
git clone https://github.com/vktoriaTech/Web-Scraping.git
cd Web-Scraping

# 2. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# 3. Instalar dependencias (versiones fijadas en requirements.txt)
pip install -r requirements.txt

# 4. Instalar Chromium
playwright install chromium

# 5. Configurar variables de entorno
cp .env.example .env
# editar .env con tu CUFE_API_KEY y CAPSOLVER_API_KEY
```

## Correr en local

```bash
source venv/bin/activate
python3 main.py
```

Abrir en el navegador: **http://localhost:8000** (la UI de demo pide la API key en pantalla y la guarda en el navegador).

## Autenticación

Todas las rutas de la API, excepto `/health`, `/`, `/docs`, `/redoc` y `/openapi.json`, requieren el header `X-API-Key` con el valor configurado en `CUFE_API_KEY`.

```bash
curl -X POST http://localhost:8000/api/v1/cufe/validar \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CUFE_API_KEY" \
  -d '{"cufe": "<96 caracteres>", "tenant_id": "VKTORIAGroup"}'
```

Si el header falta o la key es incorrecta, la API responde `401`:

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "API key inválida o no proporcionada. Incluye el header X-API-Key."
  }
}
```

## API

### `POST /api/v1/cufe/validar`

```bash
POST /api/v1/cufe/validar
Content-Type: application/json
X-API-Key: <tu API key>

{
  "cufe": "<96 caracteres>",
  "tenant_id": "VKTORIAGroup"
}
```

> `POST /api/validar` se mantiene como alias de compatibilidad: redirige (`307`) a `/api/v1/cufe/validar` preservando método y body.

### Respuesta exitosa

```json
{
  "cufe": "...",
  "numero_factura": "FEPM-31277",
  "fecha_emision": "30-04-2026",
  "emisor_razon_social": "PALOMULATA SAS",
  "emisor_nit": "901464397",
  "receptor_razon_social": "VKTORIA GROUP SAS",
  "receptor_numero_documento": "902023607",
  "total_factura_cop": "404.259,00",
  "items": [
    {
      "nro": "1",
      "codigo": "03003",
      "descripcion": "SODA",
      "cantidad": "1,00",
      "precio_unitario": "$ 11.111,11",
      "precio_venta": "$ 11.111,11"
    }
  ],
  "pdf_path": "pdfs/VKTORIAGroup/2026-04/54a50fe30d4f859a_31277.pdf",
  "estado_dian": "Valida"
}
```

### Manejo de errores

Todas las respuestas de error siguen el mismo formato estructurado:

```json
{
  "error": {
    "code": "SCRAPE_TIMEOUT",
    "message": "El scraping excedió el timeout de 60 segundos"
  }
}
```

| Código HTTP | `code` | Cuándo ocurre |
|---|---|---|
| `400` | `INVALID_CUFE` | El CUFE no tiene exactamente 96 caracteres |
| `401` | `UNAUTHORIZED` | Falta el header `X-API-Key` o la key es incorrecta |
| `502` | `SCRAPE_FAILED` | El scraping falló tras agotar los reintentos |
| `504` | `SCRAPE_TIMEOUT` | El scraping excedió el timeout de 60 segundos en el último intento |
| `500` | `INTERNAL_ERROR` | Error inesperado no controlado |

El scraping tiene un timeout de **60 segundos por intento** y se reintenta automáticamente **1 vez** si el primer intento falla o expira.

## Flujo técnico

```
CUFE
  → Playwright navega al portal DIAN
  → CapSolver resuelve Turnstile #1 (búsqueda)
  → Token inyectado en DOM → submit formulario
  → Portal responde con resultado de la factura
  → CapSolver resuelve Turnstile #2 (descarga PDF)
  → Token inyectado → submit form#postForm
  → PDF descargado y guardado en pdfs/<tenant>/<año-mes>/
  → pdfplumber extrae: emisor, receptor, items, totales
  → JSON completo retornado al frontend
```

## Configuración

| Variable | Ubicación | Descripción |
|---|---|---|
| `CUFE_API_KEY` | entorno | Autenticación de la API (header `X-API-Key`) |
| `CAPSOLVER_API_KEY` | entorno | API key de CapSolver para resolver Turnstile |
| `SITE_KEY` | `scraper.py` | Cloudflare Turnstile site key del portal DIAN |
| `REPO_BASE` | `scraper.py` | Carpeta local donde se guardan los PDFs |

## Docker

El `Dockerfile` usa **Python 3.12** explícitamente e instala Chromium con sus dependencias del sistema.

```bash
# Build
docker build -t validia-cufe-scraper .

# Run (pasando las variables de entorno desde .env)
docker run --rm -p 8000:8000 --env-file .env validia-cufe-scraper
```

El contenedor expone el puerto `8000` (configurable con la variable `PORT`).

## Deploy en Railway

1. Conectar el repo `vktoriaTech/Web-Scraping` a Railway
2. Railway detecta el `Dockerfile` automáticamente
3. Configurar las variables de entorno `CUFE_API_KEY` y `CAPSOLVER_API_KEY` en el panel de Railway
4. El servicio queda disponible en la URL generada por Railway
