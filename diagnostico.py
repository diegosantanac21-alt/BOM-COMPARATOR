"""
diagnostico.py — Reporta la ESTRUCTURA de un PDF de BOM, sin mostrar su contenido.

Sirve para ajustar la detección cuando un PDF da "Faltan columnas esenciales".
NO imprime part numbers, descripciones ni datos del documento: solo medidas
(tamaños, posiciones, cantidad de columnas) y las ETIQUETAS del encabezado de
la tabla, que son genéricas del reporte de Oracle.

Uso:
    1. Pon este archivo junto a bom_layout.py
    2. Edita PDF abajo con la ruta del PDF problemático
    3. python diagnostico.py
    4. Comparte la salida (son solo números y etiquetas de columna)
"""

import re
import fitz

# ── EDITA ESTA RUTA ─────────────────────────────────────────────────────────
PDF = "archivo_problematico.pdf"
# ────────────────────────────────────────────────────────────────────────────


def spans(page):
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for s in line["spans"]:
                yield s


def main(path):
    doc = fitz.open(path)
    print("=" * 62)
    print("DIAGNÓSTICO DE ESTRUCTURA")
    print("=" * 62)
    print(f"Páginas        : {len(doc)}")
    p0 = doc[0].rect
    print(f"Tamaño pág 1   : {p0.width:.0f} x {p0.height:.0f} "
          f"({'horizontal' if p0.width > p0.height else 'vertical'})")
    print(f"Rotación pág 1 : {doc[0].rotation}")
    print(f"Fuentes pág 1  : {[f[3] for f in doc[0].get_fonts()]}")

    # ¿El texto es extraíble o son glifos sin mapeo?
    txt = doc[0].get_text()
    legible = sum(1 for c in txt if c.isalnum() or c.isspace())
    ratio = legible / len(txt) if txt else 0
    print(f"Texto extraíble: {'SÍ' if ratio > 0.8 else 'NO / parcial'} "
          f"(ratio {ratio:.2f})")

    # ── Línea de guiones (define las columnas) ──────────────────────────────
    print("\n--- LÍNEA DE GUIONES (separador de columnas) ---")
    encontrada = False
    for pn in range(len(doc)):
        for s in spans(doc[pn]):
            t = s["text"]
            if t.count("-") >= 9 and re.search(r"-{5,}", t):
                grupos = re.findall(r"-+", t)
                x0, x1 = s["bbox"][0], s["bbox"][2]
                largo = len(t.rstrip())
                print(f"  Página          : {pn + 1}")
                print(f"  y               : {s['bbox'][1]:.1f}")
                print(f"  x0 / x1         : {x0:.1f} / {x1:.1f}")
                print(f"  Largo (chars)   : {largo}")
                print(f"  char_w calculado: {(x1 - x0) / largo:.3f}"
                      if largo else "  char_w: n/d")
                print(f"  Grupos (columnas detectadas): {len(grupos)}")
                print(f"  Anchos por grupo: {[len(g) for g in grupos]}")
                print(f"  Inicio de cada grupo (char): "
                      f"{[m.start() for m in re.finditer(r'-+', t)]}")
                encontrada = True
                break
        if encontrada:
            break
    if not encontrada:
        print("  *** NO SE ENCONTRÓ la línea de guiones ***")
        print("  (sin ella no se pueden derivar las columnas)")

    # ── Encabezado de columnas (etiquetas genéricas del reporte) ────────────
    print("\n--- ETIQUETAS DEL ENCABEZADO DE LA TABLA ---")
    claves = ("Level", "Item", "Description", "Rev", "UOM", "Quantity",
              "Status", "Category", "Effective", "Disable", "Extended",
              "Onhand", "Seq", "Date", "Time")
    for pn in range(min(3, len(doc))):
        for s in spans(doc[pn]):
            t = s["text"]
            if sum(1 for k in claves if k in t) >= 3:
                print(f"  [pág {pn + 1}] {t.strip()[:120]}")

    # ── Tipografía y espaciado ─────────────────────────────────────────────
    from collections import Counter
    sizes = [round(s["size"], 2) for pn in range(len(doc)) for s in spans(doc[pn])
             if s["text"].strip()]
    print("\n--- TIPOGRAFÍA ---")
    print(f"  Tamaños más comunes: {Counter(sizes).most_common(3)}")

    ys = sorted({round(s["bbox"][1], 2) for s in spans(doc[0])})
    diffs = [round(ys[i + 1] - ys[i], 2) for i in range(len(ys) - 1)]
    diffs = [d for d in diffs if 0 < d < 30]
    print(f"  Espaciado de línea : {Counter(diffs).most_common(3)}")

    # ── End of Report ──────────────────────────────────────────────────────
    print("\n--- 'End of Report' ---")
    hallados = 0
    for pn in range(len(doc)):
        for s in spans(doc[pn]):
            if "End of Report" in s["text"]:
                print(f"  Página {pn + 1}, y={s['bbox'][1]:.1f}")
                hallados += 1
    if not hallados:
        print("  *** NO SE ENCONTRÓ 'End of Report' ***")

    # ── Resultado de la detección real ─────────────────────────────────────
    print("\n--- RESULTADO DE detect_layout / validate_layout ---")
    try:
        from bom_layout import detect_layout, validate_layout
        L = detect_layout(doc)
        ok, msg = validate_layout(doc, L)
        print(f"  Validación: {'OK' if ok else 'FALLA'} -> {msg}")
        if L.get("ok"):
            print(f"  Tipo detectado : {L['report_type']}")
            print(f"  Columnas       : {L['n_columns']}")
            print(f"  char_w / font  : {L['char_w']} / {L['font_size']}")
            print(f"  line_h         : {L['line_h']}")
            print(f"  Columnas mapeadas: "
                  f"{[c for c in L['col_x'] if c != 'desc_cont']}")
    except Exception as e:
        print(f"  ERROR al ejecutar la detección: {e!r}")

    print("\n" + "=" * 62)
    print("Fin del diagnóstico (no se mostró contenido del documento).")


if __name__ == "__main__":
    main(PDF)
