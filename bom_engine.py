"""
bom_engine.py — Operaciones de redline sobre BOMs.

Convención de redline (todo en rojo):
  - Lo que se ELIMINA  -> tachado (strikethrough)
  - Lo que se AGREGA    -> escrito en rojo (subrayado)

Cada operación recibe `layout` (de bom_layout.detect_layout) para alinearse al
formato real del PDF, y se limita a la sección del BOM.
"""

import os
import tempfile
import fitz

RED   = (0.85, 0.0, 0.0)
WHITE = (1.0, 1.0, 1.0)


def _spans(page):
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for s in line["spans"]:
                yield s


# ── Fuente para el texto nuevo (redline) ─────────────────────────────────────
# TextWriter renderiza fuentes externas SIN el bug de codificación de insert_text.
# Preferencia: Consolas (match exacto, p.ej. en Windows) > DejaVu Sans Mono
# (muy parecido) > Courier interno. Todas monoespaciadas y de ancho equivalente.
_MONO_CANDIDATES = [
    r"C:/Windows/Fonts/consola.ttf",
    r"C:/Windows/Fonts/Consolas.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/Library/Fonts/Consolas.ttf",
]

def _resolve_mono_font():
    for p in _MONO_CANDIDATES:
        if os.path.exists(p):
            try:
                return fitz.Font(fontfile=p)
            except Exception:
                continue
    return fitz.Font("cour")     # Courier interno (siempre disponible)

_FONT = _resolve_mono_font()


def _text_width(text, fontsize, font_obj=None):
    return _FONT.text_length(str(text), fontsize=fontsize)


def _write(page, x, y_baseline, text, fontsize, color, font_path=None, font_obj=None):
    """Escribe texto nuevo (redline) con TextWriter y la mejor fuente mono disponible."""
    if not text or not str(text).strip():
        return
    tw = fitz.TextWriter(page.rect, color=color)
    tw.append(fitz.Point(x, y_baseline), str(text), font=_FONT, fontsize=fontsize)
    tw.write_text(page)


# ════════════════════════════════════════════════════════════════════════════
# FUENTE EMBEBIDA (para escribir texto nuevo con el mismo font del PDF)
# ════════════════════════════════════════════════════════════════════════════

def extract_pdf_font(doc, page_num=0):
    """Obsoleto (la fuente se resuelve automáticamente). Se mantiene por
    compatibilidad: devuelve (None, None)."""
    return None, None


# ════════════════════════════════════════════════════════════════════════════
# BÚSQUEDA EN LA SECCIÓN DEL BOM (ignora otros reportes del PDF)
# ════════════════════════════════════════════════════════════════════════════

def _norm(s):
    return s.strip().upper().replace("\u2010", "-").replace("\u2011", "-")


def find_in_bom_section(doc, layout, target):
    """Ocurrencias exactas de `target` SOLO dentro de la sección del BOM
    (entre la línea de guiones y el primer 'End of Report')."""
    tgt = _norm(target)
    sp, ep = layout["sep_page"], layout["eor_page"]
    sep_y, eor_y = layout["sep_y"], layout["eor_y"]
    out = []
    for pn in range(sp, ep + 1):
        for x0, y0, x1, y1, t, *_ in doc[pn].get_text("words"):
            if _norm(t) != tgt:
                continue
            if pn == sp and y0 < sep_y:        # antes de la tabla
                continue
            if pn == ep and eor_y and y0 > eor_y:  # después de End of Report
                continue
            out.append((pn, x0, y0, x1, y1))
    return out


# ════════════════════════════════════════════════════════════════════════════
# OPERACIÓN: REEMPLAZAR CÓDIGO DE COMPONENTE (redline)
# ════════════════════════════════════════════════════════════════════════════

