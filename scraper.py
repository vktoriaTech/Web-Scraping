"""
Validia — Scraper DIAN v2 DEFINITIVO
Flujo: CUFE → Playwright + CapSolver (Turnstile x2) → PDF → extracción completa
"""

import time, random, json, re, logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("validia")

URL_DIAN       = "https://catalogo-vpfe.dian.gov.co/User/SearchDocument"
DELAY_MIN      = 2.0
DELAY_MAX      = 5.0
MAX_REINTENTOS = 3
REPO_BASE      = Path("pdfs")


@dataclass
class ItemFactura:
    nro: str = ""
    codigo: str = ""
    descripcion: str = ""
    unidad_medida: str = ""
    cantidad: str = ""
    precio_unitario: str = ""
    descuento: str = ""
    recargo: str = ""
    iva_valor: str = ""
    iva_pct: str = ""
    precio_venta: str = ""


@dataclass
class FacturaCompleta:
    cufe: str = ""
    numero_factura: str = ""
    forma_pago: str = ""
    medio_pago: str = ""
    fecha_emision: str = ""
    tipo_operacion: str = ""
    emisor_razon_social: str = ""
    emisor_nombre_comercial: str = ""
    emisor_nit: str = ""
    emisor_tipo_contribuyente: str = ""
    emisor_regimen_fiscal: str = ""
    emisor_departamento: str = ""
    emisor_municipio: str = ""
    emisor_direccion: str = ""
    emisor_telefono: str = ""
    emisor_correo: str = ""
    receptor_razon_social: str = ""
    receptor_tipo_documento: str = ""
    receptor_numero_documento: str = ""
    receptor_tipo_contribuyente: str = ""
    receptor_departamento: str = ""
    receptor_municipio: str = ""
    receptor_direccion: str = ""
    receptor_telefono: str = ""
    receptor_correo: str = ""
    subtotal: str = ""
    descuento_detalle: str = ""
    total_bruto: str = ""
    iva: str = ""
    inc: str = ""
    total_impuesto: str = ""
    total_neto: str = ""
    total_factura_cop: str = ""
    propina: str = ""
    items: list = field(default_factory=list)
    autorizacion_numero: str = ""
    autorizacion_rango_desde: str = ""
    autorizacion_rango_hasta: str = ""
    autorizacion_vigencia: str = ""
    fecha_generacion_doc: str = ""
    fecha_validacion_dian: str = ""
    tenant_id: str = ""
    pdf_path: str = ""
    estado_dian: str = ""
    detalle_error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class RepoPDF:
    def __init__(self, base: Path = REPO_BASE):
        self.base = base

    def guardar(self, bytes_: bytes, cufe: str, tenant: str, folio: str = "", fecha: str = "") -> Path:
        if fecha and "-" in fecha:
            partes = fecha.split("-")
            mes = f"{partes[2]}-{partes[1]}" if len(partes) == 3 else datetime.now().strftime("%Y-%m")
        else:
            mes = datetime.now().strftime("%Y-%m")
        nombre = f"{cufe[:16]}_{folio}.pdf" if folio else f"{cufe[:16]}.pdf"
        carpeta = self.base / (tenant or "default") / mes
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / nombre
        ruta.write_bytes(bytes_)
        log.info(f"PDF guardado → {ruta}  ({len(bytes_):,} bytes)")
        return ruta


