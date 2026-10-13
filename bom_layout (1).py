"""
bom_layout.py — Base del motor de BOMs.

Auto-detecta TODO lo medible de un PDF de BOM (Oracle EBS Structure Report)
en lugar de hardcodearlo, para que funcione con cualquier BOM del mismo formato.

Expone:
  detect_layout(doc)   -> dict con font, line_h, char_w, columnas (por etiqueta),
                          y posiciones clave (sección del BOM, End of Report).
  validate_layout(doc, layout) -> (ok, mensaje). Estricta: aborta si falta lo esencial.
  would_overflow(layout, n_lines) -> True/False  (red de seguridad Nivel 1)

Notas de diseño:
  - Las columnas se derivan de la LÍNEA DE GUIONES ('--- ---- ----...'), que marca
    el inicio y ancho exacto de cada columna. Las 8 primeras (Level..Quantity) son
    idénticas en todos los formatos vistos; las siguientes se etiquetan según el
    tipo de reporte detectado en el header (Inventory vs Engineering).
  - Todo se limita a la SECCIÓN DEL BOM: desde la línea de guiones hasta el primer
    'End of Report'. Un PDF puede traer otros reportes después (p.ej. Routing).
"""

import re
import fitz

__version__ = "1.8.1"
__fecha__ = "2026-10-13"

# ── Historial ───────────────────────────────────────────────────────────────
# 1.8.1  'End of Report' ya no bloquea el procesamiento. Se busca por RENGLÓN y
#        sin distinguir mayúsculas (antes era texto exacto dentro de UN span, y
#        fallaba si venía partido en varios o escrito distinto). Si de verdad no
#        está, se toma el final del documento como cierre de la sección y se
#        avisa, en vez de abortar y no generar ningún archivo.
# 1.8.0  Columnas estrechas (Level, Op Seq, Item Seq) editables de verdad:
#        las columnas auxiliares de los renglones de continuación (rev_desc,
#        rev_desc_rev, desc_cont) comparten X con Level/Op Seq y rompían el
#        cálculo de sus límites, así que edit_field no encontraba el valor.
#        Además el valor nuevo se coloca AL LADO del tachado (derecha o
#        izquierda, donde quepa) en vez de debajo, para no pisar la fila
#        siguiente. Y set_rev_description avisa en vez de escribir cuando el
#        componente no tiene renglón libre debajo (antes tachaba datos de la
#        fila siguiente).
# 1.7.0  El texto nuevo se escribe con una fuente del sistema (Consolas si
#        está, si no DejaVu/Courier) y con el TAMAÑO AJUSTADO para igualar el
#        ancho de carácter real del PDF (5.36 en Consolas frente a 5.85 en
#        Courier): antes quedaba más ancho e invadía la columna siguiente.
#        No se usa el tipo embebido del PDF: es un subset sin ToUnicode y su
#        texto no se puede volver a leer.
# 1.6.2  En Windows el glob de "*.pdf" y "*.PDF" devolvía cada archivo DOS
#        veces (el sistema no distingue mayúsculas) y cada BOM se procesaba
#        por duplicado. Se deduplica por ruta normalizada.
# 1.6.1  La Rev Description del BOM ya NO depende de 'agregar_bom': antes el
#        bloque entero se saltaba con agregar_bom=NO y el comentario no se
#        escribía ni se tachaba el anterior.
# 1.6.0  Doble comprobación para 'rev': el valor debe TENER FORMA de revisión
#        (letras o dígitos, nunca un UOM como 'EA'). Si la geometría falla,
#        busca en la fila un valor con forma de revisión antes de la columna UOM.
# 1.5.1  Tolerancia vertical acotada por el tamaño de fuente: si line_h se
#        detecta mal (el doble de lo real), la búsqueda abarcaba DOS filas y
#        tomaba valores de la de abajo (bug: editaba UOM 'EA'->'EB' en vez de Rev).
# 1.5.0  find_in_bom_section prioriza la columna ITEM (antes tomaba el código
#        del encabezado de página y las ediciones caían en columnas erróneas,
#        p. ej. editaba UOM 'EA'->'EB' en vez de Rev).
# 1.4.0  'Rev Description': detección según orientación (wrap vertical vs una
#        sola línea en horizontal); redline sobre la Rev Description anterior.
# 1.3.0  Versión limpia (_CLEAN_COPY) + nombres item(BOM)_REVxxx_REDLINE.
# 1.2.0  Rev del BOM numérica (3 dígitos); actualiza Rev si el BOM ya estaba.
# 1.1.0  Opciones: página horizontal, revisión en la misma línea.
# 1.0.0  Base: detección automática de layout y las 5 operaciones de redline.
from collections import Counter

