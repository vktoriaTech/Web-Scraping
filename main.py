"""
Validia — Demo App
API + UI para demostración a socios
"""

import concurrent.futures
import logging
import os
import secrets
from dataclasses import asdict

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from scraper import ScraperDIAN

load_dotenv()

log = logging.getLogger("validia.api")

app = FastAPI(title="Validia CUFE Scraper", version="2.0")

SCRAPE_TIMEOUT_SECONDS = 60
SCRAPE_MAX_ATTEMPTS = 2  # intento inicial + 1 reintento

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="scraper")


# ── Auth ────────────────────────────────────────────────────────────────────────
API_KEY_HEADER = "X-API-Key"
CUFE_API_KEY = os.environ.get("CUFE_API_KEY", "")

# Rutas que no requieren autenticación: health check, UI de demo y docs de la API.
PUBLIC_PATHS = {"/health", "/", "/docs", "/redoc", "/openapi.json"}

if not CUFE_API_KEY:
    log.warning("CUFE_API_KEY no está configurada — todas las rutas protegidas devolverán 401")


@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    if request.url.path not in PUBLIC_PATHS:
        provided = request.headers.get(API_KEY_HEADER, "")
        if not CUFE_API_KEY or not secrets.compare_digest(provided, CUFE_API_KEY):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": f"API key inválida o no proporcionada. Incluye el header {API_KEY_HEADER}.",
                    }
                },
            )
    return await call_next(request)


# ── Errores estructurados ───────────────────────────────────────────────────────
class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Error no manejado")
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "Error interno del servidor"}},
    )


# ── Schema ──────────────────────────────────────────────────────────────────────
class CUFERequest(BaseModel):
    cufe: str
    tenant_id: str = "VKTORIAGroup"


# ── Scraping con timeout + retry ─────────────────────────────────────────────────
def _ejecutar_scraper(cufe: str, tenant_id: str):
    with ScraperDIAN(headless=True, tenant_id=tenant_id) as scraper:
        return scraper.procesar(cufe)


