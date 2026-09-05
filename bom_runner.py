"""
bom_runner.py — Capa 4: el motor.

Recorre una carpeta de PDFs, empareja cada uno con sus instrucciones del Excel
(por nombre de archivo), aplica las operaciones en orden y guarda los redlines
en una carpeta de salida.

Uso rápido (editar el bloque CONFIGURA y ejecutar):
    python bom_runner.py

O desde código:
    from bom_runner import run_batch
    run_batch("carpeta_entrada", "plantilla_cambios.xlsx", "carpeta_salida")
"""

import os
import glob
import fitz

from bom_layout import detect_layout, validate_layout
from bom_engine import (update_revision, add_bom_at_start, replace_part,
                        insert_at_end, edit_field, to_landscape, _fmt_rev_num)
from bom_excel import read_instructions


def _match_instructions(stem, instr):
    """Empareja un PDF (por su nombre sin extensión) con su entrada del Excel.
    Primero match exacto; si no, el nombre del Excel contenido en el del archivo."""
    if stem in instr:
        return stem, instr[stem]
    low = stem.lower()
    for naf, paquete in instr.items():
        if naf.lower() == low:
            return naf, paquete
    for naf, paquete in instr.items():
        if naf.lower() in low:                     # p.ej. PDF con sufijos extra
            return naf, paquete
    return None, None


def _output_name(stem, codigo_bom, item_bom, rev_bom=None):
    """Nombre de salida con el formato:  item(BOM)_REVxxx.pdf
    p. ej.  4D-81-584Z-G(BOM-005379)_REV001.pdf

    - `stem` es el item (el nombre del PDF de entrada).
    - El código del BOM va entre paréntesis; si el nombre ya lo contiene, no se
      repite.
    - `rev_bom` es la revisión numérica del BOM (3 dígitos). Si no se indicó,
      se usa 001.
    """
    rev = _fmt_rev_num(rev_bom) if rev_bom else "001"

    if codigo_bom and codigo_bom.lower() not in stem.lower():
        return f"{stem}({codigo_bom})_REV{rev}.pdf"
    return f"{stem}_REV{rev}.pdf"


def process_one(pdf_path, paquete, output_folder, generar_limpio=True):
    """Procesa UN PDF con su paquete de instrucciones. Devuelve dict de resultado."""
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    log = []
    cfg = paquete["config"]

    # Se procesan DOS documentos en paralelo con las mismas operaciones:
    #   doc_r -> versión REDLINE (cambios marcados: tachado + rojo)
    #   doc_c -> versión LIMPIA  (cambios ya aplicados, en negro)
    doc_r = fitz.open(pdf_path)
    doc_c = fitz.open(pdf_path) if generar_limpio else None

    layout = detect_layout(doc_r)
    ok, msg = validate_layout(doc_r, layout)
    if not ok:
        doc_r.close()
        if doc_c: doc_c.close()
        return {"archivo": stem, "estado": "ERROR", "detalle": msg, "log": []}
    log.append(f"layout: {msg}")

    new_rev, item_bom = None, None

    def en_ambos(fn, *args, **kw):
        """Aplica la operación al redline y, si corresponde, al limpio.
        Devuelve el resultado del redline y re-detecta el layout."""
        nonlocal layout
        r = fn(doc_r, layout, *args, redline=True, **kw)
        if doc_c is not None:
            lay_c = detect_layout(doc_c)
            fn(doc_c, lay_c, *args, redline=False, **kw)
        layout = detect_layout(doc_r)
        return r

    # 1) Revisión
    if cfg.get("actualizar_revision", True):
        ok, m, _old, new_rev = en_ambos(
            update_revision,
            revision_misma_linea=cfg.get("revision_misma_linea", False))
        log.append(m)

    # 2) Agregar BOM al inicio (condicional)
    if cfg.get("agregar_bom", True) and cfg.get("codigo_bom"):
        ok, m, item_bom = en_ambos(
            add_bom_at_start, cfg["codigo_bom"], new_rev or "A",
            rev_bom=cfg.get("rev_bom"))
        log.append(m)

    # 3) Reemplazos de componente
    for old, new in paquete["reemplazos"]:
        ok, m = en_ambos(replace_part, old, new)
        log.append(m)

    # 4) Ediciones de campo
    for item, campo, valor in paquete["ediciones"]:
        ok, m = en_ambos(edit_field, item, campo, valor)
        log.append(m)

    # 5) Inserciones al final
    for comp in paquete["inserciones"]:
        ok, m = en_ambos(insert_at_end, comp)
        log.append(m)

    # Post-proceso opcional: página horizontal (apaisada)
    if cfg.get("pagina_horizontal", False):
        land_r = to_landscape(doc_r); doc_r.close(); doc_r = land_r
        if doc_c is not None:
            land_c = to_landscape(doc_c); doc_c.close(); doc_c = land_c
        log.append("Páginas convertidas a horizontal (apaisado).")

    os.makedirs(output_folder, exist_ok=True)
    out_name = _output_name(stem, cfg.get("codigo_bom"), item_bom,
                            cfg.get("rev_bom"))
    doc_r.save(os.path.join(output_folder, out_name))
    doc_r.close()

    salida_limpia = None
    if doc_c is not None:
        salida_limpia = out_name.replace(".pdf", "_LIMPIO.pdf")
        doc_c.save(os.path.join(output_folder, salida_limpia))
        doc_c.close()
        log.append(f"Versión limpia: {salida_limpia}")

    return {"archivo": stem, "estado": "OK", "salida": out_name,
            "salida_limpia": salida_limpia, "log": log}