def replace_part(doc, layout, old_part, new_part, font_path=None, font_obj=None):
    """Por cada ocurrencia de old_part en la sección del BOM:
        - tacha old_part en rojo (en su lugar)
        - escribe new_part en rojo, subrayado, justo debajo, en la columna 'item'
    """
    occ = find_in_bom_section(doc, layout, old_part)
    if not occ:
        return False, f"'{old_part}' no encontrado en la sección del BOM."

    sz = layout["font_size"]
    lh = layout["line_h"]
    item_x = layout["col_x"]["item"]

    for pn, x0, y0, x1, y1 in occ:
        page = doc[pn]
        # 1. borrar y tachar el viejo en su lugar
        page.add_redact_annot(fitz.Rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1), fill=WHITE)
        page.apply_redactions()
        _write(page, x0, y0 + sz * 0.85, old_part, sz, RED, font_path, font_obj)
        y_mid = y0 + (y1 - y0) * 0.48
        page.draw_line(fitz.Point(x0 - 1, y_mid), fitz.Point(x1 + 1, y_mid),
                       color=RED, width=0.7)
        # 2. escribir el nuevo debajo, en la columna item, subrayado
        y_below = y0 + lh
        _write(page, item_x, y_below + sz * 0.85, new_part, sz, RED, font_path, font_obj)
        w = _text_width(new_part, sz, font_obj)
        y_ul = y_below + sz * 1.05
        page.draw_line(fitz.Point(item_x, y_ul), fitz.Point(item_x + w, y_ul),
                       color=RED, width=0.6)

    pages = ", ".join(str(p + 1) for p, *_ in occ)
    return True, f"'{old_part}' → '{new_part}' en {len(occ)} lugar(es) (pág. {pages})"


# ════════════════════════════════════════════════════════════════════════════
# OPERACIÓN: ACTUALIZAR REVISIÓN (redline)
# ════════════════════════════════════════════════════════════════════════════

def next_revision(current_rev):
    """001/002.. -> 'A';  A..Y -> siguiente letra;  Z -> 'AA';  AB -> 'AC'..."""
    v = str(current_rev).strip().upper()
    if not v:
        return None
    if v.isdigit():
        return "A"
    if v.isalpha():
        if v[-1] != "Z":
            return v[:-1] + chr(ord(v[-1]) + 1)
        return v[:-1] + "AA"   # carry simple (Z->AA, AZ->AAA)
    return None


