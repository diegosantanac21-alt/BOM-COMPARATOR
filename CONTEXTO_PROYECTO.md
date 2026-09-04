# Contexto del proyecto — Herramienta de redline para BOMs (Oracle EBS)

> Documento de traspaso. Léelo junto con los archivos de código (`bom_layout.py`,
> `bom_engine.py`, `probar_un_bom.py`) y la plantilla `plantilla_cambios.xlsx`.
> Con esto se puede continuar el desarrollo sin perder contexto.

## 1. Objetivo

Herramienta en **Python (PyMuPDF / fitz)** que procesa en **lote** una carpeta de
PDFs de BOM generados por Oracle EBS ("Bill of Material Structure Report") y les
aplica marcas de **redline** (control de cambios de ingeniería), guiándose por un
**Excel** de instrucciones. Hoy se corre como script en VSCode; el objetivo final
es una mini-UI (probablemente Streamlit).

## 2. Formato de los PDFs (clave para todo)

- Reporte de Oracle, texto **monoespaciado** en fuente **Consolas embebida**.
- La tabla de componentes NO tiene columnas como objetos separados: **cada fila es
  un solo span** de texto; las columnas se alinean con espacios.
- Las **columnas se derivan de la línea de guiones** (`--------- ---- ----...`) que
  Oracle imprime sobre los componentes: cada grupo de guiones marca el inicio y
  ancho exacto de una columna.
- Hay **dos formatos** confirmados:
  - **Inventory**: 10 columnas (`level, op_seq, item_seq, item, desc, rev, uom,
    qty, status, category`), fuente 9.75pt, line_h 11.25.
  - **Engineering**: 14 columnas (`...qty, eff_date, eff_time, dis_date, dis_time,
    ext_qty, onhand`), fuente 7.31pt, line_h 8.44. Además trae un segundo reporte
    (Routing) en páginas posteriores.
- Las primeras 8 columnas (`level`..`qty`) son **idénticas** en ambos formatos; las
  siguientes cambian. Por eso las columnas se **etiquetan por tipo de reporte**.
- Un PDF puede contener **varios reportes** y **varios "End of Report"**. Todas las
  operaciones se limitan a la **sección del BOM**: desde la línea de guiones hasta
  el **primer** "End of Report".

### Aprendizaje técnico crítico: el ancho de carácter
El ancho de carácter real del Consolas del PDF **NO es el de Courier**. Hay que
**medirlo** del propio ancho de la línea de guiones:
`char_w = (x1_del_span_guiones - x0) / len(texto_guiones)`.
Da ~**5.36** (Inventory 9.75pt) y ~**4.02** (Engineering 7.31pt). Usar el de Courier
(5.85) desalinea el texto nuevo con un desfase que **crece** con la posición X.

## 3. Convención de redline (todo en ROJO)

- Lo que se **agrega** (nuevo) → texto en rojo (subrayado).
- Lo que se **elimina** (viejo) → texto tachado (strikethrough) en rojo.

### Aprendizaje técnico: la fuente del texto nuevo
- NO usar el font subset embebido para texto nuevo: corrompe los glifos.
- `page.insert_text(..., fontfile=...)` también corrompe (offset de codificación).
- **Usar `fitz.TextWriter`** con un `fitz.Font(fontfile=...)`: renderiza bien.
- Resolución de fuente: **Consolas** (p.ej. `C:/Windows/Fonts/consola.ttf` en Windows
  → match exacto, ancho 0.55em = 5.36 a 9.75pt) > **DejaVu Sans Mono** (Linux, muy
  parecido) > **Courier** interno (`fitz.Font("cour")`, siempre disponible).

## 4. Arquitectura en 4 capas

1. **`bom_layout.py` (base)** — `detect_layout(doc)` mide font, line_h, char_w real,
   columnas por etiqueta y posiciones clave (sección BOM, End of Report).
   `validate_layout(doc, layout)` es **estricta**: aborta con mensaje si falta lo
   esencial. `would_overflow(...)` es red de seguridad.  **[HECHO y validado]**
2. **`bom_engine.py` (operaciones)** — una función independiente por operación,
   recibe `(doc, layout, datos)`. No sabe del Excel ni de carpetas.  **[HECHO y validado]**
3. **`bom_excel.py` (lectura del Excel)** — lee las 4 hojas y arma, por
   `nombre_archivo`, su lista de instrucciones.  **[PENDIENTE]**
4. **`bom_runner.py` (el motor)** — recorre la carpeta, empareja cada PDF con sus
   instrucciones, aplica las operaciones en orden y guarda la salida.  **[PENDIENTE]**

UI (Streamlit) va **encima** del motor.  **[PENDIENTE, después del runner]**

## 5. Operaciones (capa 2, ya implementadas)

Todas marcan en rojo y se limitan a la sección del BOM.

- **`replace_part(doc, layout, old, new)`** — tacha el código viejo en su lugar y
  escribe el nuevo debajo, en la columna `item`, subrayado.
- **`update_revision(doc, layout)`** — detecta la revisión actual y la sube
  (`001`→`A`, `A`→`B`, `Z`→`AA`). Tacha la vieja, escribe la nueva al lado.
  Devuelve `(ok, msg, old_rev, new_rev)`. Actualiza todas sus apariciones (bloque
  de parámetros + header por página).
