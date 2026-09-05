# ============================================================================
#  DIAGNOSTICO — Prueba paso a paso el flujo de extraccion e impresion en Edge.
#
#  Se ejecuta sobre UNA sola pestaña (la que tengas activa) y va reportando
#  que funciona y que no, deteniendose en cada etapa para que puedas ver
#  lo que pasa en pantalla.
#
#  USO:
#    1. Abre en Edge la pestaña de un BOM.
#    2. Ejecuta:  .\diagnostico_edge.ps1
#    3. Comparte la salida.
# ============================================================================

Add-Type -AssemblyName System.Windows.Forms
$shell = New-Object -ComObject WScript.Shell

$carpeta = "C:\PDFs"
if (!(Test-Path $carpeta)) { New-Item -ItemType Directory -Path $carpeta | Out-Null }

function Tecla($k) { [System.Windows.Forms.SendKeys]::SendWait($k) }
function Pausa($ms) { Start-Sleep -Milliseconds $ms }

function Titulo($t) {
    Write-Host ""
    Write-Host "=== $t ===" -ForegroundColor Cyan
}

function OK($m)    { Write-Host "  [OK]    $m" -ForegroundColor Green }
function FALLA($m) { Write-Host "  [FALLA] $m" -ForegroundColor Red }
function INFO($m)  { Write-Host "  [info]  $m" -ForegroundColor Gray }

Write-Host "============================================================"
Write-Host " DIAGNOSTICO DE IMPRESION EDGE -> PDF"
Write-Host "============================================================"

# ── 0) Entorno ──────────────────────────────────────────────────────────────
Titulo "0. ENTORNO"
INFO "PowerShell version : $($PSVersionTable.PSVersion)"
INFO "Idioma del sistema : $((Get-Culture).Name)"
INFO "Carpeta destino    : $carpeta"
$edge = Get-Process msedge -ErrorAction SilentlyContinue
if ($edge) { OK "Edge esta abierto ($($edge.Count) procesos)" }
else { FALLA "Edge NO parece estar abierto" }

# ── 1) Enfocar Edge ─────────────────────────────────────────────────────────
Titulo "1. ENFOCAR EDGE"
$foco = $shell.AppActivate("Edge")
if ($foco) { OK "Se enfoco Edge con AppActivate('Edge')" }
else {
    FALLA "No se pudo enfocar con 'Edge'. Probando por proceso..."
    if ($edge) {
        $foco = $shell.AppActivate($edge[0].Id)
        if ($foco) { OK "Se enfoco por Id de proceso" } else { FALLA "Tampoco por Id" }
    }
}
Pausa 800

# ── 2) Titulo de la ventana activa ──────────────────────────────────────────
Titulo "2. TITULO DE LA VENTANA"
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Win {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
}
"@ -ErrorAction SilentlyContinue

$sb = New-Object System.Text.StringBuilder 512
[Win]::GetWindowText([Win]::GetForegroundWindow(), $sb, 512) | Out-Null
INFO "Ventana activa: '$($sb.ToString())'"

# ── 3) Consola de DevTools y extraccion del nombre ──────────────────────────
Titulo "3. EXTRACCION DEL NOMBRE (DevTools)"
$jsCode = 'copy((document.body.innerText.match(/item:\s*(\S+)/i)||["","sin_nombre"])[1].trim())'

INFO "Abriendo DevTools (Ctrl+Shift+J)..."
Tecla "^+j"
Pausa 2000

INFO "Enviando 'allow pasting'..."
Set-Clipboard -Value "allow pasting"
Pausa 300
Tecla "^v"; Pausa 300; Tecla "{ENTER}"
Pausa 800

INFO "Limpiando portapapeles..."
Set-Clipboard -Value ""
Pausa 300
$antes = Get-Clipboard
INFO "Portapapeles antes: '$antes'"

INFO "Ejecutando el JS de extraccion..."
Set-Clipboard -Value $jsCode
Pausa 300
Tecla "^v"; Pausa 400; Tecla "{ENTER}"
Pausa 1200

