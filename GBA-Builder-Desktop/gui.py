"""
gui.py - the desktop window (Tkinter, ships with Python, works fully offline)

Thin on purpose: everything that actually builds lives in engine.py.
Layout:  [builder picker]  ->  scrolling steps (1 games, 2 emulator/extras,
3 options)  ->  fixed bottom bar (save-to folder, Build button, log).
"""

import os
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import engine
from builder_core import BUILDERS, ApiError, human_size

WRAP = 700


class ScrollFrame(ttk.Frame):
    """A vertically scrolling container. Put widgets into .inner"""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._wheel)

    def _wheel(self, event):
        w = self.winfo_containing(event.x_root, event.y_root)
        if w is None or not str(w).startswith(str(self)):
            return
        if w.winfo_class() in ("Listbox", "Text"):
            return
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("GBA Compilation Builder")
        self.root.geometry("880x800")
        self.root.minsize(780, 620)

        self.q = queue.Queue()
        self.busy = False
        self.builder = None
        self.roms = []                 # game paths, in menu order
        self.extra_paths = {}          # role -> [paths]
        self.extra_vars = {}           # role -> StringVar shown in the entry
        self.flag_vars = {}            # flag -> BooleanVar
        self.emu_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.dest_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Pick a builder, add your games, then press Build.")

        self._build_frame()
        self.select_builder(0)
        self.root.after(100, self._poll)

    # ------------------------------------------------------------------ frame

    def _build_frame(self):
        top = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        top.pack(fill="x")
        ttk.Label(top, text="GBA Compilation Builder",
                  font=("Segoe UI", 15, "bold")).pack(anchor="w")
        row = ttk.Frame(top)
        row.pack(fill="x", pady=(6, 2))
        ttk.Label(row, text="Which console are your games for?").pack(side="left")
        self.combo = ttk.Combobox(
            row, state="readonly", width=52,
            values=[f"{b['name']}  -  {b['system']}" for b in BUILDERS])
        self.combo.pack(side="left", padx=8)
        self.combo.current(0)
        self.combo.bind("<<ComboboxSelected>>",
                        lambda e: self.select_builder(self.combo.current()))
        self.desc = ttk.Label(top, wraplength=WRAP + 60, justify="left")
        self.desc.pack(anchor="w", pady=(2, 0))

        # bottom bar first so it keeps its space when the window is short
        bottom = ttk.Frame(self.root, padding=(12, 4, 12, 10))
        bottom.pack(side="bottom", fill="x")
        self._build_bottom(bottom)

        self.scroll = ScrollFrame(self.root)
        self.scroll.pack(fill="both", expand=True, padx=8)
        self.dyn = ttk.Frame(self.scroll.inner, padding=(4, 4))
        self.dyn.pack(fill="both", expand=True)

    def _build_bottom(self, f):
        row = ttk.Frame(f)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Save finished files in:").pack(side="left")
        ttk.Entry(row, textvariable=self.dest_var).pack(side="left", fill="x",
                                                        expand=True, padx=6)
        ttk.Button(row, text="Browse...", command=self.pick_dest).pack(side="left")

        row = ttk.Frame(f)
        row.pack(fill="x", pady=6)
        self.build_btn = ttk.Button(row, text="Build my GBA ROM", command=self.start_build)
        self.build_btn.pack(side="left")
        self.open_btn = ttk.Button(row, text="Open output folder",
                                   command=self.open_dest, state="disabled")
        self.open_btn.pack(side="left", padx=8)
        ttk.Label(row, textvariable=self.status_var, wraplength=520,
                  justify="left").pack(side="left", padx=8, fill="x", expand=True)

        self.progress = ttk.Progressbar(f, mode="indeterminate")
        self.progress.pack(fill="x")
        self.log = scrolledtext.ScrolledText(f, height=7, state="disabled",
                                             font=("Consolas", 9))
        self.log.pack(fill="x", pady=(6, 0))
        ttk.Label(f, foreground="#666666",
                  text="Everything stays on your computer. Only use game and BIOS "
                       "files you legally own.").pack(anchor="w", pady=(4, 0))

    # --------------------------------------------------------- builder switch

    def select_builder(self, index):
        if self.busy:
            self.combo.current(BUILDERS.index(self.builder))
            return
        b = self.builder = BUILDERS[index]
        self.roms = []
        self.extra_paths = {}
        self.extra_vars = {}
        self.flag_vars = {}
        self.emu_var.set("")
        self.out_var.set("")
        self.desc.configure(text=b["description"])
        for w in self.dyn.winfo_children():
            w.destroy()

        # ---- Step 1: games --------------------------------------------------
        s1 = ttk.LabelFrame(self.dyn, text=" 1.  Add your games ", padding=10)
        s1.pack(fill="x", pady=6)
        ttk.Label(s1, text=b["roms"]["hint"] + "  Games appear in the menu in the "
                  "order shown here.", wraplength=WRAP, justify="left").pack(anchor="w")
        body = ttk.Frame(s1)
        body.pack(fill="x", pady=6)
        self.listbox = tk.Listbox(body, height=8, selectmode="extended",
                                  activestyle="none")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        btns = ttk.Frame(body)
        btns.pack(side="left", padx=(8, 0), anchor="n")
        for text, cmd in (("Add games...", self.add_roms),
                          ("Remove selected", self.remove_roms),
                          ("Move up", lambda: self.move_roms(-1)),
                          ("Move down", lambda: self.move_roms(1)),
                          ("Clear all", self.clear_roms)):
            ttk.Button(btns, text=text, command=cmd, width=16).pack(pady=2)

        # ---- Step 2: emulator + extra files ----------------------------------
        s2 = ttk.LabelFrame(self.dyn, text=" 2.  Emulator and extra files ", padding=10)
        s2.pack(fill="x", pady=6)
        emu = b["emu"]
        ttk.Label(s2, text=emu["label"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Label(s2, text=emu["hint"], wraplength=WRAP, justify="left").pack(anchor="w")
        row = ttk.Frame(s2)
        row.pack(fill="x", pady=4)
        ttk.Entry(row, textvariable=self.emu_var).pack(side="left", fill="x", expand=True)
        if b["id"] == "hvca":
            ttk.Button(row, text="Choose .zip...",
                       command=self.pick_emu_zip).pack(side="left", padx=(6, 0))
            ttk.Button(row, text="Choose folder...",
                       command=self.pick_emu_folder).pack(side="left", padx=(6, 0))
        else:
            ttk.Button(row, text="Browse...",
                       command=self.pick_emu).pack(side="left", padx=(6, 0))
        if engine.can_download(b):
            self.dl_btn = ttk.Button(row, text="Download for me",
                                     command=self.download_emu)
            self.dl_btn.pack(side="left", padx=(6, 0))
            ttk.Label(s2, foreground="#666666",
                      text="Needs internet just once - the emulator is saved on this "
                           "computer, so later builds work offline.").pack(anchor="w")
        cached = engine.cached_emulator(b)
        if cached:
            self.emu_var.set(cached)

        for extra in b.get("extras", []):
            role = extra["role"]
            self.extra_paths[role] = []
            self.extra_vars[role] = tk.StringVar()
            ttk.Separator(s2).pack(fill="x", pady=8)
            ttk.Label(s2, text=extra["label"],
                      font=("Segoe UI", 9, "bold")).pack(anchor="w")
            ttk.Label(s2, text=extra["hint"], wraplength=WRAP,
                      justify="left").pack(anchor="w")
            r = ttk.Frame(s2)
            r.pack(fill="x", pady=4)
            ttk.Entry(r, textvariable=self.extra_vars[role],
                      state="readonly").pack(side="left", fill="x", expand=True)
            ttk.Button(r, text="Browse...",
                       command=lambda e=extra: self.pick_extra(e)).pack(side="left", padx=(6, 0))
            ttk.Button(r, text="Clear",
                       command=lambda ro=role: self.clear_extra(ro)).pack(side="left", padx=(6, 0))

        # ---- Step 3: options --------------------------------------------------
        s3 = ttk.LabelFrame(self.dyn, text=" 3.  Options ", padding=10)
        s3.pack(fill="x", pady=6)
        for opt in b.get("options", []):
            var = tk.BooleanVar(value=False)
            self.flag_vars[opt["flag"]] = var
            ttk.Checkbutton(s3, text=opt["label"], variable=var).pack(anchor="w")
            ttk.Label(s3, text=opt["help"], foreground="#666666", wraplength=WRAP - 30,
                      justify="left").pack(anchor="w", padx=(24, 0), pady=(0, 4))
        orow = ttk.Frame(s3)
        orow.pack(fill="x", pady=(6, 0))
        if b["id"] == "snezziboy":
            ttk.Label(orow, text="Snezziboy makes one .gba file per game, "
                      "named after the game.").pack(anchor="w")
        else:
            ttk.Label(orow, text="Name for the finished ROM:").pack(side="left")
            ttk.Entry(orow, textvariable=self.out_var, width=34).pack(side="left", padx=6)
            ttk.Label(orow, text=f"(leave empty for {b['output']})",
                      foreground="#666666").pack(side="left")

        self.scroll.canvas.yview_moveto(0)
        self.set_status("Add your games, then press Build.")

    # --------------------------------------------------------------- file pick

    def _types(self, exts, label):
        return [(label, tuple("*" + e for e in exts)), ("All files", "*.*")]

    def add_roms(self):
        exts = self.builder["roms"]["exts"]
        paths = filedialog.askopenfilenames(
            title="Choose your games", filetypes=self._types(exts, self.builder["roms"]["label"]))
        for p in paths:
            if p not in self.roms:
                self.roms.append(p)
        if self.roms and not self.dest_var.get():
            self.dest_var.set(os.path.dirname(self.roms[0]))
        self.refresh_list()

    def refresh_list(self, select=()):
        self.listbox.delete(0, "end")
        for i, p in enumerate(self.roms, 1):
            try:
                size = human_size(os.path.getsize(p))
            except OSError:
                size = "?"
            self.listbox.insert("end", f"{i:>3}.  {os.path.basename(p)}   ({size})")
        for i in select:
            self.listbox.selection_set(i)

    def remove_roms(self):
        drop = set(self.listbox.curselection())
        self.roms = [p for i, p in enumerate(self.roms) if i not in drop]
        self.refresh_list()

    def clear_roms(self):
        self.roms = []
        self.refresh_list()

    def move_roms(self, step):
        sel = list(self.listbox.curselection())
        if not sel:
            return
        order = sel if step < 0 else sel[::-1]
        picked = set(sel)
        for i in order:
            j = i + step
            if 0 <= j < len(self.roms) and j not in picked:
                self.roms[i], self.roms[j] = self.roms[j], self.roms[i]
                picked.discard(i)
                picked.add(j)
        self.refresh_list(select=sorted(picked))

    def pick_emu(self):
        p = filedialog.askopenfilename(
            title="Choose the emulator file",
            filetypes=[("Emulator", ("*.gba", "*.bin")), ("All files", "*.*")])
        if p:
            self.emu_var.set(p)

    def pick_emu_zip(self):
        p = filedialog.askopenfilename(title="Choose the HVCA emulator .zip",
                                       filetypes=[("Zip files", "*.zip"), ("All files", "*.*")])
        if p:
            self.emu_var.set(p)

    def pick_emu_folder(self):
        p = filedialog.askdirectory(title="Choose the HVCA 'bin' folder (contains base.bin)")
        if p:
            self.emu_var.set(p)

    def pick_extra(self, extra):
        role = extra["role"]
        ft = self._types(extra["exts"], extra["label"])
        if extra.get("multiple"):
            paths = list(filedialog.askopenfilenames(title=extra["label"], filetypes=ft))
        else:
            p = filedialog.askopenfilename(title=extra["label"], filetypes=ft)
            paths = [p] if p else []
        if paths:
            self.extra_paths[role] = paths
            self.extra_vars[role].set("; ".join(os.path.basename(p) for p in paths))

    def clear_extra(self, role):
        self.extra_paths[role] = []
        self.extra_vars[role].set("")

    def pick_dest(self):
        p = filedialog.askdirectory(title="Where should the finished files go?")
        if p:
            self.dest_var.set(p)

    # ------------------------------------------------------------ log / status

    def set_status(self, text):
        self.status_var.set(text)

    def log_set(self, text):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.build_btn.configure(state=state)
        if busy:
            self.open_btn.configure(state="disabled")
            self.progress.start(12)
        else:
            self.progress.stop()

    # ------------------------------------------------------------------ build

    def start_build(self):
        if self.busy:
            return
        b = self.builder
        dest = self.dest_var.get().strip() or os.path.join(os.path.expanduser("~"), "Documents")
        self.dest_var.set(dest)
        flags = [f for f, v in self.flag_vars.items() if v.get()]
        args = dict(
            builder_id=b["id"], roms=list(self.roms),
            emu=self.emu_var.get().strip() or None,
            extras={r: list(p) for r, p in self.extra_paths.items()},
            flags=flags, out_name=self.out_var.get().strip(), dest_dir=dest)
        self.log_set("")
        self.set_busy(True)
        self.set_status("Starting...")

        def work():
            try:
                res = engine.run_build(progress=lambda m: self.q.put(("status", m)), **args)
            except Exception:
                res = {"ok": False, "saved": [], "log": traceback.format_exc(),
                       "message": "Something unexpected went wrong. Details are in the box below."}
            self.q.put(("done", res))

        threading.Thread(target=work, daemon=True).start()

    def download_emu(self):
        if self.busy:
            return
        b = self.builder
        self.set_busy(True)
        self.set_status("Downloading emulator...")

        def work():
            try:
                path = engine.download_emulator(b, lambda m: self.q.put(("status", m)))
                self.q.put(("emu", path))
            except ApiError as e:
                self.q.put(("emu_error", str(e)))
            except Exception:
                self.q.put(("emu_error", traceback.format_exc()))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "status":
                    self.set_status(data)
                elif kind == "emu":
                    self.set_busy(False)
                    self.emu_var.set(data)
                    self.set_status("Emulator downloaded and saved for offline use.")
                elif kind == "emu_error":
                    self.set_busy(False)
                    self.set_status("Download failed.")
                    messagebox.showerror("Download failed", data)
                elif kind == "done":
                    self._finish(data)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finish(self, res):
        self.set_busy(False)
        self.log_set(res.get("log") or "")
        if res["ok"]:
            names = "\n".join(os.path.basename(p) for p in res["saved"])
            self.set_status("Done! Saved to: " + self.dest_var.get())
            self.open_btn.configure(state="normal")
            messagebox.showinfo(
                "Your ROM is ready",
                f"Finished files:\n\n{names}\n\nSaved in:\n{self.dest_var.get()}\n\n"
                "Copy the .gba file to your flash cart, or open it in an emulator.")
        else:
            self.set_status("Build failed - see the message and the log below.")
            messagebox.showerror("Build failed", res.get("message") or "The build failed.")

    def open_dest(self):
        d = self.dest_var.get()
        try:
            if sys.platform.startswith("win"):
                os.startfile(d)                       # noqa: B606 (Windows only)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
        except OSError as e:
            messagebox.showerror("Can't open folder", str(e))

    def run(self):
        self.root.mainloop()


def main():
    App().run()


if __name__ == "__main__":
    main()