# Nombres universales de las 8 primeras columnas (iguales en todos los formatos)
BASE_COLS = ["level", "op_seq", "item_seq", "item", "desc", "rev", "uom", "qty"]

# Columnas extra según tipo de reporte (después de 'qty')
EXTRA_COLS = {
    "inventory":   ["status", "category"],
    "engineering": ["eff_date", "eff_time", "dis_date", "dis_time", "ext_qty", "onhand"],
}

SEPARATOR_RE = re.compile(r"-{5,}")        # para IDENTIFICAR la línea (corrida larga)
GROUP_RE = re.compile(r"-+")               # para SEPARAR columnas (grupos de 3+ guiones)
PAGE_BOTTOM_MARGIN = 28                     # margen inferior útil (pts)


def _spans(page):
    """Itera todos los spans de texto de una página."""
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for s in line["spans"]:
                yield s


def _find_separator_line(doc):
    """Devuelve (page_num, y, x0, x1, text) de la línea de guiones que separa el
    header de columnas de los datos del BOM.

    Oracle emite VARIOS renglones de guiones seguidos: el principal (con todas las
    columnas de la tabla) y continuaciones cortas de las últimas columnas
    ('Item Category / Rev Description'). Según el ancho del reporte, el principal
    no siempre es el primero, así que se elige el renglón con MÁS grupos de
    guiones, que es el que describe la tabla completa.
    """
    mejor = None          # (n_grupos, page_num, y, x0, x1, texto)
    for pn in range(len(doc)):
        por_y = {}
        for s in _spans(doc[pn]):
            por_y.setdefault(round(s["bbox"][1], 1), []).append(s)

        for y in sorted(por_y):
            spans_y = sorted(por_y[y], key=lambda s: s["bbox"][0])
            texto = "".join(s["text"] for s in spans_y)
            if texto.count("-") < 9 or not SEPARATOR_RE.search(texto):
                continue
            n_grupos = len(GROUP_RE.findall(texto))
            x0 = min(s["bbox"][0] for s in spans_y)
            x1 = max(s["bbox"][2] for s in spans_y)
            if mejor is None or n_grupos > mejor[0]:
                mejor = (n_grupos, pn, y, x0, x1, texto)
        # Si ya se halló un separador con pinta de tabla completa, no hace falta
        # seguir: los reportes posteriores (p. ej. Routing) traen los suyos.
        if mejor is not None and mejor[0] >= 6:
            break

    if mejor is None:
        return None, None, None, None, None
    _, pn, y, x0, x1, texto = mejor
    return pn, y, x0, x1, texto


def _find_header_text(doc, sep_page, sep_y):
    """Junta el texto del header de columnas (las líneas justo encima de los
    guiones que contienen 'Level' e 'Item' y/o 'Effective'/'Disable')."""
    parts = []
    for s in _spans(doc[sep_page]):
        y = s["bbox"][1]
        if sep_y - 40 < y < sep_y:
            t = s["text"]
            if any(k in t for k in ("Level", "Item", "Description",
                                    "Effective", "Disable", "Extended", "Onhand")):
                parts.append(t)
    return " ".join(parts)


def _detect_report_type(header_text):
    """Inventory (…Status/Category) vs Engineering (…Effective/Disable/Onhand)."""
    h = header_text.lower()
    if "effective" in h or "disable" in h or "onhand" in h or "extended" in h:
        return "engineering"
    return "inventory"


EOR_RE = re.compile(r"end\s*[-_]?\s*of\s*[-_]?\s*report", re.I)