$nombre = Get-Clipboard
if ([string]::IsNullOrWhiteSpace($nombre)) {
    FALLA "El portapapeles quedo VACIO -> copy() no funciono"
    INFO "Posibles causas: DevTools no tenia foco, o el 'allow pasting' no se acepto"
} elseif ($nombre -eq $jsCode) {
    FALLA "El portapapeles tiene el propio codigo JS -> no se ejecuto"
} elseif ($nombre -eq "sin_nombre") {
    FALLA "El regex NO encontro 'Item:' en la pagina"
    INFO "Revisa que la pestaña activa sea realmente un BOM"
} else {
    OK "Nombre extraido: '$nombre'"
}

INFO "Cerrando DevTools..."
Tecla "^+j"
Pausa 1000

if ([string]::IsNullOrWhiteSpace($nombre) -or $nombre -eq $jsCode) {
    $nombre = "PRUEBA_DIAGNOSTICO"
    INFO "Se usara '$nombre' para seguir probando la impresion"
}
$nombre = ($nombre -replace '[\\/:*?"<>|]', '_').Trim()
$destino = Join-Path $carpeta "$nombre.pdf"
if (Test-Path $destino) { Remove-Item $destino -Force; INFO "Se borro un archivo previo con ese nombre" }

# ── 4) Dialogo de impresion ─────────────────────────────────────────────────
Titulo "4. DIALOGO DE IMPRESION"
INFO "Abriendo Ctrl+P..."
Tecla "^p"
Pausa 2500

$sb2 = New-Object System.Text.StringBuilder 512
[Win]::GetWindowText([Win]::GetForegroundWindow(), $sb2, 512) | Out-Null
INFO "Ventana tras Ctrl+P: '$($sb2.ToString())'"

INFO "Enviando Alt+S (boton Guardar)..."
Tecla "%s"
Pausa 1500

# ── 5) Dialogo Guardar como ─────────────────────────────────────────────────
Titulo "5. DIALOGO 'GUARDAR COMO'"
$titulos = @("Guardar como","Save As","Guardar","Save")
$enfocado = $false
$cual = ""
foreach ($t in $titulos) {
    if ($shell.AppActivate($t)) { $enfocado = $true; $cual = $t; break }
    Pausa 300
}
if ($enfocado) { OK "Dialogo enfocado con el titulo: '$cual'" }
else { FALLA "No se pudo enfocar el dialogo con ninguno de: $($titulos -join ', ')" }

$sb3 = New-Object System.Text.StringBuilder 512
[Win]::GetWindowText([Win]::GetForegroundWindow(), $sb3, 512) | Out-Null
INFO "Ventana activa ahora: '$($sb3.ToString())'"

Pausa 1000

# ── 6) Reemplazar el nombre ─────────────────────────────────────────────────
Titulo "6. ESCRIBIR EL NOMBRE"
INFO "Alt+N (enfocar campo nombre)..."
Tecla "%n"
Pausa 500
INFO "Ctrl+A + DEL (borrar lo sugerido)..."
Tecla "^a"; Pausa 300; Tecla "{DEL}"
Pausa 400
INFO "Pegando: $destino"
Set-Clipboard -Value $destino
Pausa 400
Tecla "^v"
Pausa 600
Tecla "{ENTER}"
Pausa 2000

# ── 7) Verificacion ─────────────────────────────────────────────────────────
Titulo "7. VERIFICACION"
$creado = $false
for ($t = 0; $t -lt 12; $t++) {
    if (Test-Path $destino) { $creado = $true; break }
    Pausa 500
}

if ($creado) {
    $f = Get-Item $destino
    OK "Archivo creado: $($f.Name)  ($([math]::Round($f.Length/1KB,1)) KB)"
} else {
    FALLA "No se creo: $destino"
    INFO "Archivos PDF mas recientes en la carpeta:"
    Get-ChildItem $carpeta -Filter *.pdf -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 5 |
        ForEach-Object { INFO "   $($_.Name)  ($($_.LastWriteTime))" }
    INFO "Si aparece uno con OTRO nombre, el problema es el paso 6 (no se reemplazo el nombre)"
}

Write-Host ""
Write-Host "============================================================"
Write-Host " FIN DEL DIAGNOSTICO"
Write-Host "============================================================"