def _procesar_con_reintento(cufe: str, tenant_id: str):
    ultimo_error = "Error desconocido durante el scraping"
    ultimo_fue_timeout = False

    for intento in range(1, SCRAPE_MAX_ATTEMPTS + 1):
        future = _executor.submit(_ejecutar_scraper, cufe, tenant_id)
        try:
            factura = future.result(timeout=SCRAPE_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            ultimo_error = f"El scraping excedió el timeout de {SCRAPE_TIMEOUT_SECONDS} segundos"
            ultimo_fue_timeout = True
            log.warning(f"[Intento {intento}/{SCRAPE_MAX_ATTEMPTS}] {ultimo_error}")
            continue
        except Exception as e:
            ultimo_error = str(e)
            ultimo_fue_timeout = False
            log.warning(f"[Intento {intento}/{SCRAPE_MAX_ATTEMPTS}] Error inesperado: {ultimo_error}")
            continue

        if factura.estado_dian == "Error":
            ultimo_error = factura.detalle_error or ultimo_error
            ultimo_fue_timeout = False
            log.warning(f"[Intento {intento}/{SCRAPE_MAX_ATTEMPTS}] {ultimo_error}")
            continue

        return factura

    if ultimo_fue_timeout:
        raise APIError(504, "SCRAPE_TIMEOUT", ultimo_error)
    raise APIError(502, "SCRAPE_FAILED", ultimo_error)


# ── Endpoints ───────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "Validia CUFE Scraper v2"}


@app.post("/api/v1/cufe/validar")
def validar_cufe(req: CUFERequest):
    cufe = req.cufe.strip()
    if len(cufe) != 96:
        raise APIError(400, "INVALID_CUFE", f"CUFE debe tener 96 caracteres, recibido: {len(cufe)}")
    factura = _procesar_con_reintento(cufe, req.tenant_id)
    return JSONResponse(content=asdict(factura))


@app.post("/api/validar", include_in_schema=False)
def validar_cufe_legacy():
    """Alias de compatibilidad — redirige a /api/v1/cufe/validar."""
    return RedirectResponse(url="/api/v1/cufe/validar", status_code=307)


# ── UI de demo ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def ui_demo():
    return HTMLResponse(content=HTML_DEMO)


HTML_DEMO = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Validia — Validador CUFE DIAN</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');

  :root {
    --magenta: #FF0080;
    --black: #000000;
    --white: #FFFFFF;
    --gray-50: #F9FAFB;
    --gray-100: #F3F4F6;
    --gray-200: #E5E7EB;
    --gray-600: #4B5563;
    --gray-800: #1F2937;
    --green: #10B981;
    --red: #EF4444;
    --yellow: #F59E0B;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Poppins', sans-serif;
    background: var(--gray-50);
    color: var(--gray-800);
    min-height: 100vh;
  }

  /* ── Header ── */
  header {
    background: var(--black);
    padding: 16px 32px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .logo-dot {
    width: 10px; height: 10px;
    background: var(--magenta);
    border-radius: 50%;
  }
  header h1 {
    color: var(--white);
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.3px;
  }
  header span {
    color: var(--magenta);
  }
  .badge {
    margin-left: auto;
    background: var(--magenta);
    color: white;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
    letter-spacing: 0.5px;
  }

  /* ── Main ── */
  main {
    max-width: 860px;
    margin: 0 auto;
    padding: 40px 24px;
  }

  .hero {
    text-align: center;
    margin-bottom: 40px;
  }
  .hero h2 {
    font-size: 28px;
    font-weight: 700;
    color: var(--black);
    margin-bottom: 8px;
  }
  .hero p {
    color: var(--gray-600);
    font-size: 15px;
  }

  /* ── Card ── */
  .card {
    background: white;
    border-radius: 16px;
    padding: 32px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 4px 16px rgba(0,0,0,0.04);
    margin-bottom: 24px;
  }

  .card h3 {
    font-size: 15px;
    font-weight: 600;
    color: var(--black);
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .card h3::before {
    content: '';
    display: block;
    width: 4px; height: 18px;
    background: var(--magenta);
    border-radius: 2px;
  }

  /* ── Form ── */
  label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--gray-600);
    margin-bottom: 6px;
  }

  input[type="text"] {
    width: 100%;
    padding: 12px 16px;
    border: 1.5px solid var(--gray-200);
    border-radius: 10px;
    font-family: 'Poppins', monospace;
    font-size: 13px;
    color: var(--gray-800);
    transition: border-color 0.2s;
    outline: none;
    margin-bottom: 16px;
  }
  input[type="text"]:focus {
    border-color: var(--magenta);
  }

  .cufe-len {
    text-align: right;
    font-size: 12px;
    color: var(--gray-600);
    margin-top: -12px;
    margin-bottom: 20px;
  }
  .cufe-len.ok { color: var(--green); }
  .cufe-len.error { color: var(--red); }

  .row { display: flex; gap: 16px; }
  .row > div { flex: 1; }

  button {
    width: 100%;
    padding: 14px;
    background: var(--magenta);
    color: white;
    border: none;
    border-radius: 10px;
    font-family: 'Poppins', sans-serif;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.1s;
    margin-top: 4px;
  }
  button:hover { opacity: 0.9; }
  button:active { transform: scale(0.99); }
  button:disabled { opacity: 0.5; cursor: not-allowed; }

  /* ── Estado ── */
  #estado {
    display: none;
    align-items: center;
    gap: 10px;
    padding: 14px 18px;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 500;
    margin-bottom: 24px;
  }
  #estado.loading { display: flex; background: #EFF6FF; color: #1D4ED8; }
  #estado.success { display: flex; background: #ECFDF5; color: #065F46; }
  #estado.error   { display: flex; background: #FEF2F2; color: #991B1B; }

  .spinner {
    width: 18px; height: 18px;
    border: 2.5px solid #BFDBFE;
    border-top-color: #1D4ED8;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Resultado ── */
  #resultado { display: none; }

  .section-title {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--magenta);
    margin-bottom: 16px;
  }

  .grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px 24px;
    margin-bottom: 24px;
  }
  @media (max-width: 600px) { .grid-2 { grid-template-columns: 1fr; } }

  .field label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--gray-600);
    margin-bottom: 3px;
  }
  .field .val {
    font-size: 14px;
    font-weight: 500;
    color: var(--gray-800);
  }
  .field .val.cufe-val {
    font-size: 11px;
    font-family: monospace;
    word-break: break-all;
  }

  /* Estado badge */
  .estado-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
  }
  .estado-badge.valida  { background: #ECFDF5; color: #065F46; }
  .estado-badge.error   { background: #FEF2F2; color: #991B1B; }

  /* Totales */
  .totales-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid var(--gray-100);
    font-size: 14px;
  }
  .totales-row:last-child { border-bottom: none; }
  .totales-row .lbl { color: var(--gray-600); }
  .totales-row .amt { font-weight: 600; color: var(--gray-800); }
  .totales-row.total-final .lbl,
  .totales-row.total-final .amt {
    font-size: 16px;
    font-weight: 700;
    color: var(--black);
  }

  /* Tabla items */
  .items-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .items-table th {
    text-align: left;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--gray-600);
    padding: 8px 12px;
    background: var(--gray-50);
    border-bottom: 1px solid var(--gray-200);
  }
  .items-table td {
    padding: 12px;
    border-bottom: 1px solid var(--gray-100);
    color: var(--gray-800);
    vertical-align: top;
  }
  .items-table tr:last-child td { border-bottom: none; }
  .items-table .desc { font-weight: 500; }
  .items-table .price { font-weight: 600; text-align: right; }

  /* Divider */
  .divider {
    height: 1px;
    background: var(--gray-100);
    margin: 20px 0;
  }

  /* Footer */
  footer {
    text-align: center;
    padding: 24px;
    font-size: 12px;
    color: var(--gray-600);
  }
  footer strong { color: var(--magenta); }
