"""
probar_un_bom.py — Prueba el engine sobre UN BOM.

Requisitos:
  - PyMuPDF instalado:  pip install pymupdf
  - bom_layout.py y bom_engine.py en la misma carpeta que este script.

Uso:
  1. Edita el bloque "CONFIGURA AQUÍ" con tu PDF y los cambios.
  2. Ejecuta:  python probar_un_bom.py
  3. Revisa el PDF de salida y la consola.

Nota: en Windows usará tu Consolas real para el texto rojo (match exacto).
"""

import os
import fitz
from bom_layout import detect_layout, validate_layout
from bom_engine import (update_revision, add_bom_at_start, replace_part,
                        insert_at_end, edit_field)

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURA AQUÍ
# ════════════════════════════════════════════════════════════════════════════
PDF_ENTRADA = "4D-81-584Z-G.pdf"        # nombre del PDF de entrada (Nombre Oracle)
CODIGO_BOM  = "BOM-005379"              # NEW_BOM (se agrega al inicio si no estaba)

ACTUALIZAR_REVISION = True              # 001 -> A, A -> B, ...
AGREGAR_BOM         = True              # agrega el BOM al inicio (si no está ya)

# Reemplazos de componente: lista de (viejo, nuevo)
REEMPLAZOS = [
    ("7H-83-081Z-X", "DWG-COMP-009309"),
]

# Componentes nuevos a agregar al final: lista de dicts (item y description obligatorios)
INSERCIONES = [
    # {"item": "DWG-COMP-009999", "description": "COMPONENTE EJEMPLO", "quantity": "1.00"},
]

# Ediciones de campo de un componente existente: lista de (item, campo, valor_nuevo)
EDICIONES = [
    # ("4D-87-949Z-A", "cantidad", "5.00"),
]
# ════════════════════════════════════════════════════════════════════════════


def procesar(pdf_entrada):
    doc = fitz.open(pdf_entrada)

    layout = detect_layout(doc)
    ok, msg = validate_layout(doc, layout)
    print("Layout:", msg)
    if not ok:
        print("  -> Abortado: el PDF no pasó la validación.")
        return None

    new_rev = None

    # 1) Revisión (da la nueva revisión que necesita el código del BOM)
    if ACTUALIZAR_REVISION:
        ok, msg, old_rev, new_rev = update_revision(doc, layout)
        print(" -", msg)
        layout = detect_layout(doc)

    # 2) Agregar el BOM al inicio (condicional)
    item_bom = None
    if AGREGAR_BOM:
        rev = new_rev or "A"
        ok, msg, item_bom = add_bom_at_start(doc, layout, CODIGO_BOM, rev)
        print(" -", msg)
        layout = detect_layout(doc)

    # 3) Reemplazos de componente
    for viejo, nuevo in REEMPLAZOS:
        ok, msg = replace_part(doc, layout, viejo, nuevo)
        print(" -", msg)
        layout = detect_layout(doc)

    # 4) Ediciones de campo
    for item, campo, valor in EDICIONES:
        ok, msg = edit_field(doc, layout, item, campo, valor)
        print(" -", msg)
        layout = detect_layout(doc)

    # 5) Inserciones al final
    for comp in INSERCIONES:
        ok, msg = insert_at_end(doc, layout, comp)
        print(" -", msg)
        layout = detect_layout(doc)

    # Nombre de salida: entrada + '__' + item del BOM (solo si el código no estaba ya)
    base = os.path.splitext(os.path.basename(pdf_entrada))[0]
    if item_bom and CODIGO_BOM not in base:
        salida = f"{base}__{item_bom}_.pdf"
    else:
        salida = f"{base}__redline.pdf"

    doc.save(salida)
    print("Guardado:", salida)
    return salida


if __name__ == "__main__":
    procesar(PDF_ENTRADA)
