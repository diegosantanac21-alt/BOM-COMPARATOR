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
                        insert_at_end, edit_field, to_landscape)
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


def _output_name(stem, codigo_bom, item_bom):
    """Nombre de salida: entrada + '__' + item del BOM (solo si el código no
    estaba ya en el nombre). Si no se agregó BOM, sufijo '__redline'."""
    if item_bom and (not codigo_bom or codigo_bom.lower() not in stem.lower()):
        return f"{stem}__{item_bom}_.pdf"
    return f"{stem}__redline.pdf"


def process_one(pdf_path, paquete, output_folder):
    """Procesa UN PDF con su paquete de instrucciones. Devuelve dict de resultado."""
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    log = []
    cfg = paquete["config"]

    doc = fitz.open(pdf_path)
    layout = detect_layout(doc)
    ok, msg = validate_layout(doc, layout)
    if not ok:
        return {"archivo": stem, "estado": "ERROR", "detalle": msg, "log": []}
    log.append(f"layout: {msg}")

    new_rev, item_bom = None, None

    # 1) Revisión
    if cfg.get("actualizar_revision", True):
        ok, m, _old, new_rev = update_revision(
            doc, layout, revision_misma_linea=cfg.get("revision_misma_linea", False))
        log.append(m); layout = detect_layout(doc)

    # 2) Agregar BOM al inicio (condicional)
    if cfg.get("agregar_bom", True) and cfg.get("codigo_bom"):
        ok, m, item_bom = add_bom_at_start(
            doc, layout, cfg["codigo_bom"], new_rev or "A",
            rev_bom=cfg.get("rev_bom"))
        log.append(m); layout = detect_layout(doc)

    # 3) Reemplazos de componente
    for old, new in paquete["reemplazos"]:
        ok, m = replace_part(doc, layout, old, new)
        log.append(m); layout = detect_layout(doc)

    # 4) Ediciones de campo
    for item, campo, valor in paquete["ediciones"]:
        ok, m = edit_field(doc, layout, item, campo, valor)
        log.append(m); layout = detect_layout(doc)

    # 5) Inserciones al final
    for comp in paquete["inserciones"]:
        ok, m = insert_at_end(doc, layout, comp)
        log.append(m); layout = detect_layout(doc)

    # Post-proceso opcional: página horizontal (apaisada)
    if cfg.get("pagina_horizontal", False):
        land = to_landscape(doc)
        doc.close()
        doc = land
        log.append("Páginas convertidas a horizontal (apaisado).")

    os.makedirs(output_folder, exist_ok=True)
    out_name = _output_name(stem, cfg.get("codigo_bom"), item_bom)
    out_path = os.path.join(output_folder, out_name)
    doc.save(out_path)
    doc.close()
    return {"archivo": stem, "estado": "OK", "salida": out_name, "log": log}


def run_batch(input_folder, xlsx_path, output_folder):
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
            r = process_one(pdf, paquete, output_folder)
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
