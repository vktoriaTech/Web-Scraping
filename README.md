# Validia — CUFE Scraper v2

Validación automática de facturas electrónicas colombianas contra el portal DIAN.

## Stack
- **FastAPI** — API + UI de demo
- **Playwright** — scraping del portal DIAN
- **pdfplumber** — extracción de datos del PDF
- **Railway** — hosting

## Uso local

```bash
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload
```

Abrir: http://localhost:8000

## API

```bash
POST /api/validar
{
  "cufe": "<96 chars>",
  "tenant_id": "VKTORIAGroup"
}
```

## Deploy

Conectar este repo a Railway. El `nixpacks.toml` configura automáticamente Chromium.