class ExtractorPDF:
    def extraer(self, pdf_path: Path) -> dict:
        try:
            import pdfplumber
            return self._con_pdfplumber(pdf_path)
        except Exception as e:
            log.error(f"Extracción fallida: {e}")
            return {}

    def _con_pdfplumber(self, pdf_path: Path) -> dict:
        import pdfplumber
        paginas, items = [], []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, pagina in enumerate(pdf.pages):
                texto = pagina.extract_text(layout=True) or ""
                paginas.append(texto)
                # Buscar tabla de items en TODAS las páginas hasta encontrarla
                if not items:
                    for tabla in pagina.extract_tables():
                        extraidos = self._parsear_tabla_items(tabla)
                        if extraidos:
                            items = extraidos
                            break
        datos = self._parsear_campos(
            paginas[0] if paginas else "",
            paginas[1] if len(paginas) > 1 else ""
        )
        datos["items"] = items
        return datos

    def _parsear_campos(self, p1: str, p2: str) -> dict:
        def b(patron, fuente=p1):
            try:
                m = re.search(patron, fuente, re.IGNORECASE | re.MULTILINE)
                return m.group(1).strip() if m and m.lastindex else ""
            except:
                return ""

        return {
            "numero_factura":          b(r"N[uú]mero de Factura:\s*(\S+)"),
            "forma_pago":              b(r"Forma de pago:\s*(\w+)"),
            "medio_pago":              b(r"Medio de Pago:\s*(\w+)"),
            "fecha_emision":           b(r"Fecha de Emisi[oó]n:\s*([\d/]+)"),
            "tipo_operacion":          b(r"Tipo de Operaci[oó]n:\s*(\d+ - \w+)"),
            "emisor_razon_social":     b(r"Raz[oó]n Social:\s*([A-ZÁÉÍÓÚÑ ]+)"),
            "emisor_nombre_comercial": b(r"Nombre Comercial:\s*([A-ZÁÉÍÓÚÑ ]+)"),
            "emisor_nit":              b(r"Nit del Emisor:\s*(\d+)"),
            "emisor_tipo_contribuyente": b(r"Tipo de Contribuyente:\s*(Persona\s+(?:Natural|Jur[ií]dica))"),
            "emisor_regimen_fiscal":   b(r"R[eé]gimen Fiscal:\s*(\S+)"),
            "emisor_departamento":     b(r"Departamento:\s*([\w ]+?)\s{2,}"),
            "emisor_municipio":        b(r"Municipio / Ciudad:\s*([\w]+)"),
            "emisor_direccion":        b(r"Direcci[oó]n:\s*(CL[\w\s]+?)\s{2,}"),
            "emisor_telefono":         b(r"Tel[eé]fono / M[oó]vil:\s*(\d+)"),
            "emisor_correo":           b(r"Correo:\s*([\w.\-@]+\.\w{2,})"),
            "receptor_razon_social":   b(r"Nombre o Raz[oó]n Social:\s*([A-ZÁÉÍÓÚÑ ]+)"),
            "receptor_tipo_documento": b(r"Tipo de Documento:\s*(\w+)"),
            "receptor_numero_documento": b(r"N[uú]mero Documento:\s*(\d+)"),
            "receptor_tipo_contribuyente": b(r"Tipo de Contribuyente:\s*(Persona\s+Jur[ií]dica)"),
            "receptor_departamento":   b(r"Departamento:\s*(VALLE[\w ]+?)\s{2,}"),
            "receptor_municipio":      b(r"Municipio / Ciudad:\s*([\w]+)"),
            "receptor_direccion":      b(r"Direcci[oó]n:\s*(AV[\w\s]+?)\s{2,}"),
            "receptor_telefono":       b(r"Tel[eé]fono / M[oó]vil:\s*(\d{10})"),
            "receptor_correo":         b(r"Correo:\s*([\w.\-@]+\.co\b)"),
            "subtotal":                b(r"Subtotal\s+([\d.,]+)", p2),
            "descuento_detalle":       b(r"Descuento detalle\s+([\d.,]+)", p2) or "0,00",
            "total_bruto":             b(r"Total Bruto Factura\s+([\d.,]+)", p2),
            "iva":                     b(r"\bIVA\s+([\d.,]+)", p2),
            "inc":                     b(r"\bINC\s+([\d.,]+)", p2),
            "total_impuesto":          b(r"Total impuesto \(=\)\s+([\d.,]+)", p2),
            "total_neto":              b(r"Total neto factura \(=\)\s+([\d.,]+)", p2),
            "total_factura_cop":       b(r"Total factura \(=\) COP \$\s*([\d.,]+)", p2),
            "autorizacion_numero":     b(r"N[uú]mero de Autorizaci[oó]n:\s*(\d+)Rango", p2),
            "autorizacion_rango_desde": b(r"Rango desde:\s*(\d+)Rango", p2),
            "autorizacion_rango_hasta": b(r"Rango hasta:\s*(\d+)Vigencia", p2),
            "autorizacion_vigencia":   b(r"Vigencia:\s*([\d\-]+)", p2),
            "fecha_generacion_doc":    b(r"Documento generado el:\s*([\d/: ]+)", p2),
            "fecha_validacion_dian":   b(r"DIAN:\s*([\d/: ]+)", p2),
        }

    def _parsear_tabla_items(self, tabla: list) -> list:
        if not tabla or len(tabla) < 2:
            return []
        items = []
        for fila in tabla:
            if not fila or not fila[0]:
                continue
            if not str(fila[0]).strip().isdigit():
                continue
            def c(i, default=""):
                val = fila[i] if i < len(fila) else None
                return str(val).strip().replace('\n', ' ') if val else default
            items.append(asdict(ItemFactura(
                nro=c(0), codigo=c(1), descripcion=c(2),
                unidad_medida=c(3), cantidad=c(4),
                precio_unitario=c(5), descuento=c(6), recargo=c(7),
                iva_valor=c(8), iva_pct=c(9),
                precio_venta=c(12) if len(fila) > 12 else c(len(fila)-1),
            )))
        return items


