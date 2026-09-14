"""
diagnostico_split.py — Analiza la ESTRUCTURA de un reporte consolidado de BOMs
(varios BOMs en un solo PDF) para poder adaptar el splitter.

NO muestra el contenido del documento: solo posiciones, conteos y las etiquetas
genéricas del reporte de Oracle. Los códigos de item se muestran ENMASCARADOS
(p. ej. 4D-81-584Z-G -> 4D-XX-XXXX-X) para no exponer datos.

Uso:
    1. Guarda este archivo junto al reporte.
    2. Edita PDF con la ruta del reporte consolidado.
    3. python diagnostico_split.py
    4. Comparte la salida.
"""

import re
import fitz

# ── EDITA ESTA RUTA ─────────────────────────────────────────────────────────
PDF = "reporte_consolidado.pdf"
# ────────────────────────────────────────────────────────────────────────────

# Patrón general de códigos Oracle: 2 caracteres, guion, y el resto
ITEM_RE = re.compile(r"\bItem:\s*([A-Z0-9]{2,4}-[A-Z0-9-]{4,})", re.I)


def enmascarar(codigo):
    """4D-81-584Z-G -> 4D-XX-XXXX-X   (conserva la forma, oculta el dato)."""
    partes = codigo.split("-")
    out = [partes[0]]
    for p in partes[1:]:
        out.append("X" * len(p))
    return "-".join(out)


def spans(page):
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for s in line["spans"]:
                yield s


def lineas_por_y(page):
    por_y = {}
    for s in spans(page):
        por_y.setdefault(round(s["bbox"][1], 1), []).append(s)
    return por_y


def main(path):
    doc = fitz.open(path)
    print("=" * 64)
    print(" DIAGNÓSTICO DE REPORTE CONSOLIDADO")
    print("=" * 64)
    print(f"Páginas        : {len(doc)}")
    r = doc[0].rect
    print(f"Tamaño pág 1   : {r.width:.0f} x {r.height:.0f} "
          f"({'horizontal' if r.width > r.height else 'vertical'})")
    print(f"Rotación       : {doc[0].rotation}")
    print(f"Fuentes        : {[f[3] for f in doc[0].get_fonts()]}")

    # ── Dónde empieza cada BOM ('Item:') ────────────────────────────────────
    print("\n--- INICIO DE CADA BOM ('Item:') ---")
    marcas = []
    for pn in range(len(doc)):
        for y, ss in sorted(lineas_por_y(doc[pn]).items()):
            texto = "".join(s["text"] for s in sorted(ss, key=lambda s: s["bbox"][0]))
            m = ITEM_RE.search(texto)
            if m:
                x0 = min(s["bbox"][0] for s in ss)
                marcas.append((pn, y, m.group(1), x0))
    if marcas:
        print(f"  Total de marcas 'Item:' encontradas: {len(marcas)}")
        for pn, y, cod, x0 in marcas[:12]:
            print(f"    pág {pn+1:3d}  y={y:7.1f}  x={x0:6.1f}  {enmascarar(cod)}")
        if len(marcas) > 12:
            print(f"    ... y {len(marcas)-12} más")
        únicos = {enmascarar(c) for _, _, c, _ in marcas}
        print(f"  Formas de código distintas: {len(únicos)} -> {sorted(únicos)[:8]}")
    else:
        print("  *** No se encontró ninguna marca 'Item:' ***")
        print("  (el patrón de código puede ser distinto al esperado)")

    # ── Separadores de tabla ────────────────────────────────────────────────
    print("\n--- LÍNEAS DE GUIONES (una por tabla de componentes) ---")
    seps = []
    for pn in range(len(doc)):
        for y, ss in sorted(lineas_por_y(doc[pn]).items()):
            t = "".join(s["text"] for s in sorted(ss, key=lambda s: s["bbox"][0]))
            if t.count("-") >= 9 and re.search(r"-{5,}", t):
                seps.append((pn, y, len(re.findall(r"-+", t))))
    print(f"  Total: {len(seps)}")
    for pn, y, g in seps[:8]:
        print(f"    pág {pn+1:3d}  y={y:7.1f}  grupos={g}")
    if len(seps) > 8:
        print(f"    ... y {len(seps)-8} más")

    # ── End of Report ───────────────────────────────────────────────────────
    print("\n--- 'End of Report' ---")
    eor = [(pn, s["bbox"][1]) for pn in range(len(doc))
           for s in spans(doc[pn]) if "End of Report" in s["text"]]
    print(f"  Total: {len(eor)}")
    for pn, y in eor[:5]:
        print(f"    pág {pn+1}  y={y:.1f}")

    # ── Qué hay en la PORTADA (pág 1) ───────────────────────────────────────
    print("\n--- ETIQUETAS DE LA PORTADA (pág 1) ---")
    etiquetas = ("Organization", "Item Selection", "Alternate", "Revision",
                 "Date", "Category Set", "Level to Explode", "Implemented Only",
                 "Display Option", "Explosion Quantity", "Show Full Description",
                 "Component Item Detail", "Order By", "Report Date", "Page")
    for y, ss in sorted(lineas_por_y(doc[0]).items()):
        t = "".join(s["text"] for s in sorted(ss, key=lambda s: s["bbox"][0]))
        if any(e in t for e in etiquetas):
            x0 = min(s["bbox"][0] for s in ss)
            # ocultar valores que parezcan códigos
            t_safe = ITEM_RE.sub(lambda m: f"Item: {enmascarar(m.group(1))}", t)
            print(f"    y={y:7.1f} x={x0:6.1f}: {t_safe.strip()[:95]}")

    # ── Encabezado PARCIAL de un BOM que no sea el primero ──────────────────
    if len(marcas) > 1:
        pn, y, cod, _ = marcas[1]
        print(f"\n--- ENCABEZADO DEL 2º BOM (pág {pn+1}, y={y:.1f}) ---")
        print("   (para ver qué datos trae y cuáles faltan)")
        for yy, ss in sorted(lineas_por_y(doc[pn]).items()):
            if y - 60 <= yy <= y + 70:
                t = "".join(s["text"] for s in sorted(ss, key=lambda s: s["bbox"][0]))
                if not t.strip():
                    continue
                x0 = min(s["bbox"][0] for s in ss)
                t_safe = ITEM_RE.sub(lambda m: f"Item: {enmascarar(m.group(1))}", t)
                print(f"    y={yy:7.1f} x={x0:6.1f}: {t_safe.strip()[:95]}")

    print("\n" + "=" * 64)
    print(" Fin (no se mostró contenido del documento).")


if __name__ == "__main__":
    main(PDF)