</style>
</head>
<body>

<header>
  <div class="logo-dot"></div>
  <h1>VALIDIA <span>·</span> DIAN</h1>
  <span class="badge">DEMO v2</span>
</header>

<main>
  <div class="hero">
    <h2>Validación automática de CUFEs</h2>
    <p>Ingresa un código CUFE para consultar, descargar y extraer la factura electrónica directamente desde la DIAN.</p>
  </div>

  <!-- Formulario -->
  <div class="card">
    <h3>Consultar CUFE</h3>

    <label>Código CUFE (96 caracteres)</label>
    <input type="text" id="cufe" placeholder="Pega aquí el código CUFE de la factura..."
           oninput="checkLen()" />
    <div class="cufe-len" id="cufeLen">0 / 96 caracteres</div>

    <div class="row">
      <div>
        <label>Tenant / Organización</label>
        <input type="text" id="tenant" value="VKTORIAGroup" />
      </div>
      <div>
        <label>API Key</label>
        <input type="text" id="apiKey" placeholder="X-API-Key" />
      </div>
    </div>

    <button id="btnValidar" onclick="validar()" disabled>
      Validar y extraer factura
    </button>
  </div>

  <!-- Estado -->
  <div id="estado">
    <div class="spinner" id="spinner"></div>
    <span id="estadoMsg"></span>
  </div>

  <!-- Resultado -->
  <div id="resultado">

    <!-- Encabezado -->
    <div class="card">
      <h3>Información del documento</h3>
      <div class="grid-2">
        <div class="field">
          <label>Estado DIAN</label>
          <div class="val" id="r-estado"></div>
        </div>
        <div class="field">
          <label>Número de Factura</label>
          <div class="val" id="r-numero"></div>
        </div>
        <div class="field">
          <label>Fecha de Emisión</label>
          <div class="val" id="r-fecha"></div>
        </div>
        <div class="field">
          <label>Forma de Pago</label>
          <div class="val" id="r-pago"></div>
        </div>
        <div class="field" style="grid-column: 1/-1">
          <label>CUFE</label>
          <div class="val cufe-val" id="r-cufe"></div>
        </div>
      </div>
    </div>

    <!-- Partes -->
    <div class="card">
      <h3>Partes de la factura</h3>
      <div class="section-title">Emisor / Vendedor</div>
      <div class="grid-2">
        <div class="field">
          <label>Razón Social</label>
          <div class="val" id="r-emisor-nombre"></div>
        </div>
        <div class="field">
          <label>NIT</label>
          <div class="val" id="r-emisor-nit"></div>
        </div>
        <div class="field">
          <label>Dirección</label>
          <div class="val" id="r-emisor-dir"></div>
        </div>
        <div class="field">
          <label>Correo</label>
          <div class="val" id="r-emisor-correo"></div>
        </div>
      </div>

      <div class="divider"></div>

      <div class="section-title">Receptor / Comprador</div>
      <div class="grid-2">
        <div class="field">
          <label>Razón Social</label>
          <div class="val" id="r-receptor-nombre"></div>
        </div>
        <div class="field">
          <label>NIT / Documento</label>
          <div class="val" id="r-receptor-nit"></div>
        </div>
        <div class="field">
          <label>Dirección</label>
          <div class="val" id="r-receptor-dir"></div>
        </div>
        <div class="field">
          <label>Correo</label>
          <div class="val" id="r-receptor-correo"></div>
        </div>
      </div>
    </div>

    <!-- Items -->
    <div class="card" id="card-items" style="display:none">
      <h3>Detalle de Productos / Servicios</h3>
      <table class="items-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Código</th>
            <th>Descripción</th>
            <th>U/M</th>
            <th>Cant.</th>
            <th>Precio Unitario</th>
            <th>Descuento</th>
            <th>IVA</th>
            <th>INC %</th>
            <th style="text-align:right">Total</th>
          </tr>
        </thead>
        <tbody id="r-items"></tbody>
      </table>
    </div>

    <!-- Totales -->
    <div class="card">
      <h3>Totales</h3>
      <div class="totales-row">
        <span class="lbl">Subtotal</span>
        <span class="amt" id="r-subtotal">—</span>
      </div>
      <div class="totales-row">
        <span class="lbl">Descuento</span>
        <span class="amt" id="r-descuento">—</span>
      </div>
      <div class="totales-row">
        <span class="lbl">Total Bruto</span>
        <span class="amt" id="r-total-bruto">—</span>
      </div>
      <div class="totales-row">
        <span class="lbl">IVA</span>
        <span class="amt" id="r-iva">—</span>
      </div>
      <div class="totales-row">
        <span class="lbl">INC</span>
        <span class="amt" id="r-inc">—</span>
      </div>
      <div class="totales-row">
        <span class="lbl">Total Impuestos</span>
        <span class="amt" id="r-total-impuesto">—</span>
      </div>
      <div class="totales-row">
        <span class="lbl">Total Neto</span>
        <span class="amt" id="r-total-neto">—</span>
      </div>
      <div class="totales-row total-final">
        <span class="lbl">TOTAL FACTURA (COP)</span>
        <span class="amt" id="r-total">—</span>
      </div>
    </div>

    <!-- Autorización -->
    <div class="card">
      <h3>Autorización DIAN</h3>
      <div class="grid-2">
        <div class="field">
          <label>Número de Autorización</label>
          <div class="val" id="r-auth-num"></div>
        </div>
        <div class="field">
          <label>Vigencia</label>
          <div class="val" id="r-auth-vig"></div>
        </div>
        <div class="field">
          <label>Rango desde</label>
          <div class="val" id="r-auth-desde"></div>
        </div>
        <div class="field">
          <label>Rango hasta</label>
          <div class="val" id="r-auth-hasta"></div>
        </div>
      </div>
    </div>

  </div><!-- /resultado -->
