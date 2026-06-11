"""
Validia — Scraper DIAN v2 DEFINITIVO
======================================
Flujo completo: CUFE → portal DIAN → descarga PDF → extracción estructurada

Calibrado con factura real FE-6737 (27/05/2026)
Formato: Representación Gráfica DIAN — Solución Gratuita

Instalación:
    pip install playwright pdfplumber pandas openpyxl
    python -m playwright install chromium

Uso:
    python validia_cufe_scraper_v2.py --cufe <CUFE> --tenant <TENANT>
    python validia_cufe_scraper_v2.py --archivo facturas.xlsx --tenant MallAmerica
    python validia_cufe_scraper_v2.py --cufe <CUFE> --visible
"""

import argparse
import time
import random
import json
import re
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("validia")

URL_DIAN     = "https://catalogo-vpfe.dian.gov.co/User/SearchDocument"
DELAY_MIN    = 2.0
DELAY_MAX    = 5.0
TIMEOUT_MS   = 30_000
MAX_REINTENTOS = 3
REPO_BASE    = Path("pdfs")


# ── Estructuras de datos ────────────────────────────────────────────────────────

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
    precio_venta: str = ""


@dataclass
class FacturaCompleta:
    # Identificación
    cufe: str = ""
    numero_factura: str = ""
    forma_pago: str = ""
    medio_pago: str = ""
    fecha_emision: str = ""
    tipo_operacion: str = ""

    # Emisor
    emisor_razon_social: str = ""
    emisor_nit: str = ""
    emisor_tipo_contribuyente: str = ""
    emisor_regimen_fiscal: str = ""
    emisor_departamento: str = ""
    emisor_municipio: str = ""
    emisor_direccion: str = ""
    emisor_telefono: str = ""
    emisor_correo: str = ""

    # Receptor
    receptor_razon_social: str = ""
    receptor_tipo_documento: str = ""
    receptor_numero_documento: str = ""
    receptor_tipo_contribuyente: str = ""
    receptor_departamento: str = ""
    receptor_municipio: str = ""
    receptor_direccion: str = ""
    receptor_telefono: str = ""
    receptor_correo: str = ""

    # Totales
    subtotal: str = ""
    descuento_detalle: str = ""
    total_bruto: str = ""
    iva: str = ""
    total_impuesto: str = ""
    total_neto: str = ""
    total_factura_cop: str = ""

    # Items
    items: list = field(default_factory=list)

    # Autorización
    autorizacion_numero: str = ""
    autorizacion_rango_desde: str = ""
    autorizacion_rango_hasta: str = ""
    autorizacion_vigencia: str = ""

    # Generación
    fecha_generacion_doc: str = ""
    fecha_validacion_dian: str = ""
    pdf_generado_por: str = ""

    # Trazabilidad
    tenant_id: str = ""
    pdf_path: str = ""
    estado_dian: str = ""
    detalle_error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ── Repositorio de PDFs ─────────────────────────────────────────────────────────

class RepoPDF:
    """
    Organiza los PDFs descargados:
        pdfs/<tenant_id>/<YYYY-MM>/<cufe16>_<folio>.pdf
    """
    def __init__(self, base: Path = REPO_BASE):
        self.base = base

    def ruta(self, cufe: str, tenant: str, folio: str = "", fecha: str = "") -> Path:
        mes = fecha[:7].replace("/", "-") if fecha else datetime.now().strftime("%Y-%m")
        # fecha viene como "27/05/2026" → tomar año-mes = "2026-05"
        if "/" in mes:
            partes = fecha.split("/")
            mes = f"{partes[2][:4]}-{partes[1]}" if len(partes) == 3 else datetime.now().strftime("%Y-%m")
        nombre = f"{cufe[:16]}_{folio}.pdf" if folio else f"{cufe[:16]}.pdf"
        carpeta = self.base / (tenant or "default") / mes
        carpeta.mkdir(parents=True, exist_ok=True)
        return carpeta / nombre

    def guardar(self, bytes_: bytes, cufe: str, tenant: str,
                folio: str = "", fecha: str = "") -> Path:
        ruta = self.ruta(cufe, tenant, folio, fecha)
        ruta.write_bytes(bytes_)
        log.info(f"PDF guardado → {ruta}  ({len(bytes_):,} bytes)")
        return ruta


# ── Extractor de PDF ────────────────────────────────────────────────────────────

