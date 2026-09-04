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
    """Devuelve (page_num, y, x0, x1, text) de la PRIMERA línea de guiones
    (la que separa el header de columnas de los datos del BOM)."""
    for pn in range(len(doc)):
        for s in _spans(doc[pn]):
            t = s["text"]
            if t.count("-") >= 9 and SEPARATOR_RE.search(t):
                return pn, s["bbox"][1], s["bbox"][0], s["bbox"][2], t
    return None, None, None, None, None


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


def _find_end_of_report(doc):
    """(page_num, y) del PRIMER 'End of Report' (fin de la lista de componentes)."""
    for pn in range(len(doc)):
        for s in _spans(doc[pn]):
            if "End of Report" in s["text"]:
                return pn, s["bbox"][1]
    return None, None


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

    eor_page, eor_y = _find_end_of_report(doc)

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
        "n_columns": len(groups),
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
        return False, "No se encontró 'End of Report' (no se puede delimitar la sección del BOM)."
    if not (6.5 <= layout["font_size"] <= 12):
        return False, f"Tamaño de fuente fuera de rango esperado: {layout['font_size']}."
    return True, (f"OK · {layout['report_type']} · {layout['n_columns']} cols · "
                  f"{layout['font_size']}pt · line_h {layout['line_h']}")


def would_overflow(layout, y_insert, n_lines):
    """Nivel 1: ¿insertar n_lines en y_insert empujaría contenido fuera de la página?
    Conservador: asume que hay contenido hasta eor_y en esa página."""
    shift = layout["line_h"] * n_lines
    ref_bottom = layout["eor_y"] if layout["eor_y"] else layout["page_bottom"]
    return (ref_bottom + shift) > layout["page_bottom"]