def run_batch(input_folder, xlsx_path, output_folder, generar_limpio=True):
    """Procesa todos los PDFs de input_folder según xlsx_path. Devuelve resumen."""
    instr = read_instructions(xlsx_path)
    pdfs = sorted(glob.glob(os.path.join(input_folder, "*.pdf"))
                  + glob.glob(os.path.join(input_folder, "*.PDF")))

    resultados, sin_instr, errores = [], [], []
    print(f"PDFs en carpeta: {len(pdfs)} | BOMs en Excel: {len(instr)}\n")

    for pdf in pdfs:
        stem = os.path.splitext(os.path.basename(pdf))[0]
        naf, paquete = _match_instructions(stem, instr)
        if paquete is None:
            sin_instr.append(stem)
            print(f"[—] {stem}: sin instrucciones en el Excel (saltado)")
            continue
        try:
            r = process_one(pdf, paquete, output_folder, generar_limpio)
        except Exception as e:
            r = {"archivo": stem, "estado": "ERROR", "detalle": repr(e), "log": []}
        resultados.append(r)
        if r["estado"] == "OK":
            print(f"[OK] {stem}  ->  {r['salida']}")
            for line in r["log"]:
                print(f"       · {line}")
        else:
            errores.append(r)
            print(f"[ERROR] {stem}: {r.get('detalle','')}")

    # Excel sin PDF correspondiente
    matched = {_match_instructions(os.path.splitext(os.path.basename(p))[0], instr)[0]
               for p in pdfs}
    sin_pdf = [naf for naf in instr if naf not in matched]

    print("\n" + "=" * 60)
    print(f"Procesados OK : {sum(1 for r in resultados if r['estado']=='OK')}")
    print(f"Con error     : {len(errores)}")
    print(f"PDF sin Excel : {len(sin_instr)}  {sin_instr if sin_instr else ''}")
    print(f"Excel sin PDF : {len(sin_pdf)}  {sin_pdf if sin_pdf else ''}")
    return {"resultados": resultados, "sin_instruccion": sin_instr,
            "sin_pdf": sin_pdf, "errores": errores}


# ════════════════════════════════════════════════════════════════════════════
# CONFIGURA AQUÍ y ejecuta:  python bom_runner.py
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    CARPETA_ENTRADA = "entrada"                 # carpeta con los PDFs
    EXCEL           = "plantilla_cambios.xlsx"  # Excel de instrucciones
    CARPETA_SALIDA  = "salida"                   # carpeta donde guardar los redlines

    run_batch(CARPETA_ENTRADA, EXCEL, CARPETA_SALIDA)