class ExtractorPDF:
    """
    Extrae datos estructurados del PDF de Representación Gráfica DIAN.
    Calibrado con el formato real observado en la prueba de concepto.
    """

    def extraer(self, pdf_path: Path) -> dict:
        try:
            import pdfplumber
            return self._con_pdfplumber(pdf_path)
        except Exception as e:
            log.warning(f"pdfplumber falló ({e}) — intentando PyMuPDF...")
            try:
                import fitz
                return self._con_pymupdf(pdf_path)
            except Exception as e2:
                log.error(f"Extracción fallida: {e2}")
                return {}

    def _con_pdfplumber(self, pdf_path: Path) -> dict:
        import pdfplumber
        paginas_texto = []
        items = []

        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, pagina in enumerate(pdf.pages):
                texto = pagina.extract_text(layout=True) or ""
                paginas_texto.append(texto)

                # Tabla de items solo en página 1
                if i == 0:
                    for tabla in pagina.extract_tables():
                        extraidos = self._parsear_tabla_items(tabla)
                        if extraidos:
                            items = extraidos
                            break

        texto_completo = "\n".join(paginas_texto)
        datos = self._parsear_campos(paginas_texto[0] if paginas_texto else "",
                                     paginas_texto[1] if len(paginas_texto) > 1 else "")
        datos["items"] = items
        return datos

    def _con_pymupdf(self, pdf_path: Path) -> dict:
        import fitz
        doc = fitz.open(str(pdf_path))
        paginas = [p.get_text("layout") for p in doc]
        doc.close()
        datos = self._parsear_campos(
            paginas[0] if paginas else "",
            paginas[1] if len(paginas) > 1 else ""
        )
        datos["items"] = []
        return datos

    def _parsear_campos(self, p1: str, p2: str) -> dict:
        """
        Patrones regex calibrados con el formato real de factura DIAN.
        Estructura observada: etiqueta + valor separados por espacios/columnas.
        """
        def b(patron, fuente=p1):
            m = re.search(patron, fuente, re.IGNORECASE | re.MULTILINE)
            return m.group(1).strip() if m else ""

        return {
            # Documento
            "numero_factura":   b(r"Número de Factura:\s*(\S+)"),
            "forma_pago":       b(r"Forma de pago:\s*(\w+)"),
            "medio_pago":       b(r"Medio de Pago:\s*(\w+)"),
            "fecha_emision":    b(r"Fecha de Emisión:\s*([\d/]+)"),
            "tipo_operacion":   b(r"Tipo de Operación:\s*(\d+ - \w+)"),

            # Emisor
            "emisor_razon_social":       b(r"Razón Social:\s*([A-ZÁÉÍÓÚÑ ]+)"),
            "emisor_nit":                b(r"Nit del Emisor:\s*(\d+)"),
            "emisor_tipo_contribuyente": b(r"Tipo de Contribuyente:\s*(Persona Natural)"),
            "emisor_regimen_fiscal":     b(r"Régimen Fiscal:\s*(\S+)"),
            "emisor_departamento":       b(r"Departamento:\s*([\w ]+?)\s{2,}"),
            "emisor_municipio":          b(r"Municipio / Ciudad:\s*(\w+)"),
            "emisor_direccion":          b(r"Dirección:\s*(CL[\w\s]+?)\s{2,}"),
            "emisor_telefono":           b(r"Teléfono / Móvil:\s*(\d+)"),
            "emisor_correo":             b(r"Correo:\s*([\w.\-@]+\.\w{2,})"),

            # Receptor
            "receptor_razon_social":       b(r"Nombre o Razón Social:\s*([A-ZÁÉÍÓÚÑ ]+)"),
            "receptor_tipo_documento":     b(r"Tipo de Documento:\s*(\w+)"),
            "receptor_numero_documento":   b(r"Número Documento:\s*(\d+)"),
            "receptor_tipo_contribuyente": b(r"Tipo de Contribuyente:\s*(Persona Jurídica)"),
            "receptor_departamento":       b(r"Departamento:\s*(VALLE[\w ]+?)\s{2,}"),
            "receptor_municipio":          b(r"Municipio / Ciudad:\s*CALI"),
            "receptor_direccion":          b(r"Dirección:\s*(AV[\w\s]+?)\s{2,}"),
            "receptor_telefono":           b(r"Teléfono / Móvil:\s*(\d{10})"),
            "receptor_correo":             b(r"Correo:\s*([\w.\-@]+\.co\b)"),

            # Totales — de página 2, columna COP (la que tiene valores)
            "subtotal":          b(r"Subtotal\s+([\d.,]+)", p2),
            "descuento_detalle": "0,00",
            "total_bruto":       b(r"Total Bruto Factura\s+([\d.,]+)", p2),
            "iva":               b(r"\bIVA\b\s+([\d.,]+)", p2),
            "total_impuesto":    b(r"Total impuesto \(=\)\s+([\d.,]+)", p2),
            "total_neto":        b(r"Total neto factura \(=\)\s+([\d.,]+)", p2),
            "total_factura_cop": b(r"Total factura \(=\) COP \$\s*([\d.,]+)", p2),

            # Autorización
            "autorizacion_numero":      b(r"Número de Autorización:\s*(\d+)Rango", p2),
            "autorizacion_rango_desde": b(r"Rango desde:\s*(\d+)Rango", p2),
            "autorizacion_rango_hasta": b(r"Rango hasta:\s*(\d+)Vigencia", p2),
            "autorizacion_vigencia":    b(r"Vigencia:\s*([\d\-]+)", p2),

            # Generación
            "fecha_generacion_doc":  b(r"Documento generado el:\s*([\d/: ]+)", p2),
            "fecha_validacion_dian": b(r"DIAN:\s*([\d/: ]+)", p2),
            "pdf_generado_por":      b(r"PDF Generado por:\s*([^\n]+)", p2),
        }

    def _parsear_tabla_items(self, tabla: list) -> list:
        """
        Parsea la tabla de productos del PDF.
        Estructura real DIAN:
            Col 0: Nro | Col 1: Código | Col 2: Descripción | Col 3: U/M
            Col 4: Cantidad | Col 5: Precio unitario | Col 6: Descuento
            Col 7: Recargo | Col 12: Precio venta
        """
        if not tabla or len(tabla) < 2:
            return []

        items = []
        for fila in tabla:
            if not fila or not fila[0]:
                continue
            # La fila de item real comienza con número
            if not str(fila[0]).strip().isdigit():
                continue

            def c(i, default=""):
                val = fila[i] if i < len(fila) else None
                return str(val).strip() if val else default

            items.append(asdict(ItemFactura(
                nro            = c(0),
                codigo         = c(1),
                descripcion    = c(2),
                unidad_medida  = c(3),
                cantidad       = c(4),
                precio_unitario= c(5),
                descuento      = c(6),
                recargo        = c(7),
                precio_venta   = c(12) or c(len(fila)-1),
            )))

        return items


