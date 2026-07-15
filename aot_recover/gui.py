"""Native desktop GUI for unity3-aot-recover.

Stdlib only (tkinter). Runs the same ``recover()`` pipeline as the CLI on a
worker thread and reports the recovery state, with buttons to open the output
folder and REPORT.md. tkinter ships with the official Windows and macOS CPython
installers; on Linux install the system Tk package (``tk`` / ``python3-tk``).
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .cli import RecoveryError, recover

_OUTCOMES = {
    "native-method-map-recovered": (
        "Full recovery",
        "Managed metadata plus the native Mono AOT method map were recovered. "
        "Ghidra/radare2 labels are ready for pseudocode export.",
    ),
    "metadata-recovered-native-encrypted": (
        "Metadata recovered — native code encrypted",
        "The managed type/signature structure is recovered, but the executable "
        "is FairPlay-encrypted. Supply a same-build decrypted executable to map "
        "ARM method bodies.",
    ),
    "metadata-recovered-native-map-unavailable": (
        "Metadata recovered — no native map",
        "Managed structure is recovered, but no usable Mono AOT method-address "
        "table was found in the supplied executable.",
    ),
}


def build_args(values: dict[str, Any]) -> SimpleNamespace:
    """Turn form values into the Namespace ``recover()`` expects."""

    def clean(key: str) -> str | None:
        text = (values.get(key) or "").strip()
        return text or None

    refs_raw = values.get("reference_managed") or []
    if isinstance(refs_raw, str):
        refs_raw = refs_raw.splitlines()
    refs = [line.strip() for line in refs_raw if line and line.strip()]

    return SimpleNamespace(
        ipa=clean("ipa"),
        output=clean("output"),
        binary=clean("binary"),
        arch=None if (values.get("arch") or "all") == "all" else clean("arch"),
        ilspycmd=clean("ilspycmd"),
        no_decompile=bool(values.get("no_decompile")),
        reference_managed=refs or None,
    )


def _open_path(path: str) -> None:
    target = Path(path).expanduser()
    if not target.exists():
        return
    if sys.platform == "win32":
        import os

        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


def _prereqs() -> list[str]:
    missing = []
    if shutil.which("dotnet") is None:
        missing.append(".NET SDK (dotnet) — required for metadata extraction")
    ilspy = shutil.which("ilspycmd") or (
        Path.home() / ".dotnet" / "tools" / ("ilspycmd.exe" if sys.platform == "win32" else "ilspycmd")
    )
    if not (shutil.which("ilspycmd") or (isinstance(ilspy, Path) and ilspy.is_file())):
        missing.append("ilspycmd — required for C# skeletons")
    return missing


class App:
    def __init__(self, root: "object") -> None:
        import tkinter as tk
        from tkinter import filedialog, ttk

        self.tk = tk
        self.filedialog = filedialog
        self.root = root
        self.results: "queue.Queue[dict[str, Any]]" = queue.Queue()

        root.title("Unity 3 iOS AOT Recover")
        root.minsize(560, 420)
        pad = {"padx": 12, "pady": 4}
        frm = ttk.Frame(root, padding=14)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(frm, text="Recover C# metadata and native Mono AOT method maps from an IPA you own.",
                  foreground="#666").grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1

        self.prereq_var = tk.StringVar()
        self.prereq_lbl = ttk.Label(frm, textvariable=self.prereq_var, foreground="#8a6d00", wraplength=520)
        self.prereq_lbl.grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        self.ipa = self._path_row(frm, row, "IPA file", self._pick_ipa); row += 1
        self.output = self._path_row(frm, row, "Output folder", self._pick_output); row += 1

        self.no_decompile = tk.BooleanVar()
        ttk.Checkbutton(frm, text="Skip C# decompile (faster)", variable=self.no_decompile).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad); row += 1

        # Advanced
        adv = ttk.LabelFrame(frm, text="Advanced", padding=8)
        adv.grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        adv.columnconfigure(1, weight=1)
        frm.rowconfigure(row, weight=0); row += 1

        self.binary = self._path_row(adv, 0, "Decrypted executable", self._pick_binary)
        ttk.Label(adv, text="Architecture").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.arch = tk.StringVar(value="all")
        ttk.Combobox(adv, textvariable=self.arch, values=["all", "armv7", "armv6"],
                     state="readonly", width=10).grid(row=1, column=1, sticky="w", padx=4)

        ttk.Label(adv, text="Donor / reference managed").grid(row=2, column=0, sticky="nw", padx=4, pady=4)
        self.refs = tk.Listbox(adv, height=3)
        self.refs.grid(row=2, column=1, sticky="ew", padx=4, pady=4)
        refbtns = ttk.Frame(adv); refbtns.grid(row=2, column=2, sticky="n")
        ttk.Button(refbtns, text="Add DLL…", command=lambda: self._add_ref(False)).pack(fill="x")
        ttk.Button(refbtns, text="Add folder…", command=lambda: self._add_ref(True)).pack(fill="x")
        ttk.Button(refbtns, text="Remove", command=self._remove_ref).pack(fill="x")

        self.ilspycmd = self._path_row(adv, 3, "ilspycmd path", self._pick_ilspy)

        self.run_btn = ttk.Button(frm, text="Recover", command=self._run)
        self.run_btn.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 6)); row += 1

        self.status = tk.StringVar()
        ttk.Label(frm, textvariable=self.status, wraplength=520).grid(
            row=row, column=0, columnspan=3, sticky="w"); row += 1

        self.result = tk.Text(frm, height=6, wrap="word", state="disabled")
        self.result.grid(row=row, column=0, columnspan=3, sticky="nsew")
        frm.rowconfigure(row, weight=1); row += 1

        self.actions = ttk.Frame(frm)
        self.actions.grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 0))

        missing = _prereqs()
        if missing:
            self.prereq_var.set("Missing on this machine:  •  " + "  •  ".join(missing))

    def _path_row(self, parent, r, label, cmd):
        import tkinter as tk
        from tkinter import ttk

        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=4, pady=4)
        var = tk.StringVar()
        ttk.Entry(parent, textvariable=var).grid(row=r, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(parent, text="Browse…", command=cmd).grid(row=r, column=2, padx=4)
        return var

    def _pick_ipa(self):
        p = self.filedialog.askopenfilename(filetypes=[("iOS app", "*.ipa"), ("All files", "*")])
        if p:
            self.ipa.set(p)

    def _pick_output(self):
        p = self.filedialog.askdirectory()
        if p:
            self.output.set(p)

    def _pick_binary(self):
        p = self.filedialog.askopenfilename()
        if p:
            self.binary.set(p)

    def _pick_ilspy(self):
        p = self.filedialog.askopenfilename()
        if p:
            self.ilspycmd.set(p)

    def _add_ref(self, folder):
        p = self.filedialog.askdirectory() if folder else self.filedialog.askopenfilename(
            filetypes=[("Managed DLL", "*.dll"), ("All files", "*")])
        if p:
            self.refs.insert("end", p)

    def _remove_ref(self):
        for i in reversed(self.refs.curselection()):
            self.refs.delete(i)

    def _values(self) -> dict[str, Any]:
        return {
            "ipa": self.ipa.get(), "output": self.output.get(), "binary": self.binary.get(),
            "arch": self.arch.get(), "ilspycmd": self.ilspycmd.get(),
            "no_decompile": self.no_decompile.get(),
            "reference_managed": list(self.refs.get(0, "end")),
        }

    def _run(self):
        args = build_args(self._values())
        if not args.ipa:
            self._set_result("Select an IPA first.", error=True); return
        if not args.output:
            self._set_result("Choose an output folder first.", error=True); return
        self.run_btn.config(state="disabled")
        self.status.set("Recovering… this can take a few minutes.")
        for widget in self.actions.winfo_children():
            widget.destroy()
        threading.Thread(target=self._worker, args=(args,), daemon=True).start()
        self.root.after(150, self._poll)

    def _worker(self, args):
        try:
            manifest = recover(args)
            self.results.put({"ok": True, "manifest": manifest, "output": args.output})
        except (RecoveryError, OSError, zipfile.BadZipFile) as error:
            self.results.put({"ok": False, "error": str(error)})

    def _poll(self):
        try:
            r = self.results.get_nowait()
        except queue.Empty:
            self.root.after(150, self._poll); return
        self.run_btn.config(state="normal")
        self.status.set("")
        if not r["ok"]:
            self._set_result("Recovery failed:\n\n" + r["error"], error=True); return
        state = r["manifest"]["recovery_state"]
        title, body = _OUTCOMES.get(state, (state, ""))
        self._set_result(f"{title}\n\n{body}", error=False)
        report = str(Path(r["output"]).expanduser().resolve() / "REPORT.md")
        from tkinter import ttk

        ttk.Button(self.actions, text="Open output folder",
                   command=lambda: _open_path(r["output"])).pack(side="left", padx=(0, 6))
        ttk.Button(self.actions, text="Open REPORT.md",
                   command=lambda: _open_path(report)).pack(side="left")

    def _set_result(self, text, error):
        self.result.config(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", ("✕ " if error else "✓ ") + text)
        self.result.config(state="disabled")


def main() -> int:
    try:
        import tkinter as tk
    except Exception as error:  # pragma: no cover
        print(f"error: tkinter is unavailable ({error}).", file=sys.stderr)
        print("Install the system Tk package: 'pacman -S tk' / 'apt install python3-tk'.", file=sys.stderr)
        return 1
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