def _find_revision_values(page):
    """Encuentra el VALOR de cada 'Revision:' en la página (puede estar en la
    misma línea o en la siguiente por wrap). Ignora la columna 'Rev' de la tabla."""
    words = page.get_text("words")
    by_y = {}
    for x0, y0, x1, y1, t, *_ in words:
        by_y.setdefault(round(y0, 0), []).append(
            {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": t})
    ys = sorted(by_y)
    out = []
    for i, yk in enumerate(ys):
        row = sorted(by_y[yk], key=lambda w: w["x0"])
        for j, w in enumerate(row):
            if w["text"].strip().lower() != "revision:":
                continue
            # valor en la misma línea (siguiente palabra no vacía)
            val = None
            for k in range(j + 1, len(row)):
                if row[k]["text"].strip() and row[k]["text"].strip() != ":":
                    val = row[k]; break
            # si no, en la línea siguiente, cerca del label
            if val is None and i + 1 < len(ys):
                nxt = sorted(by_y[ys[i + 1]], key=lambda w: w["x0"])
                for nw in nxt:
                    if nw["text"].strip() and nw["x0"] < w["x1"] + 80:
                        val = nw; break
            if val is not None:
                out.append(val)
    return out


def _find_revision_label(page, val):
    """Devuelve el word 'Revision:' que corresponde a un valor dado (mismo renglón
    o el renglón anterior, cuando el valor bajó por wrap). None si no se halla."""
    cands = [w for w in page.get_text("words") if w[4].strip().lower() == "revision:"]
    if not cands:
        return None
    # mismo renglón y a la izquierda
    same = [w for w in cands if abs(w[1] - val["y0"]) < 3 and w[2] <= val["x0"] + 1]
    if same:
        return max(same, key=lambda w: w[2])
    # renglón anterior (el valor bajó por wrap)
    prev = [w for w in cands if 0 < (val["y0"] - w[1]) < 30]
    if prev:
        return min(prev, key=lambda w: val["y0"] - w[1])
    return None


def update_revision(doc, layout, font_path=None, font_obj=None,
                    revision_misma_linea=False):
    """Detecta la revisión actual, calcula la siguiente y la actualiza en todas
    las páginas de la sección del BOM. Devuelve (ok, msg, old_rev, new_rev).

    revision_misma_linea: si el valor de la revisión quedó en la línea de abajo
    (wrap), reescribe el cambio junto a la etiqueta 'Revision:', en su misma línea.
    """
    # La revisión aparece en el bloque de parámetros y en el encabezado de cada
    # página. Ese bloque puede estar en páginas ANTERIORES a la tabla (p. ej. en
    # los reportes horizontales la tabla arranca en la pág. 2), así que se recorre
    # desde la primera página hasta el fin de la sección del BOM.
    ep = layout["eor_page"]
    sp = 0

    first = None
    for pn in range(sp, ep + 1):
        vals = _find_revision_values(doc[pn])
        if vals:
            first = vals
            break
    if not first:
        return False, "No se encontró 'Revision:' en el BOM.", None, None
    old_rev = first[0]["text"].strip()
    new_rev = next_revision(old_rev)
    if new_rev is None:
        return False, f"No se pudo calcular la revisión siguiente de '{old_rev}'.", old_rev, None

    sz = layout["font_size"]
    n = 0
    for pn in range(sp, ep + 1):
        page = doc[pn]
        for v in _find_revision_values(page):
            if v["text"].strip().upper() != old_rev.upper():
                continue
            x0, y0, x1, y1 = v["x0"], v["y0"], v["x1"], v["y1"]

            # ¿El valor está en otra línea que su etiqueta? -> moverlo arriba
            destino_x, destino_y = x0, y0
            if revision_misma_linea:
                lab = _find_revision_label(page, v)
                if lab is not None and abs(lab[1] - y0) >= 3:
                    destino_x, destino_y = lab[2] + layout["char_w"], lab[1]

            # borrar el valor viejo de su posición original
            page.add_redact_annot(fitz.Rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1), fill=WHITE)
            page.apply_redactions()

            # viejo tachado (en el destino) + nuevo al lado
            _write(page, destino_x, destino_y + sz * 0.85, old_rev, sz, RED, font_path, font_obj)
            w_old = _text_width(old_rev, sz, font_obj)
            y_mid = destino_y + (y1 - y0) * 0.5
            page.draw_line(fitz.Point(destino_x, y_mid), fitz.Point(destino_x + w_old, y_mid),
                           color=RED, width=0.7)
            x_new = destino_x + w_old + 4
            _write(page, x_new, destino_y + sz * 0.85, new_rev, sz, RED, font_path, font_obj)
            w_new = _text_width(new_rev, sz, font_obj)
            page.draw_line(fitz.Point(x_new, destino_y + sz * 1.05),
                           fitz.Point(x_new + w_new, destino_y + sz * 1.05),
                           color=RED, width=0.5)
            n += 1

    return True, f"Revisión '{old_rev}' → '{new_rev}' en {n} lugar(es).", old_rev, new_rev


# ════════════════════════════════════════════════════════════════════════════
# OPERACIÓN: AGREGAR EL BOM AL INICIO (condicional)
# ════════════════════════════════════════════════════════════════════════════

def split_description(desc, width_chars):
    """Parte la descripción en HASTA 3 sub-líneas sin cortar palabras.
    Devuelve la lista de líneas no vacías (1 a 3)."""
    width_chars = max(6, int(width_chars))
    def cut(s):
        if len(s) <= width_chars:
            return s, ""
        k = s.rfind(" ", 0, width_chars + 1)
        if k <= 0:
            k = width_chars
        return s[:k].rstrip(), s[k:].strip()
    l1, rest = cut(desc)
    l2, l3 = cut(rest) if rest else ("", "")
    return [x for x in (l1, l2, l3) if x] or [""]


def get_assembly_description(doc, layout):
    """Lee la descripción del ensamblaje del header ('Item: <código> <descripción>').
    Devuelve la descripción (sin el código) o ''."""
    best = ""
    for pn in range(layout["sep_page"] + 1):
        for s in _spans(doc[pn]):
            t = s["text"]
            if "Item:" in t and "Organization" not in t:
                after = t.split("Item:", 1)[1].strip()
                parts = after.split(None, 1)        # [código, resto...]
                if len(parts) == 2 and len(parts[1].strip()) > len(best):
                    best = parts[1].strip()
    return best


def _last_content_y(page):
    return max((s["bbox"][3] for s in _spans(page)), default=0)


def write_component_fields(page, y_top, comp, layout, color, font_path=None, font_obj=None):
    """Escribe una fila de componente alineada a las columnas detectadas.
    La descripción puede ocupar hasta 3 sub-líneas."""
    sz, lh, cx, cw = (layout["font_size"], layout["line_h"],
                      layout["col_x"], layout["col_w"])
    cwidth = layout["char_w"]

    def put(x, text, yb):
        _write(page, x, yb, text, sz, color, font_path, font_obj)

    yb = y_top + sz * 0.85
    put(cx["level"], comp.get("level", "1"), yb)
    put(cx["op_seq"], comp.get("op_seq", "10"), yb)
    put(cx["item_seq"], comp.get("item_seq", "10"), yb)
    put(cx["item"], comp.get("item", ""), yb)
    put(cx["rev"], comp.get("rev", "A"), yb)
    put(cx["uom"], comp.get("uom", "EA"), yb)

    # cantidad: alineada a la derecha del campo qty
    qty = str(comp.get("quantity", "1.00"))
    qty_right = cx["qty"] + cw.get("qty", 9) * cwidth
    put(qty_right - _text_width(qty, sz, font_obj), qty, yb)

    if "status" in cx:
        put(cx["status"], comp.get("status", "Active"), yb)
    if "category" in cx:
        put(cx["category"], comp.get("category", "MISC|MISC"), yb)

    # descripción (hasta 3 sub-líneas)
    desc_lines = split_description(comp.get("description", ""), cw.get("desc", 14))
    for i, dl in enumerate(desc_lines):
        put(cx["desc"], dl, y_top + lh * i + sz * 0.85)
    return len(desc_lines)


def _insert_blank_rows(doc, page_num, y_insert, shift):
    """Parte la página: arriba intacto, abajo desplazado `shift` pts. Devuelve
    el doc con la página reemplazada (in-place)."""
    src = doc[page_num]
    w, h = src.rect.width, src.rect.height
    tmp = fitz.open(); tmp.insert_pdf(doc, from_page=page_num, to_page=page_num)
    nd = fitz.open(); npg = nd.new_page(width=w, height=h)
    top = fitz.Rect(0, 0, w, y_insert - 0.5)
    npg.show_pdf_page(top, tmp, 0, clip=top)
    bsrc = fitz.Rect(0, y_insert - 0.5, w, h - shift)
    bdst = fitz.Rect(0, y_insert - 0.5 + shift, w, h)
    npg.show_pdf_page(bdst, tmp, 0, clip=bsrc)
    doc.delete_page(page_num)
    doc.insert_pdf(nd, from_page=0, to_page=0, start_at=page_num)
    tmp.close(); nd.close()
    return doc[page_num]


def bom_already_present(doc, layout, bom_code):
    """¿El código del BOM ya aparece como componente en la sección del BOM?"""
    base = _norm(bom_code).split("_R")[0]
    sp, ep = layout["sep_page"], layout["eor_page"]
    for pn in range(sp, ep + 1):
        for x0, y0, x1, y1, t, *_ in doc[pn].get_text("words"):
            if pn == sp and y0 < layout["sep_y"]:
                continue
            if pn == ep and layout["eor_y"] and y0 > layout["eor_y"]:
                continue
            if _norm(t).startswith(base):
                return True
    return False


def find_first_component_y(doc, layout):
    """(page_num, y_top) del primer componente tras la línea de guiones."""
    sp = layout["sep_page"]
    page = doc[sp]
    by_y = {}
    for s in _spans(page):
        by_y.setdefault(round(s["bbox"][1], 1), []).append(s)
    for y in sorted(by_y):
        if y <= layout["sep_y"] + 1:
            continue
        line = " ".join(s["text"] for s in by_y[y]).strip()
        if line and line[0].isdigit():     # filas empiezan con el nivel (1)
            return sp, y
    return None, None


def _fmt_rev_num(valor):
    """Formatea una revisión numérica a 3 dígitos: 9 -> '009', '10' -> '010'."""
    try:
        return f"{int(str(valor).strip()):03d}"
    except (TypeError, ValueError):
        return str(valor).strip()


def find_bom_row(doc, layout, bom_code):
    """Si el BOM ya está como componente, devuelve (page_num, x0, y0, x1, y1)
    de su código en la lista. Si no, None."""
    base = _norm(bom_code).split("_R")[0]
    sp, ep = layout["sep_page"], layout["eor_page"]
    for pn in range(sp, ep + 1):
        for x0, y0, x1, y1, t, *_ in doc[pn].get_text("words"):
            if pn == sp and y0 < layout["sep_y"]:
                continue
            if pn == ep and layout["eor_y"] and y0 > layout["eor_y"]:
                continue
            if _norm(t).startswith(base):
                return (pn, x0, y0, x1, y1)
    return None


def add_bom_at_start(doc, layout, bom_code, new_rev, font_path=None, font_obj=None,
                     rev_bom=None, actualizar_rev_bom=True):
    """Agrega el BOM al inicio, o actualiza su Rev si ya estaba.

    - Si el BOM NO está en la lista -> inserta la fila. Su columna `Rev` toma
      `rev_bom` (del Excel) o '001' si no se indicó.
    - Si el BOM YA está -> no se inserta; se actualiza su `Rev`: `rev_bom` si se
      indicó, o el valor actual + 1 (formato de 3 dígitos). Requiere
      `actualizar_rev_bom=True`.

    Nota: la revisión general del documento (letras) es independiente de esta.
    """
    existente = find_bom_row(doc, layout, bom_code)

    # ── Caso B: el BOM ya estaba -> actualizar su Rev (no insertar) ──────────
    if existente is not None:
        if not actualizar_rev_bom:
            return False, f"'{bom_code}' ya estaba en el BOM; no se agrega.", None
        pn, x0, y0, x1, y1 = existente
        page = doc[pn]
        sz = layout["font_size"]

        # Valor actual de la columna Rev en esa fila
        rx0, rx1 = _field_x_range(layout, "rev")
        margin = layout["char_w"] * 0.5
        celdas = [(wx0, wy0, wx1, wy1, t) for wx0, wy0, wx1, wy1, t, *_ in page.get_text("words")
                  if abs(wy0 - y0) < layout["line_h"] * 0.6 and rx0 - 1 <= wx0 < rx1 - margin]
        if not celdas:
            return False, f"'{bom_code}' ya estaba, pero no se halló su columna Rev.", None

        vx0 = min(c[0] for c in celdas); vy0 = min(c[1] for c in celdas)
        vx1 = max(c[2] for c in celdas); vy1 = max(c[3] for c in celdas)
        rev_actual = " ".join(c[4] for c in sorted(celdas, key=lambda c: c[0]))

        if rev_bom:
            rev_nueva = _fmt_rev_num(rev_bom)
        else:
            try:
                rev_nueva = _fmt_rev_num(int(rev_actual.strip()) + 1)
            except ValueError:
                return (False, f"'{bom_code}': Rev actual '{rev_actual}' no es numérica; "
                               f"indica la revisión en el Excel.", None)

        # redline: tachar el viejo y escribir el nuevo debajo
        page.add_redact_annot(fitz.Rect(vx0 - 1, vy0 - 1, vx1 + 1, vy1 + 1), fill=WHITE)
        page.apply_redactions()
        _write(page, vx0, vy0 + sz * 0.85, rev_actual, sz, RED, font_path, font_obj)
        y_mid = vy0 + (vy1 - vy0) * 0.5
        page.draw_line(fitz.Point(vx0, y_mid),
                       fitz.Point(vx0 + _text_width(rev_actual, sz), y_mid),
                       color=RED, width=0.7)
        y_bel = vy0 + layout["line_h"]
        _write(page, rx0, y_bel + sz * 0.85, rev_nueva, sz, RED, font_path, font_obj)
        w = _text_width(rev_nueva, sz)
        page.draw_line(fitz.Point(rx0, y_bel + sz * 1.05),
                       fitz.Point(rx0 + w, y_bel + sz * 1.05), color=RED, width=0.6)
        return (True, f"'{bom_code}' ya estaba: Rev '{rev_actual}' → '{rev_nueva}' "
                      f"(pág. {pn+1}).", None)

    # ── Caso A: el BOM no estaba -> insertar la fila ─────────────────────────
    rev_fila = _fmt_rev_num(rev_bom) if rev_bom else "001"
    item = bom_code                     # sin sufijo: la revisión va en la columna Rev
    asm_desc = get_assembly_description(doc, layout)
    comp = {"level": "1", "op_seq": "10", "item_seq": "10", "item": item,
            "description": f"BOM FOR {asm_desc}".strip(),
            "rev": rev_fila, "uom": "EA", "quantity": "1.00",
            "status": "Active", "category": "MISC|MISC"}

    pn, y_first = find_first_component_y(doc, layout)
    if y_first is None:
        return False, "No se encontró el inicio de la lista de componentes.", None

    n_lines = len(split_description(comp["description"], layout["col_w"].get("desc", 14)))
    shift = layout["line_h"] * n_lines

    # Red de seguridad Nivel 1: una línea solo se pierde si su TOPE se sale de la
    # página física tras el desplazamiento. (El proceso usa la hoja completa.)
    last_top = max((s["bbox"][1] for s in _spans(doc[pn])), default=0)
    if last_top + shift + layout["line_h"] > layout["page_height"] + 2:
        return (False,
                f"Insertar el BOM empujaría contenido fuera de la página {pn+1} "
                f"(falta reflujo de página). Abortado para no perder datos.", item)

    page = _insert_blank_rows(doc, pn, y_first, shift)
    write_component_fields(page, y_first, comp, layout, RED, font_path, font_obj)
    return True, f"BOM '{item}' insertado al inicio (pág. {pn+1}).", item


# ════════════════════════════════════════════════════════════════════════════
# OPERACIÓN: INSERTAR COMPONENTE AL FINAL (antes de End of Report)
# ════════════════════════════════════════════════════════════════════════════

def insert_at_end(doc, layout, comp, font_path=None, font_obj=None):
    """Inserta un componente nuevo como última fila, justo antes de 'End of Report'."""
    ep, eor_y = layout["eor_page"], layout["eor_y"]
    if eor_y is None:
        return False, "No se encontró 'End of Report'."

    # Tope de la última línea de contenido por encima del End of Report
    tops = [s["bbox"][1] for s in _spans(doc[ep]) if s["bbox"][1] < eor_y - 2]
    last_top = max(tops) if tops else layout["sep_y"]
    y_insert = last_top + layout["line_h"]

    n_lines = len(split_description(comp.get("description", ""),
                                    layout["col_w"].get("desc", 14)))
    shift = layout["line_h"] * n_lines

    page_top_last = max((s["bbox"][1] for s in _spans(doc[ep])), default=0)
    if page_top_last + shift + layout["line_h"] > layout["page_height"] + 2:
        return (False, f"Insertar al final desbordaría la página {ep+1} "
                       f"(falta reflujo de página). Abortado.")

    page = _insert_blank_rows(doc, ep, y_insert, shift)
    write_component_fields(page, y_insert, comp, layout, RED, font_path, font_obj)
    return True, f"Componente '{comp.get('item','')}' insertado al final (pág. {ep+1})."


# ════════════════════════════════════════════════════════════════════════════
# OPERACIÓN: EDITAR UN CAMPO DE UN COMPONENTE EXISTENTE (redline)
# ════════════════════════════════════════════════════════════════════════════

# Nombres de campo aceptados (Excel) -> clave de columna del layout
FIELD_ALIASES = {
    "cantidad": "qty", "quantity": "qty", "qty": "qty",
    "rev": "rev", "revision": "rev",
    "uom": "uom", "um": "uom",
    "descripcion": "desc", "descripción": "desc", "description": "desc",
    "status": "status", "item_status": "status", "estado": "status",
    "category": "category", "item_category": "category", "categoria": "category",
    "level": "level", "nivel": "level",
    "op_seq": "op_seq", "item_seq": "item_seq",
}


def _ordered_columns(layout):
    """Lista de (nombre, x) ordenada por X, sin desc_cont."""
    cols = [(c, x) for c, x in layout["col_x"].items() if c != "desc_cont"]
    return sorted(cols, key=lambda t: t[1])


def _field_x_range(layout, field):
    """Rango [x0, x1) horizontal de la columna `field` en la fila."""
    ordered = _ordered_columns(layout)
    for i, (name, x) in enumerate(ordered):
        if name == field:
            x1 = ordered[i + 1][1] if i + 1 < len(ordered) else layout["page_width"]
            return x, x1
    return None, None


def edit_field(doc, layout, item, field, new_value, font_path=None, font_obj=None):
    """Edita un campo de un componente existente: tacha el valor viejo (rojo) y
    escribe el nuevo (rojo) en la misma columna. `field` admite alias en español."""
    key = FIELD_ALIASES.get(str(field).strip().lower())
    if key is None or key not in layout["col_x"]:
        return False, f"Campo '{field}' no reconocido o ausente en este formato."

    occ = find_in_bom_section(doc, layout, item)
    if not occ:
        return False, f"Componente '{item}' no encontrado en la sección del BOM."
    pn, ix0, iy0, ix1, iy1 = occ[0]
    page = doc[pn]
    sz = layout["font_size"]

    # Localizar el valor viejo: palabras en la misma fila, dentro de la columna.
    # Se resta un margen al límite derecho para no capturar la columna vecina.
    fx0, fx1 = _field_x_range(layout, key)
    margin = layout["char_w"] * 0.5
    row_words = [(x0, y0, x1, y1, t) for x0, y0, x1, y1, t, *_ in page.get_text("words")
                 if abs(y0 - iy0) < layout["line_h"] * 0.6 and fx0 - 1 <= x0 < fx1 - margin]
    if not row_words:
        return False, f"No se encontró el valor actual de '{field}' en '{item}'."

    vx0 = min(w[0] for w in row_words)
    vy0 = min(w[1] for w in row_words)
    vx1 = max(w[2] for w in row_words)
    vy1 = max(w[3] for w in row_words)
    old_value = " ".join(w[4] for w in sorted(row_words, key=lambda w: w[0]))

    # Si no se indicó un valor nuevo, se calcula automáticamente a partir del actual.
    # Para `rev` la secuencia es alfabética (A->B->C ... Z->AA); si el valor actual
    # es numérico, next_revision devuelve 'A'.
    if new_value is None or str(new_value).strip() == "":
        if key != "rev":
            return False, (f"'{item}': falta el valor nuevo para '{field}' "
                           f"(solo 'rev' se calcula solo).")
        calculado = next_revision(old_value)
        if calculado is None:
            return False, (f"'{item}': no se pudo calcular la revisión siguiente "
                           f"de '{old_value}'; indícala en el Excel.")
        new_value = calculado

    # 1. tachar viejo (rojo, en su lugar). El rectángulo se ajusta a la caja del
    #    valor sin margen vertical: las filas están separadas por line_h y un
    #    margen mayor borraría texto de la fila vecina.
    page.add_redact_annot(fitz.Rect(vx0 - 0.5, vy0 + 0.3, vx1 + 0.5, vy1 - 0.3), fill=WHITE)
    page.apply_redactions()
    _write(page, vx0, vy0 + sz * 0.85, old_value, sz, RED, font_path, font_obj)
    y_mid = vy0 + (vy1 - vy0) * 0.5
    page.draw_line(fitz.Point(vx0, y_mid), fitz.Point(vx0 + _text_width(old_value, sz), y_mid),
                   color=RED, width=0.7)

    # 2. escribir el nuevo. Para `rev` (valor corto) va AL LADO del tachado, así no
    #    invade la fila de abajo; el resto va debajo. qty se alinea a la derecha.
    new_value = str(new_value)
    if key == "rev":
        nx = vx0 + _text_width(old_value, sz) + 3
        ny = vy0
    else:
        ny = vy0 + layout["line_h"]
        if key == "qty":
            right = layout["col_x"]["qty"] + layout["col_w"].get("qty", 9) * layout["char_w"]
            nx = right - _text_width(new_value, sz)
        else:
            nx = fx0
    _write(page, nx, ny + sz * 0.85, new_value, sz, RED, font_path, font_obj)
    w = _text_width(new_value, sz)
    page.draw_line(fitz.Point(nx, ny + sz * 1.05), fitz.Point(nx + w, ny + sz * 1.05),
                   color=RED, width=0.6)

    return True, f"'{item}': {field} '{old_value}' → '{new_value}' (pág. {pn+1})."


# ════════════════════════════════════════════════════════════════════════════
# POST-PROCESO: CONVERTIR A PÁGINA HORIZONTAL (APAISADA)
# ════════════════════════════════════════════════════════════════════════════

def to_landscape(doc):
    """Devuelve un documento NUEVO con cada página en formato apaisado
    (ancho x alto invertidos), con el contenido centrado y escalado para que
    entre completo y el texto siga legible en horizontal.

    Se aplica al FINAL, después de todas las operaciones de redline.
    """
    out = fitz.open()
    for i in range(len(doc)):
        p = doc[i]
        w, h = p.rect.width, p.rect.height
        lw, lh = h, w                                  # invertir: 612x792 -> 792x612
        new = out.new_page(width=lw, height=lh)
        scale = min(lw / w, lh / h)
        pw, ph = w * scale, h * scale
        x = (lw - pw) / 2
        y = (lh - ph) / 2
        new.show_pdf_page(fitz.Rect(x, y, x + pw, y + ph), doc, i)
    return out