# ── Motor de scraping ───────────────────────────────────────────────────────────

class ScraperDIAN:
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
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
        )
        self._page = self._ctx.new_page()
        log.info("Navegador listo")

    def close(self):
        for obj in [self._ctx, self._browser, self._pw]:
            try:
                if obj: obj.close() if hasattr(obj, "close") else obj.stop()
            except: pass

    def __enter__(self):
        self.launch(); return self

    def __exit__(self, *_):
        self.close()

    # ── Flujo principal ─────────────────────────────────────────────────────
    def procesar(self, cufe: str, intento: int = 1) -> FacturaCompleta:
        cufe = cufe.strip()
        log.info(f"[{intento}/{MAX_REINTENTOS}] CUFE: {cufe[:16]}...")
        factura = FacturaCompleta(cufe=cufe, tenant_id=self.tenant_id)

        try:
            # Paso 1: Buscar en el portal
            self._page.goto(URL_DIAN, timeout=TIMEOUT_MS, wait_until="networkidle")
            time.sleep(random.uniform(0.5, 1.2))

            campo = self._page.wait_for_selector(
                "input[placeholder*='CUFE'], input[placeholder*='UUID'], input[placeholder*='código']",
                timeout=10_000
            )
            campo.triple_click()
            campo.fill(cufe)
            time.sleep(random.uniform(0.3, 0.6))
            self._page.click("button:has-text('Buscar')", timeout=5_000)
            self._page.wait_for_url("**/ShowDocumentToPublic**", timeout=TIMEOUT_MS)
            self._page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)
            time.sleep(random.uniform(0.5, 1.0))

            # Paso 2: Extraer metadatos de la página HTML
            self._extraer_pagina_html(factura)
            if factura.estado_dian == "No encontrada":
                return factura

            # Paso 3: Descargar PDF
            pdf_bytes = self._descargar_pdf(cufe)

            if pdf_bytes:
                # Paso 4: Guardar en repositorio
                ruta = self.repo.guardar(
                    bytes_  = pdf_bytes,
                    cufe    = cufe,
                    tenant  = self.tenant_id,
                    folio   = factura.numero_factura.replace("FE-", ""),
                    fecha   = factura.fecha_emision,
                )
                factura.pdf_path = str(ruta)

                # Paso 5: Extraer campos del PDF
                log.info("Extrayendo datos del PDF...")
                datos = self.extractor.extraer(ruta)
                self._aplicar_datos_pdf(factura, datos)
                log.info(f"Items extraídos: {len(factura.items)}")
            else:
                log.warning("PDF no disponible — usando solo datos de la página")

        except Exception as e:
            log.error(f"Error: {e}")
            if intento < MAX_REINTENTOS:
                time.sleep(5 * intento)
                return self.procesar(cufe, intento + 1)
            factura.estado_dian   = "Error"
            factura.detalle_error = str(e)

        return factura

    def _extraer_pagina_html(self, factura: FacturaCompleta):
        """Extrae campos rápidos del HTML del resultado DIAN."""
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

        factura.numero_factura = "FE-" + entre("Folio: ", "\n")
        factura.fecha_emision  = entre("Fecha de emisión de la factura Electrónica: ", "\n")

        bloque_e = entre("DATOS DEL EMISOR", "DATOS DEL RECEPTOR")
        factura.emisor_nit          = entre("NIT: ", "\n", bloque_e)
        factura.emisor_razon_social = entre("Nombre: ", "\n", bloque_e)

        bloque_r = entre("DATOS DEL RECEPTOR", "TOTALES E IMPUESTOS")
        factura.receptor_numero_documento = entre("NIT: ", "\n", bloque_r)
        factura.receptor_razon_social     = entre("Nombre: ", "\n", bloque_r)

        factura.iva              = entre("IVA: ", "\n")
        factura.total_factura_cop = entre("Total: ", "\n")

        log.info(
            f"HTML OK: {factura.numero_factura} | "
            f"{factura.emisor_razon_social} → {factura.receptor_razon_social} | "
            f"Total: {factura.total_factura_cop}"
        )

    def _descargar_pdf(self, cufe: str) -> Optional[bytes]:
        """
        Descarga el PDF interceptando el submit del formulario DIAN.
        El form hace POST a /Document/DownloadPDF con trackId + token de sesión.
        """
        log.info("Descargando PDF...")
        try:
            with self._page.expect_download(timeout=30_000) as dl:
                self._page.click("a.downloadLink", timeout=5_000)
            download = dl.value
            ruta_tmp = Path(download.path())
            if ruta_tmp and ruta_tmp.exists():
                bytes_ = ruta_tmp.read_bytes()
                log.info(f"PDF descargado: {len(bytes_):,} bytes")
                return bytes_
        except Exception as e:
            log.warning(f"expect_download falló ({e}) — intentando vía requests...")

        # Fallback: POST directo con cookies de sesión
        return self._descargar_via_requests(cufe)

    def _descargar_via_requests(self, cufe: str) -> Optional[bytes]:
        """Fallback: POST directo reutilizando cookies de Playwright."""
        import requests
        try:
            cookies = {c["name"]: c["value"] for c in self._ctx.cookies()}
            token = self._page.eval_on_selector(
                "form#postForm input[name='token']", "el => el.value"
            )
            resp = requests.post(
                "https://catalogo-vpfe.dian.gov.co/Document/DownloadPDF",
                data={"trackId": cufe, "token": token},
                cookies=cookies,
                headers={
                    "Referer": self._page.url,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=30,
            )
            if resp.status_code == 200 and resp.content[:4] == b"%PDF":
                log.info(f"PDF vía requests: {len(resp.content):,} bytes")
                return resp.content
            else:
                log.error(f"Respuesta inesperada HTTP {resp.status_code}")
        except Exception as e:
            log.error(f"Fallback requests falló: {e}")
        return None

    def _aplicar_datos_pdf(self, factura: FacturaCompleta, datos: dict):
        """Enriquece la factura con los campos extraídos del PDF."""
        for campo in [
            "numero_factura", "forma_pago", "medio_pago", "fecha_emision",
            "tipo_operacion",
            "emisor_razon_social", "emisor_nit", "emisor_tipo_contribuyente",
            "emisor_regimen_fiscal", "emisor_departamento", "emisor_municipio",
            "emisor_direccion", "emisor_telefono", "emisor_correo",
            "receptor_razon_social", "receptor_tipo_documento",
            "receptor_numero_documento", "receptor_tipo_contribuyente",
            "receptor_departamento", "receptor_municipio", "receptor_direccion",
            "receptor_telefono", "receptor_correo",
            "subtotal", "descuento_detalle", "total_bruto", "iva",
            "total_impuesto", "total_neto", "total_factura_cop",
            "autorizacion_numero", "autorizacion_rango_desde",
            "autorizacion_rango_hasta", "autorizacion_vigencia",
            "fecha_generacion_doc", "fecha_validacion_dian", "pdf_generado_por",
        ]:
            val = datos.get(campo, "")
            if val and not getattr(factura, campo, ""):
                setattr(factura, campo, val)

        if datos.get("items"):
            factura.items = datos["items"]


# ── Procesador de lotes ─────────────────────────────────────────────────────────

class ProcesadorLote:
    def __init__(self, scraper: ScraperDIAN):
        self.scraper    = scraper
        self.resultados = []

    def procesar(self, cufes: list, salida: str = "facturas_validia") -> list:
        total = len(cufes)
        log.info(f"Lote: {total} CUFEs | tenant: {self.scraper.tenant_id}")

        for i, cufe in enumerate(cufes, 1):
            log.info(f"\n{'─'*55}\n[{i}/{total}]")
            factura = self.scraper.procesar(cufe)
            self.resultados.append(factura)

            if i % 5 == 0:
                self._guardar(salida)
                log.info(f"Progreso guardado ({i}/{total})")

            if i < total:
                espera = random.uniform(DELAY_MIN, DELAY_MAX)
                log.info(f"Esperando {espera:.1f}s...")
                time.sleep(espera)

        self._guardar(salida)
        self._resumen()
        return self.resultados

    def _guardar(self, nombre: str):
        datos = []
        for f in self.resultados:
            d = asdict(f)
            d["items_json"] = json.dumps(d.pop("items", []), ensure_ascii=False)
            datos.append(d)

        with open(Path(nombre).with_suffix(".json"), "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in self.resultados], f,
                      ensure_ascii=False, indent=2)
        try:
            import pandas as pd
            df = pd.DataFrame(datos)
            df.to_csv(Path(nombre).with_suffix(".csv"), index=False, encoding="utf-8-sig")
            df.to_excel(Path(nombre).with_suffix(".xlsx"), index=False)
        except ImportError:
            pass

    def _resumen(self):
        t = len(self.resultados)
        print(f"\n{'='*50}")
        print(f"  VALIDIA — Resumen")
        print(f"{'='*50}")
        print(f"  Total          : {t}")
        print(f"  ✓ Válidas      : {sum(1 for r in self.resultados if r.estado_dian == 'Valida')}")
        print(f"  ↓ Con PDF      : {sum(1 for r in self.resultados if r.pdf_path)}")
        print(f"  ≡ Con items    : {sum(1 for r in self.resultados if r.items)}")
        print(f"  ✗ Errores      : {sum(1 for r in self.resultados if r.estado_dian == 'Error')}")
        print(f"{'='*50}")


# ── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validia v2 — CUFE → PDF → Datos")
    parser.add_argument("--cufe",    help="CUFE individual")
    parser.add_argument("--archivo", help="CSV o Excel con lista de CUFEs")
    parser.add_argument("--columna", default="cufe")
    parser.add_argument("--tenant",  default="default", help="ID del tenant / centro comercial")
    parser.add_argument("--salida",  default="facturas_validia")
    parser.add_argument("--visible", action="store_true", help="Abrir navegador visible")
    args = parser.parse_args()

    if args.cufe:
        with ScraperDIAN(headless=not args.visible, tenant_id=args.tenant) as s:
            factura = s.procesar(args.cufe)
            print(json.dumps(asdict(factura), ensure_ascii=False, indent=2))
        return

    if args.archivo:
        import pandas as pd
        path = Path(args.archivo)
        df = pd.read_excel(path) if path.suffix in (".xlsx", ".xls") else pd.read_csv(path)
        cufes = df[args.columna].dropna().tolist()
        with ScraperDIAN(headless=not args.visible, tenant_id=args.tenant) as s:
            ProcesadorLote(s).procesar(cufes, args.salida)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