</main>

<footer>
  Powered by <strong>VKTORIA Tech Consulting</strong> · Validia CUFE Scraper v2
</footer>

<script>
const CUFE_DEMO = "7d0a7f415b5f452d056991730d8387aa5dbface4397a69b53a26e8330e505ecd40b85fb309d2b71c2c24b859b9e1acb2";

document.getElementById("apiKey").value = localStorage.getItem("validia_api_key") || "";

// Auto-fill demo CUFE



function checkLen() {
  const v = document.getElementById("cufe").value.trim();
  const el = document.getElementById("cufeLen");
  const btn = document.getElementById("btnValidar");
  el.textContent = v.length + " / 96 caracteres";
  el.className = "cufe-len " + (v.length === 96 ? "ok" : v.length > 0 ? "error" : "");
  btn.disabled = v.length !== 96;
}

function setEstado(tipo, msg) {
  const el = document.getElementById("estado");
  el.className = tipo;
  document.getElementById("estadoMsg").textContent = msg;
  document.getElementById("spinner").style.display = tipo === "loading" ? "block" : "none";
}

function fill(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val || "—";
}

async function validar() {
  const cufe   = document.getElementById("cufe").value.trim();
  const tenant = document.getElementById("tenant").value.trim() || "default";
  const apiKey = document.getElementById("apiKey").value.trim();
  localStorage.setItem("validia_api_key", apiKey);

  document.getElementById("resultado").style.display = "none";
  document.getElementById("btnValidar").disabled = true;
  setEstado("loading", "Consultando portal DIAN y descargando factura... puede tomar ~20 segundos");

  try {
    const resp = await fetch("/api/v1/cufe/validar", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-API-Key": apiKey},
      body: JSON.stringify({ cufe, tenant_id: tenant })
    });

    const data = await resp.json();

    if (!resp.ok) {
      setEstado("error", "Error: " + (data.error?.message || data.detail || "No se pudo procesar"));
      document.getElementById("btnValidar").disabled = false;
      return;
    }

    setEstado("success", "✓ Factura validada y extraída correctamente");
    renderResultado(data);

  } catch(e) {
    setEstado("error", "Error de conexión: " + e.message);
  }

  document.getElementById("btnValidar").disabled = false;
}

