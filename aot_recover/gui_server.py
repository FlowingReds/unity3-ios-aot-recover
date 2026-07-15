"""Local web GUI for unity3-aot-recover.

Stdlib only. Serves a single page bound to 127.0.0.1 and runs the real
``recover()`` pipeline in a worker thread. Browse buttons open native OS file
dialogs through tkinter so the browser gets genuine absolute paths (the browser
sandbox never exposes them); if tkinter is unavailable the path fields are still
editable by hand.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .cli import RecoveryError, recover

HTML_PATH = Path(__file__).resolve().parent / "gui.html"

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
    """Turn a form payload into the Namespace ``recover()`` expects.

    Empty strings become ``None``; the donor field becomes a list of non-blank
    paths; the checkbox becomes a real bool.
    """

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


def _run(values: dict[str, Any]) -> dict[str, Any]:
    args = build_args(values)
    if not args.ipa:
        return {"ok": False, "error": "Select an IPA first."}
    if not args.output:
        return {"ok": False, "error": "Choose an output folder first."}
    try:
        manifest = recover(args)
    except (RecoveryError, OSError, zipfile.BadZipFile) as error:
        return {"ok": False, "error": str(error)}
    state = manifest["recovery_state"]
    title, body = _OUTCOMES.get(state, (state, ""))
    report = str(Path(args.output).expanduser().resolve() / "REPORT.md")
    return {"ok": True, "state": state, "title": title, "body": body, "report": report}


def _pick(kind: str) -> dict[str, Any]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as error:  # pragma: no cover - platform tk missing
        return {"path": "", "error": f"native picker unavailable: {error}"}
    # ponytail: fresh Tk per pick from the handler thread; fine for one-shot
    # dialogs, revisit only if a real event loop is ever needed.
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if kind == "folder":
            path = filedialog.askdirectory()
        elif kind == "ipa":
            path = filedialog.askopenfilename(filetypes=[("iOS app", "*.ipa"), ("All files", "*")])
        else:
            path = filedialog.askopenfilename()
    finally:
        root.destroy()
    return {"path": path or ""}


def _prereq() -> dict[str, Any]:
    ilspy = (
        shutil.which("ilspycmd")
        or (Path.home() / ".dotnet" / "tools" / ("ilspycmd.exe" if sys.platform == "win32" else "ilspycmd"))
    )
    ilspy_ok = bool(shutil.which("ilspycmd")) or (isinstance(ilspy, Path) and ilspy.is_file())
    return {"dotnet": shutil.which("dotnet") is not None, "ilspy": ilspy_ok}


def _open(path: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if not target.exists():
        return {"ok": False, "error": f"not found: {target}"}
    try:
        if sys.platform == "win32":
            import os

            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except OSError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # quiet
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict[str, Any], code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, HTML_PATH.read_bytes(), "text/html; charset=utf-8")
        elif path == "/prereq":
            self._json(_prereq())
        elif path == "/pick":
            from urllib.parse import parse_qs, urlparse

            kind = (parse_qs(urlparse(self.path).query).get("kind") or ["file"])[0]
            self._json(_pick(kind))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "bad request body"}, 400)
            return
        if self.path == "/run":
            self._json(_run(payload))
        elif self.path == "/open":
            self._json(_open(payload.get("path", "")))
        else:
            self._json({"error": "not found"}, 404)


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"unity3-aot-recover GUI: {url}")
    print("Close this window (Ctrl+C) to stop.")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
