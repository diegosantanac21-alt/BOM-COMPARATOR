#!/usr/bin/env python3
"""
Agrega un sufijo al nombre de los archivos de una carpeta.

Ejemplos:
    # Ver que pasaria (sin renombrar nada)
    python agregar_sufijo.py "C:/Users/Diego/Documentos/fotos" _2026

    # Renombrar de verdad
    python agregar_sufijo.py "C:/Users/Diego/Documentos/fotos" _2026 --aplicar

    # Solo los .pdf
    python agregar_sufijo.py ./carpeta _final --ext .pdf --aplicar

    # Poner el texto al inicio en vez de al final
    python agregar_sufijo.py ./carpeta "borrador_" --prefijo --aplicar
"""

import argparse
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description="Agrega un sufijo a los nombres de archivo de una carpeta.")
    p.add_argument("carpeta", help="Ruta de la carpeta")
    p.add_argument("sufijo", help="Texto a agregar, ej: _v2")
    p.add_argument("--ext", default=None, help="Filtrar por extension, ej: .jpg")
    p.add_argument("--prefijo", action="store_true", help="Agregar al inicio en lugar del final")
    p.add_argument("--recursivo", action="store_true", help="Incluir subcarpetas")
    p.add_argument("--aplicar", action="store_true", help="Renombrar de verdad (por defecto solo simula)")
    args = p.parse_args()

    carpeta = Path(args.carpeta).expanduser()
    if not carpeta.is_dir():
        raise SystemExit(f"No existe la carpeta: {carpeta}")

    patron = "**/*" if args.recursivo else "*"
    archivos = sorted(f for f in carpeta.glob(patron) if f.is_file())

    if args.ext:
        ext = args.ext if args.ext.startswith(".") else "." + args.ext
        archivos = [f for f in archivos if f.suffix.lower() == ext.lower()]

    cambios = 0
    for f in archivos:
        # f.stem = nombre sin extension, f.suffix = ".txt"
        nuevo_nombre = (args.sufijo + f.stem if args.prefijo else f.stem + args.sufijo) + f.suffix
        destino = f.with_name(nuevo_nombre)

        if destino == f:
            continue
        if destino.exists():
            print(f"OMITIDO (ya existe): {destino.name}")
            continue

        print(f"{f.name}  ->  {destino.name}")
        if args.aplicar:
            f.rename(destino)
        cambios += 1

    print(f"\n{cambios} archivo(s) {'renombrados' if args.aplicar else 'se renombrarian'}.")
    if not args.aplicar and cambios:
        print("Agrega --aplicar para hacerlo de verdad.")


if __name__ == "__main__":
    main()
