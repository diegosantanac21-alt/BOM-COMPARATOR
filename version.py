"""
version.py — Muestra la versión instalada y verifica que los módulos tengan los
últimos arreglos.

Úsalo cuando dudes si reemplazaste bien los archivos:

    python version.py
"""

import os
import sys

# Marcas que deben existir en cada módulo según la versión. Si falta alguna,
# ese archivo es de una versión anterior.
MARCAS = {
    "bom_layout.py": [
        ("1.4.0", "rev_desc_wrap", "Rev Description según orientación"),
        ("1.4.0", "se elige el renglón con MÁS grupos", "línea de guiones correcta"),
    ],
    "bom_engine.py": [
        ("1.5.1", "def _tol_y", "fix tolerancia vertical (Rev/UOM)"),
        ("1.5.0", "Prioriza las que están en la COLUMNA ITEM", "fix columna item"),
        ("1.4.0", "def set_rev_description", "Rev Description"),
        ("1.4.0", "def _col_bounds", "límites reales de columna"),
        ("1.3.0", "redline=True", "modo limpio"),
        ("1.2.0", "def _fmt_rev_num", "Rev numérica del BOM"),
    ],
    "bom_runner.py": [
        ("1.4.0", "set_rev_description", "Rev Description en Config"),
        ("1.3.0", "_CLEAN_COPY", "copia limpia"),
        ("1.3.0", "_REDLINE.pdf", "nombres nuevos"),
    ],
    "bom_excel.py": [
        ("1.4.0", "rev_description", "columna rev_description"),
        ("1.1.0", "pagina_horizontal", "opciones nuevas"),
    ],
}


def main():
    carpeta = os.path.dirname(os.path.abspath(__file__))

    try:
        sys.path.insert(0, carpeta)
        from bom_layout import __version__, __fecha__
        print("=" * 58)
        print(f" Redline de BOMs — versión {__version__}  ({__fecha__})")
        print("=" * 58)
    except Exception as e:
        print("No se pudo leer la versión:", e)
        return

    problemas = 0
    for archivo, marcas in MARCAS.items():
        ruta = os.path.join(carpeta, archivo)
        if not os.path.exists(ruta):
            print(f"\n[{archivo}]  *** NO ENCONTRADO ***")
            problemas += 1
            continue

        contenido = open(ruta, encoding="utf-8", errors="ignore").read()
        faltan = [(v, d) for v, marca, d in marcas if marca not in contenido]

        if not faltan:
            print(f"\n[{archivo}]  OK — al día")
        else:
            problemas += 1
            print(f"\n[{archivo}]  *** DESACTUALIZADO ***")
            for v, d in faltan:
                print(f"     falta: {d}  (introducido en v{v})")

    print("\n" + "=" * 58)
    if problemas:
        print(f" {problemas} archivo(s) desactualizado(s).")
        print(" Reemplázalos con la versión más reciente y vuelve a probar.")
    else:
        print(" Todos los módulos están al día.")
    print("=" * 58)

    # Recordatorio sobre el ejecutable
    if os.path.exists(os.path.join(carpeta, "dist")):
        print("\nNota: si usas el .exe, recuerda reempaquetarlo tras cambiar los .py:")
        print('   pyinstaller --windowed --name "RedlineBOMs" bom_ui.py')


if __name__ == "__main__":
    main()
