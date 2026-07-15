# Validia — CUFE Scraper v2

Validación automática de facturas electrónicas colombianas contra el portal DIAN.
Extrae datos completos incluyendo detalle de productos directamente del PDF oficial.

## Stack

- **FastAPI** — API + UI de demo
- **Playwright** — scraping del portal DIAN (bypasea Cloudflare Turnstile)
- **CapSolver** — resolución automática del captcha Turnstile
- **pdfplumber** — extracción estructurada del PDF de la factura
- **Railway** — hosting en producción

## Instalación local

```bash
# 1. Clonar el repositorio
git clone https://github.com/vktoriaTech/Web-Scraping.git
cd Web-Scraping

# 2. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# 3. Instalar dependencias
pip install fastapi uvicorn playwright pdfplumber pymupdf pandas openpyxl requests python-multipart beautifulsoup4 playwright-stealth

# 4. Instalar Chromium
playwright install chromium
```

## Correr en local

```bash
cd ~/Downloads/validia_demo   # o la carpeta donde tengas el proyecto
source venv/bin/activate
python3 main.py
```

Abrir en el navegador: **http://localhost:8000**

## API

```bash
POST /api/validar
Content-Type: application/json

{
  "cufe": "<96 caracteres>",
  "tenant_id": "VKTORIAGroup"
}
```

### Respuesta

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

Las siguientes constantes están en `scraper.py`:

| Variable | Descripción |
|---|---|
| `CAPSOLVER_KEY` | API key de CapSolver para resolver Turnstile |
| `SITE_KEY` | Cloudflare Turnstile site key del portal DIAN |
| `REPO_BASE` | Carpeta local donde se guardan los PDFs |

## Deploy en Railway

1. Conectar el repo `vktoriaTech/Web-Scraping` a Railway
2. Railway detecta el `Dockerfile` automáticamente
3. El servicio queda disponible en la URL generada por Railway
