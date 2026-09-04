"""
bom_ui.py — Interfaz de escritorio para la herramienta de redline de BOMs.

Permite a cualquiera (sin VSCode) procesar una carpeta de BOMs:
  1. Elige la carpeta con los PDFs de entrada.
  2. Elige el Excel de instrucciones (plantilla_cambios.xlsx).
  3. Elige la carpeta de salida.
  4. Clic en "Procesar".

Requiere (solo para desarrollar/empaquetar): bom_layout.py, bom_engine.py,
bom_excel.py, bom_runner.py en la misma carpeta, y PyMuPDF + openpyxl.
Para los usuarios finales se distribuye como .exe (ver instrucciones de empaquetado).
"""

import os
import sys
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from bom_runner import run_batch


class _QueueWriter:
    """Captura lo que se imprime (print) y lo manda a una cola para mostrarlo."""
    def __init__(self, q):
        self.q = q
    def write(self, text):
        if text:
            self.q.put(text)
    def flush(self):
        pass


class RedlineApp:
    def __init__(self, root):
        self.root = root
        root.title("Redline de BOMs")
        root.geometry("720x520")
        root.minsize(620, 460)

        self.var_in = tk.StringVar()
        self.var_xlsx = tk.StringVar()
        self.var_out = tk.StringVar()
        self.log_q = queue.Queue()
        self.worker = None

        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(root, padding=14)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Procesador de redline de BOMs",
                  font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=3,
                                                       sticky="w", pady=(0, 10))

        # Fila: carpeta de entrada
        ttk.Label(frm, text="Carpeta de PDFs:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.var_in).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Examinar…",
                   command=lambda: self._pick_folder(self.var_in)).grid(row=1, column=2, **pad)

        # Fila: Excel
        ttk.Label(frm, text="Excel de cambios:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.var_xlsx).grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Examinar…",
                   command=self._pick_xlsx).grid(row=2, column=2, **pad)

        # Fila: carpeta de salida
        ttk.Label(frm, text="Carpeta de salida:").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.var_out).grid(row=3, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Examinar…",
                   command=lambda: self._pick_folder(self.var_out)).grid(row=3, column=2, **pad)

        # Botón procesar + barra de progreso
        self.btn = ttk.Button(frm, text="Procesar", command=self.procesar)
        self.btn.grid(row=4, column=0, sticky="w", **pad)
        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.grid(row=4, column=1, columnspan=2, sticky="ew", **pad)

        # Área de log
        ttk.Label(frm, text="Resultado:").grid(row=5, column=0, sticky="w", padx=10)
        self.log = tk.Text(frm, height=15, wrap="word", state="disabled",
                           font=("Consolas", 9), background="#1e1e1e", foreground="#e0e0e0")
        self.log.grid(row=6, column=0, columnspan=3, sticky="nsew", padx=10, pady=(2, 8))
        frm.rowconfigure(6, weight=1)
        sb = ttk.Scrollbar(frm, command=self.log.yview)
        sb.grid(row=6, column=3, sticky="ns")
        self.log["yscrollcommand"] = sb.set

        self.root.after(120, self._poll_log)

    # ── Selectores ───────────────────────────────────────────────────────────
    def _pick_folder(self, var):
        d = filedialog.askdirectory(title="Selecciona la carpeta")
        if d:
            var.set(d)

    def _pick_xlsx(self):
        f = filedialog.askopenfilename(title="Selecciona el Excel",
                                       filetypes=[("Excel", "*.xlsx *.xlsm"), ("Todos", "*.*")])
        if f:
            self.var_xlsx.set(f)

    # ── Log ────────────────────────────────────────────────────────────────
    def _append(self, text):
        self.log["state"] = "normal"
        self.log.insert("end", text)
        self.log.see("end")
        self.log["state"] = "disabled"

    def _poll_log(self):
        try:
            while True:
                self._append(self.log_q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._poll_log)

    # ── Procesar ─────────────────────────────────────────────────────────────
    def procesar(self):
        carpeta_in = self.var_in.get().strip()
        xlsx = self.var_xlsx.get().strip()
        carpeta_out = self.var_out.get().strip()

        if not os.path.isdir(carpeta_in):
            return messagebox.showerror("Falta dato", "Elige una carpeta de PDFs válida.")
        if not os.path.isfile(xlsx):
            return messagebox.showerror("Falta dato", "Elige un archivo Excel válido.")
        if not carpeta_out:
            return messagebox.showerror("Falta dato", "Elige una carpeta de salida.")

        self.log["state"] = "normal"; self.log.delete("1.0", "end"); self.log["state"] = "disabled"
        self.btn["state"] = "disabled"
        self.progress.start(12)

        self.worker = threading.Thread(
            target=self._run, args=(carpeta_in, xlsx, carpeta_out), daemon=True)
        self.worker.start()

    def _run(self, carpeta_in, xlsx, carpeta_out):
        old_stdout = sys.stdout
        sys.stdout = _QueueWriter(self.log_q)
        try:
            run_batch(carpeta_in, xlsx, carpeta_out)
        except Exception as e:
            self.log_q.put(f"\nERROR: {e!r}\n")
        finally:
            sys.stdout = old_stdout
            self.root.after(0, self._done)

    def _done(self):
        self.progress.stop()
        self.btn["state"] = "normal"
        messagebox.showinfo("Listo", "Proceso terminado. Revisa el resultado y la carpeta de salida.")


if __name__ == "__main__":
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")   # apariencia un poco más limpia
    except Exception:
        pass
    RedlineApp(root)
    root.mainloop()