def _find_end_of_report(doc):
    """(page_num, y, estimado) del PRIMER 'End of Report'.

    Se busca por RENGLÓN y sin distinguir mayúsculas, porque el texto puede venir
    partido en varios spans ('*****', 'End of', 'Report', '*****') o escrito de
    otra forma ('END OF REPORT', 'End-of-Report').

    Si el PDF no lo trae (por ejemplo, un reporte recortado o separado a mano),
    NO se aborta: se toma el final del contenido del documento como cierre de la
    sección y se marca `estimado=True` para avisarlo.
    """
    for pn in range(len(doc)):
        for b in doc[pn].get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for linea in b["lines"]:
                texto = "".join(s["text"] for s in linea["spans"])
                if EOR_RE.search(texto):
                    return pn, linea["bbox"][1], False

    # ── Plan B: no hay 'End of Report' ──────────────────────────────────────
    # El cierre de la sección pasa a ser la última línea con texto del PDF.
    for pn in range(len(doc) - 1, -1, -1):
        ys = [s["bbox"][3] for s in _spans(doc[pn]) if s["text"].strip()]
        if ys:
            return pn, max(ys) + 2, True
    return None, None, False


def detect_layout(doc):
    """Mide el PDF y devuelve el dict de layout. No modifica el documento."""
    sep_page, sep_y, x_left, sep_x1, sep_text = _find_separator_line(doc)
    if sep_text is None:
        return {"ok": False, "reason": "No se encontró la línea de guiones (separador de columnas)."}

    # --- Tipografía: tamaño y nombre más comunes en la zona de la tabla ---
    sizes, fonts = [], []
    for pn in range(len(doc)):
        for s in _spans(doc[pn]):
            if s["text"].strip() and s["size"] > 5:
                sizes.append(round(s["size"], 2))
                fonts.append(s["font"])
    font_size = Counter(sizes).most_common(1)[0][0]
    font_name = Counter(fonts).most_common(1)[0][0]

    # --- Ancho de carácter REAL del PDF (no el de Courier): se mide del propio
    #     ancho de la línea de guiones. Es lo que alinea el texto nuevo con los datos.
    sep_len = len(sep_text.rstrip())
    char_w = (sep_x1 - x_left) / sep_len if sep_len else \
             fitz.get_text_length("M", fontname="cour", fontsize=font_size)

    # --- line_h: espaciado vertical más común en la página del separador ---
    ys = sorted({round(s["bbox"][1], 2) for s in _spans(doc[sep_page])})
    diffs = [round(ys[i + 1] - ys[i], 2) for i in range(len(ys) - 1)]
    diffs = [d for d in diffs if 0 < d < 30]
    line_h = Counter(diffs).most_common(1)[0][0] if diffs else round(font_size * 1.15, 2)

    # --- Columnas: posición de cada grupo de guiones ---
    groups = [(m.start(), m.end()) for m in GROUP_RE.finditer(sep_text)]
    header_text = _find_header_text(doc, sep_page, sep_y)
    report_type = _detect_report_type(header_text)
    col_names = BASE_COLS + EXTRA_COLS.get(report_type, [])

    col_x, col_w = {}, {}
    for i, (cs, ce) in enumerate(groups):
        if i < len(col_names):
            name = col_names[i]
            col_x[name] = round(x_left + cs * char_w, 2)
            col_w[name] = ce - cs
    if "desc" in col_x:
        col_x["desc_cont"] = col_x["desc"]

    # ── Columnas 'Rev Description' ───────────────────────────────────────────
    # Son las dos últimas columnas de la tabla. Según el ancho del reporte:
    #   SIN WRAP (hoja ancha): caben en la línea principal -> vienen como grupos
    #     extra después de 'category', y sus valores van en la MISMA línea.
    #   CON WRAP (hoja angosta): Oracle las envuelve a un segundo renglón de
    #     guiones -> sus valores van en el RENGLÓN SIGUIENTE de cada fila.
    rev_desc_wrap = False
    extra_idx = len(col_names)          # primer grupo sin nombre asignado
    if len(groups) > extra_idx:
        # Sin wrap: hay grupos de sobra en la línea principal.
        # Se asignan por ANCHO, no por orden: 'Rev' es un grupo corto (~3) y
        # 'Description' uno ancho (~19). Si solo sobra un grupo, es Description
        # (que es donde se escribe el texto).
        sobrantes = groups[extra_idx:extra_idx + 2]
        if len(sobrantes) == 1:
            cs, ce = sobrantes[0]
            nombre = "rev_desc_rev" if (ce - cs) <= 5 else "rev_desc"
            col_x[nombre] = round(x_left + cs * char_w, 2)
            col_w[nombre] = ce - cs
        else:
            for j, nombre in enumerate(["rev_desc_rev", "rev_desc"]):
                if j < len(sobrantes):
                    cs, ce = sobrantes[j]
                    col_x[nombre] = round(x_left + cs * char_w, 2)
                    col_w[nombre] = ce - cs
    else:
        # Con wrap: buscar el renglón de continuación debajo del separador
        for s in _spans(doc[sep_page]):
            y = s["bbox"][1]
            if not (sep_y < y < sep_y + line_h * 2.5):
                continue
            t = s["text"]
            if t.count("-") < 3 or not GROUP_RE.search(t):
                continue
            gx0 = s["bbox"][0]
            cont = [(m.start(), m.end()) for m in GROUP_RE.finditer(t)]
            for j, nombre in enumerate(["rev_desc_rev", "rev_desc"]):
                if j < len(cont):
                    cs, ce = cont[j]
                    col_x[nombre] = round(gx0 + cs * char_w, 2)
                    col_w[nombre] = ce - cs
            rev_desc_wrap = True
            break
    col_x.pop("_cont_y", None)

    eor_page, eor_y, eor_estimado = _find_end_of_report(doc)

    return {
        "ok": True,
        "report_type": report_type,
        "font_size": font_size,
        "font_name": font_name,
        "char_w": round(char_w, 3),
        "line_h": line_h,
        "x_left": round(x_left, 2),
        "page_width": doc[sep_page].rect.width,
        "page_height": doc[sep_page].rect.height,
        "page_bottom": round(doc[sep_page].rect.height - PAGE_BOTTOM_MARGIN, 2),
        "sep_page": sep_page,
        "sep_y": round(sep_y, 2),
        "eor_page": eor_page,
        "eor_y": round(eor_y, 2) if eor_y else None,
        "eor_estimado": eor_estimado,
        "n_columns": len(groups),
        "rev_desc_wrap": rev_desc_wrap,
        "col_x": col_x,
        "col_w": col_w,
    }