- **`add_bom_at_start(doc, layout, bom_code, new_rev)`** — **condicional**: solo si
  el BOM **no estaba ya** como componente. Item insertado = `bom_code` + `_R` +
  revisión nueva (ej. `BOM-005379_RA`). Descripción = `BOM FOR ` + la descripción
  del ensamblaje **leída del header** del PDF. Devuelve `(ok, msg, item)`.
- **`insert_at_end(doc, layout, comp)`** — agrega un componente nuevo como última
  fila, antes de "End of Report". `comp` es un dict (item y description obligatorios).
- **`edit_field(doc, layout, item, campo, valor_nuevo)`** — edita un campo de un
  componente existente (ej. `cantidad`, `rev`, `uom`). Tacha el valor viejo, escribe
  el nuevo. `campo` admite alias en español (ver `FIELD_ALIASES`).

### Detalles de implementación
- Inserciones/overflow: se usa una técnica de **partir la página** (top intacto +
  bottom desplazado con `show_pdf_page`). Si el desplazamiento empujaría contenido
  fuera de la página física, **aborta** con mensaje (red de seguridad **Nivel 1**;
  el reflujo a la página siguiente = **Nivel 2**, pendiente). Criterio de overflow:
  una línea se pierde solo si su **tope** se sale tras el shift (la hoja se usa
  completa, hasta ~792pt, no se reserva margen inferior).
- **Orden y re-detección**: las operaciones que insertan filas mueven las posiciones
  de la página, así que en el script se **re-detecta el layout entre operaciones**.

## 6. Estructura del Excel (plantilla limpia propuesta)

El Excel original del cliente (`cambios.xlsx`) mezclaba todo; se rediseñó en 4 hojas
(ver `plantilla_cambios.xlsx`), todas cruzadas por `nombre_archivo`:

- **Config**: `nombre_archivo | codigo_bom | agregar_bom | actualizar_revision`
- **Reemplazos**: `nombre_archivo | componente_actual | componente_nuevo`
- **Inserciones**: `nombre_archivo | item | descripcion | cantidad | uom | rev |
  level | op_seq | item_seq | item_status | item_category`
- **Ediciones**: `nombre_archivo | item | campo | valor_nuevo`

### Mapeo desde el Excel original del cliente
- `Nombre Oracle` (ej. `4D-81-584Z-G`) = **nombre del archivo de entrada** y clave de
  emparejamiento. NO se escribe en el PDF. (Conceptualmente = "Nombre archivo".)
- `NEW_BOM` (ej. `BOM-005379`) = código del BOM → item insertado + nombre de salida.
- `COMPONENT_ITEM` → componente que se tacha (viejo).
- `New component` → componente que se agrega (nuevo).
- `ANTERIOR` y `Nombre Oscor` = **referencia, NO se usan** en el proceso.

## 7. Flujo batch y nombres de archivo

- Entrada: carpeta de PDFs, cada uno nombrado por `Nombre Oracle` (ej.
  `4D-81-584Z-G.pdf`).
- Se empareja cada PDF con su(s) fila(s) del Excel por ese nombre.
- Por cada BOM se aplican (en orden sensato): revisión → agregar BOM (condicional)
  → reemplazos → ediciones → inserciones. Re-detectar layout entre las que insertan.
- Salida: `NombreOracle` + `__` + `item_insertado` + `_.pdf`
  (ej. `4D-81-584Z-G__BOM-005379_RA_.pdf`). El código del BOM se agrega al nombre
  solo si **no estaba ya** en él.

### Ejemplo real validado (antes/después)
- Entrada `4D-81-584Z-G.pdf`, fila del Excel: `NEW_BOM=BOM-005379`,
  `COMPONENT_ITEM=7H-83-081Z-X`, `New component=DWG-COMP-009309`.
- Resultado: revisión `001`→`A`; insertado `BOM-005379_RA` (desc
  "BOM FOR ADELANTE 9.5F PEELAWAY S16CM D19CM (P)"); reemplazo
  `7H-83-081Z-X`→`DWG-COMP-009309`. Reproducido por el engine de forma idéntica.

## 8. Estado actual y próximos pasos

- **HECHO**: capa 1 (`bom_layout.py`) y capa 2 (`bom_engine.py`), validadas contra
  PDFs reales y los dos formatos. Script de prueba `probar_un_bom.py`.
- **PENDIENTE**:
  1. `bom_excel.py` — lector de las 4 hojas.
  2. `bom_runner.py` — el motor batch (carpeta + emparejamiento + orden + guardado).
  3. UI mínima (Streamlit) envolviendo el motor.
  4. (Opcional) Reflujo de página Nivel 2 para BOMs que desbordan al insertar.

## 9. Notas / gotchas para quien continúe

- Validación estricta: ante un formato desconocido, **abortar con mensaje**, no
  generar algo mal alineado.
- No perder contenido en silencio: si un insert desborda, abortar (Nivel 1).
- El texto nuevo se escribe con `TextWriter` + fuente mono resuelta (Consolas/DejaVu/
  Courier). En Windows del cliente, Consolas da match exacto.
- Las columnas y posiciones SIEMPRE salen de `detect_layout` (nada hardcodeado).
- `find_in_bom_section` ignora otros reportes del PDF (p.ej. Routing).