class ScraperDIAN:
    CAPSOLVER_KEY = "CAP-1025A79691AA2EFF2456B25CD6E1D71438DB5D6525ED70700C92CD7DBA7838FF"
    SITE_KEY      = "0x4AAAAAAAg1WuNb-OnOa76z"

    def __init__(self, headless: bool = True, tenant_id: str = "default"):
        self.headless  = headless
        self.tenant_id = tenant_id
        self.repo      = RepoPDF()
        self.extractor = ExtractorPDF()
        self._pw = self._browser = self._ctx = self._page = None

    def launch(self):
        from playwright.sync_api import sync_playwright
        log.info("Iniciando Chromium...")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        self._ctx = self._browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
        )
        self._page = self._ctx.new_page()
        log.info("Navegador listo")

    def close(self):
        for obj in [self._ctx, self._browser]:
            try:
                if obj: obj.close()
            except: pass
        try:
            if self._pw: self._pw.stop()
        except: pass

    def __enter__(self):
        self.launch(); return self

    def __exit__(self, *_):
        self.close()

    def _resolver_turnstile(self) -> Optional[str]:
        import requests as req
        try:
            r = req.post("https://api.capsolver.com/createTask", json={
                "clientKey": self.CAPSOLVER_KEY,
                "task": {"type": "AntiTurnstileTaskProxyLess", "websiteURL": URL_DIAN, "websiteKey": self.SITE_KEY}
            }, timeout=30).json()
            if r.get("errorId"):
                log.error(f"CapSolver error: {r}")
                return None
            task_id = r["taskId"]
            for _ in range(20):
                time.sleep(3)
                res = req.post("https://api.capsolver.com/getTaskResult", json={
                    "clientKey": self.CAPSOLVER_KEY, "taskId": task_id
                }, timeout=30).json()
                if res.get("status") == "ready":
                    return res["solution"]["token"]
        except Exception as e:
            log.error(f"Error Turnstile: {e}")
        return None

    def procesar(self, cufe: str, intento: int = 1) -> FacturaCompleta:
        cufe = cufe.strip()
        log.info(f"[{intento}/{MAX_REINTENTOS}] CUFE: {cufe[:16]}...")
        factura = FacturaCompleta(cufe=cufe, tenant_id=self.tenant_id)

        try:
            # Paso 1: Navegar y resolver Turnstile de búsqueda
            self._page.goto(URL_DIAN, timeout=60_000, wait_until="domcontentloaded")
            time.sleep(2)
            log.info("Resolviendo Turnstile búsqueda...")
            token1 = self._resolver_turnstile()
            if not token1:
                raise Exception("No se pudo resolver Turnstile de búsqueda")
            self._page.evaluate(f"document.querySelectorAll('input[name=\"cf-turnstile-response\"]').forEach(i => i.value = '{token1}');")
            self._page.wait_for_selector("input#DocumentKey", timeout=10_000).fill(cufe)
            time.sleep(0.5)
            self._page.click("button:has-text('Buscar')")
            time.sleep(8)

            # Paso 2: Extraer metadatos del HTML
            self._extraer_pagina_html(factura)
            if factura.estado_dian == "No encontrada":
                return factura

            # Paso 3: Resolver Turnstile de descarga e inyectar en form
            log.info("Resolviendo Turnstile descarga...")
            token2 = self._resolver_turnstile()
            if not token2:
                raise Exception("No se pudo resolver Turnstile de descarga")
            self._page.evaluate(f"""
                const form = document.querySelector('form#postForm');
                const cap = form?.querySelector('input[name="captcha"]');
                if (cap) cap.value = '{token2}';
            """)

            # Paso 4: Submit del form de descarga y capturar PDF
            log.info("Descargando PDF...")
            with self._page.expect_download(timeout=30_000) as dl:
                self._page.evaluate("document.querySelector('form#postForm').submit()")
            download = dl.value
            pdf_bytes = Path(download.path()).read_bytes()
            log.info(f"PDF descargado: {len(pdf_bytes):,} bytes")

            # Paso 5: Guardar en repositorio
            folio = factura.numero_factura.replace("FE-", "").replace("FEPM-", "")
            ruta = self.repo.guardar(pdf_bytes, cufe, self.tenant_id, folio, factura.fecha_emision)
            factura.pdf_path = str(ruta)

            # Paso 6: Extraer datos del PDF
            log.info("Extrayendo datos del PDF...")
            datos = self.extractor.extraer(ruta)
            self._aplicar_datos_pdf(factura, datos)
            log.info(f"Items extraídos: {len(factura.items)}")

        except Exception as e:
            log.error(f"Error: {e}")
            if intento < MAX_REINTENTOS:
                time.sleep(5 * intento)
                return self.procesar(cufe, intento + 1)
            factura.estado_dian   = "Error"
            factura.detalle_error = str(e)

        return factura

    def _extraer_pagina_html(self, factura: FacturaCompleta):
        texto = self._page.inner_text("body")

        def entre(ini, fin, src=texto):
            try:
                i = src.index(ini) + len(ini)
                j = src.index(fin, i)
                return src[i:j].strip()
            except ValueError:
                return ""

        if "Factura electrónica" in texto or "Factura Electrónica" in texto:
            factura.estado_dian = "Valida"
        else:
            factura.estado_dian = "No encontrada"
            return

        serie = entre("Serie: ", "\n")
        folio = entre("Folio: ", "\n")
        factura.numero_factura = f"{serie}-{folio}" if serie else f"FE-{folio}"
        factura.fecha_emision  = entre("Fecha de emisión de la factura Electrónica: ", "\n")

        bloque_e = entre("DATOS DEL EMISOR", "DATOS DEL RECEPTOR")
        factura.emisor_nit          = entre("NIT: ", "\n", bloque_e)
        factura.emisor_razon_social = entre("Nombre: ", "\n", bloque_e)

        bloque_r = entre("DATOS DEL RECEPTOR", "TOTALES E IMPUESTOS")
        factura.receptor_numero_documento = entre("NIT: ", "\n", bloque_r)
        factura.receptor_razon_social     = entre("Nombre: ", "\n", bloque_r)

        factura.iva               = entre("IVA: ", "\n")
        factura.total_factura_cop = entre("Total: ", "\n")

        log.info(f"HTML OK: {factura.numero_factura} | {factura.emisor_razon_social} → {factura.receptor_razon_social} | Total: {factura.total_factura_cop}")

    def _aplicar_datos_pdf(self, factura: FacturaCompleta, datos: dict):
        campos = [
            "numero_factura","forma_pago","medio_pago","fecha_emision","tipo_operacion",
            "emisor_razon_social","emisor_nombre_comercial","emisor_nit","emisor_tipo_contribuyente",
            "emisor_regimen_fiscal","emisor_departamento","emisor_municipio","emisor_direccion",
            "emisor_telefono","emisor_correo","receptor_razon_social","receptor_tipo_documento",
            "receptor_numero_documento","receptor_tipo_contribuyente","receptor_departamento",
            "receptor_municipio","receptor_direccion","receptor_telefono","receptor_correo",
            "subtotal","descuento_detalle","total_bruto","iva","inc","total_impuesto",
            "total_neto","total_factura_cop","autorizacion_numero","autorizacion_rango_desde",
            "autorizacion_rango_hasta","autorizacion_vigencia","fecha_generacion_doc","fecha_validacion_dian",
        ]
        for campo in campos:
            val = datos.get(campo, "")
            if val and not getattr(factura, campo, ""):
                setattr(factura, campo, val)
        if datos.get("items"):
            factura.items = datos["items"]


class ProcesadorLote:
    def __init__(self, scraper: ScraperDIAN):
        self.scraper    = scraper
        self.resultados = []

    def procesar(self, cufes: list, salida: str = "facturas_validia") -> list:
        total = len(cufes)
        for i, cufe in enumerate(cufes, 1):
            log.info(f"\n{'─'*50}\n[{i}/{total}]")
            factura = self.scraper.procesar(cufe)
            self.resultados.append(factura)
            if i % 5 == 0:
                self._guardar(salida)
            if i < total:
                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        self._guardar(salida)
        return self.resultados

    def _guardar(self, nombre: str):
        datos = []
        for f in self.resultados:
            d = asdict(f)
            d["items_json"] = json.dumps(d.pop("items", []), ensure_ascii=False)
            datos.append(d)
        with open(Path(nombre).with_suffix(".json"), "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in self.resultados], f, ensure_ascii=False, indent=2)
        try:
            import pandas as pd
            df = pd.DataFrame(datos)
            df.to_csv(Path(nombre).with_suffix(".csv"), index=False, encoding="utf-8-sig")
            df.to_excel(Path(nombre).with_suffix(".xlsx"), index=False)
        except ImportError:
            pass