def validate_layout(doc, layout):
    """Validación ESTRICTA. Devuelve (ok, mensaje). Aborta si falta lo esencial."""
    if not layout.get("ok"):
        return False, layout.get("reason", "Layout no detectado.")
    needed = {"level", "item", "desc", "rev", "uom", "qty"}
    missing = needed - set(layout["col_x"])
    if missing:
        return False, f"Faltan columnas esenciales: {', '.join(sorted(missing))}."
    if layout["n_columns"] < 8:
        return False, f"Solo se detectaron {layout['n_columns']} columnas (se esperaban ≥8)."
    if layout["eor_page"] is None:
        return False, "El PDF no tiene texto legible (¿es un escaneo? haría falta OCR)."
    if not (6.5 <= layout["font_size"] <= 12):
        return False, f"Tamaño de fuente fuera de rango esperado: {layout['font_size']}."
    aviso = ("  [sin 'End of Report': se tomó el final del documento]"
             if layout.get("eor_estimado") else "")
    return True, (f"OK · {layout['report_type']} · {layout['n_columns']} cols · "
                  f"{layout['font_size']}pt · line_h {layout['line_h']}{aviso}")


def would_overflow(layout, y_insert, n_lines):
    """Nivel 1: ¿insertar n_lines en y_insert empujaría contenido fuera de la página?
    Conservador: asume que hay contenido hasta eor_y en esa página."""
    shift = layout["line_h"] * n_lines
    ref_bottom = layout["eor_y"] if layout["eor_y"] else layout["page_bottom"]
    return (ref_bottom + shift) > layout["page_bottom"]