function renderResultado(d) {
  // Encabezado
  const estadoEl = document.getElementById("r-estado");
  if (d.estado_dian === "Valida") {
    estadoEl.innerHTML = '<span class="estado-badge valida">✓ Válida en DIAN</span>';
  } else {
    estadoEl.innerHTML = '<span class="estado-badge error">✗ ' + d.estado_dian + '</span>';
  }

  fill("r-cufe",    d.cufe);
  fill("r-numero",  d.numero_factura);
  fill("r-fecha",   d.fecha_emision);
  fill("r-pago",    (d.forma_pago || "") + (d.medio_pago ? " — " + d.medio_pago : ""));

  // Emisor
  fill("r-emisor-nombre",  d.emisor_razon_social);
  fill("r-emisor-nit",     d.emisor_nit);
  fill("r-emisor-dir",     d.emisor_direccion);
  fill("r-emisor-correo",  d.emisor_correo);

  // Receptor
  fill("r-receptor-nombre",  d.receptor_razon_social);
  fill("r-receptor-nit",     d.receptor_numero_documento);
  fill("r-receptor-dir",     d.receptor_direccion);
  fill("r-receptor-correo",  d.receptor_correo);

  // Items
  const items = d.items || [];
  if (items.length > 0) {
    document.getElementById("card-items").style.display = "block";
    const tbody = document.getElementById("r-items");
    tbody.innerHTML = items.map(it => `
      <tr>
        <td>${it.nro || "1"}</td>
        <td>${it.codigo || ""}</td>
        <td class="desc">${it.descripcion || ""}</td>
        <td>${it.unidad_medida || ""}</td>
        <td>${it.cantidad || ""}</td>
        <td>${it.precio_unitario || ""}</td>
        <td class="price">${it.precio_venta || ""}</td>
      </tr>
    `).join("");
  }

  // Totales
  fill("r-subtotal",       d.subtotal || "—");
  fill("r-descuento",      d.descuento_detalle || "0,00");
  fill("r-total-bruto",    d.total_bruto || "—");
  fill("r-iva",            d.iva || "0,00");
  fill("r-inc",            d.inc || "0,00");
  fill("r-total-impuesto", d.total_impuesto || "—");
  fill("r-total-neto",     d.total_neto || "—");
  fill("r-total",          d.total_factura_cop || d.total_neto);

  // Autorización
  fill("r-auth-num",   d.autorizacion_numero);
  fill("r-auth-vig",   d.autorizacion_vigencia);
  fill("r-auth-desde", d.autorizacion_rango_desde);
  fill("r-auth-hasta", d.autorizacion_rango_hasta);

  document.getElementById("resultado").style.display = "block";
  document.getElementById("resultado").scrollIntoView({ behavior: "smooth" });
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn, os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
