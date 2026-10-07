"""
engine.py - GUI-independent build engine for the desktop app
============================================================

Wraps builder_core (the same registry/validation/command logic used by the
web version) and adds what a standalone Windows program needs:

  * finds the bundled builder scripts (works both from source and from a
    PyInstaller .exe)
  * runs the scripts IN-PROCESS (inside a frozen .exe, sys.executable is the
    app itself, so the web version's "run python as a subprocess" trick
    would just relaunch the window)
  * stages the user's files, runs the build, copies results to a folder the
    user chose, and cleans up
  * optional one-time emulator download, cached for offline use afterwards
  * a headless self-test used by the automated build to prove the .exe works

No tkinter in here, so it can be tested without a display.
"""

import io
import os
import runpy
import shutil
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.request
import uuid

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = getattr(sys, "_MEIPASS", APP_DIR)          # _MEIPASS = unpacked .exe contents
BUILDERS_DIR = os.path.join(BASE_DIR, "builders")
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".gba-builder", "emulators")

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import builder_core  # noqa: E402
from builder_core import (  # noqa: E402
    BUILDERS, BUILDERS_BY_ID, ApiError, human_size, sanitize_filename,
)

_work_root = None
_BUILD_LOCK = threading.Lock()


def _init():
    """Point builder_core at the bundled scripts and a private temp folder."""
    global _work_root
    if _work_root is None or not os.path.isdir(_work_root):
        _work_root = tempfile.mkdtemp(prefix="gba-builder-")
    builder_core.REPO_DIR = BUILDERS_DIR
    builder_core.JOBS_DIR = _work_root
    builder_core.EXECUTOR = _inprocess_executor


# --------------------------------------------------------------------------
# Running the builder scripts inside this process
# --------------------------------------------------------------------------

def _inprocess_executor(cmd, cwd):
    """Same idea as the in-browser (Pyodide) executor: run the script with
    runpy, capture everything it prints, return (exit_code, log)."""
    script = cmd[0]
    os.makedirs(cwd, exist_ok=True)
    old_cwd, old_argv = os.getcwd(), sys.argv
    old_out, old_err = sys.stdout, sys.stderr
    buf = io.StringIO()
    code = 0
    try:
        os.chdir(cwd)
        sys.argv = [script] + [str(a) for a in cmd[1:]]
        sys.stdout = sys.stderr = buf
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        if isinstance(e.code, int):
            code = e.code
        elif e.code is None:
            code = 0
        else:                       # sys.exit("some message")
            buf.write(str(e.code) + "\n")
            code = 1
    except Exception:
        traceback.print_exc(file=buf)
        code = 1
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        sys.argv = old_argv
        try:
            os.chdir(old_cwd)
        except OSError:
            pass
    return code, buf.getvalue()


# --------------------------------------------------------------------------
# Staging + building
# --------------------------------------------------------------------------

def _unique_name(folder, name):
    safe = sanitize_filename(name)
    base, ext = os.path.splitext(safe)
    cand, n = safe, 1
    while os.path.exists(os.path.join(folder, cand)):
        n += 1
        cand = f"{base}_{n}{ext}"
    return cand


def _stage(src, folder):
    """Copy a file (or folder) into the job's uploads folder; return its name."""
    if os.path.isdir(src):
        name = _unique_name(folder, os.path.basename(os.path.normpath(src)))
        shutil.copytree(src, os.path.join(folder, name))
    else:
        name = _unique_name(folder, os.path.basename(src))
        shutil.copyfile(src, os.path.join(folder, name))
    return name


def _free_path(folder, name):
    """Never overwrite something the user already has."""
    base, ext = os.path.splitext(name)
    cand, n = os.path.join(folder, name), 1
    while os.path.exists(cand):
        n += 1
        cand = os.path.join(folder, f"{base} ({n}){ext}")
    return cand


def run_build(builder_id, roms, emu, extras, flags, out_name, dest_dir,
              progress=lambda msg: None):
    """Run one build.

    roms      list of game file paths, in menu order
    emu       path to the emulator file (or HVCA folder/.zip)
    extras    {role: [paths]}  e.g. {"bios": [...], "splash": [...]}
    flags     list of option flags, e.g. ["-c", "-sav"]
    out_name  output file name ('' = builder default)
    dest_dir  folder to put the finished files in

    Returns a dict: ok, message, log, saved (list of file paths)
    """
    _init()
    builder = BUILDERS_BY_ID[builder_id]
    job = "job-" + uuid.uuid4().hex[:8]
    updir = builder_core.uploads_dir(job)
    os.makedirs(updir, exist_ok=True)
    try:
        progress("Preparing your files...")
        rom_names = [_stage(p, updir) for p in roms]
        files = {}
        if emu:
            files["emu"] = _stage(emu, updir)
        for role, paths in (extras or {}).items():
            names = [_stage(p, updir) for p in paths if p]
            if names:
                files[role] = names
        payload = {
            "roms": rom_names,
            "files": files,
            "options": {"flags": list(flags or []), "output": out_name or ""},
        }

        progress("Building... large compilations can take a minute or two.")
        with _BUILD_LOCK:
            result = builder_core.run_build(builder, job, payload)
        result.setdefault("log", "")
        result["saved"] = []
        if not result["ok"]:
            return result

        progress("Saving your files...")
        os.makedirs(dest_dir, exist_ok=True)
        odir = builder_core.out_dir(job)
        for o in result["outputs"]:
            dst = _free_path(dest_dir, o["name"])
            shutil.copyfile(os.path.join(odir, o["name"]), dst)
            result["saved"].append(dst)
        return result
    except (OSError, ApiError) as e:
        return {"ok": False, "log": traceback.format_exc(), "saved": [],
                "message": f"Could not complete the build: {e}"}
    finally:
        shutil.rmtree(builder_core.job_dir(job), ignore_errors=True)


# --------------------------------------------------------------------------
# Optional emulator download (cached so later builds work fully offline)
# --------------------------------------------------------------------------

def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "gba-compilation-builder"})
    tmp = dest + ".part"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    os.replace(tmp, dest)


def can_download(builder):
    emu = builder["emu"]
    return bool(emu.get("fetch") or emu.get("fetch_folder"))


def cached_emulator(builder):
    """Path of a previously downloaded emulator, or None."""
    path = os.path.join(CACHE_DIR, builder["id"], builder["emu"]["filename"])
    if os.path.isdir(path):
        return path if os.path.isfile(os.path.join(path, "base.bin")) else None
    return path if os.path.isfile(path) else None


def download_emulator(builder, progress=lambda msg: None):
    """Download the recommended emulator into the cache. Returns its path."""
    emu = builder["emu"]
    root = os.path.join(CACHE_DIR, builder["id"])
    try:
        if "fetch_folder" in emu:
            spec = emu["fetch_folder"]
            target = os.path.join(root, emu["filename"])
            os.makedirs(os.path.join(target, spec["subdir"]), exist_ok=True)
            todo = [(rel, os.path.join(target, rel)) for rel in spec["files"]]
            todo += [(f"{spec['subdir']}/{n}", os.path.join(target, spec["subdir"], n))
                     for n in spec.get("subdir_files", [])]
            for i, (rel, dest) in enumerate(todo, 1):
                progress(f"Downloading emulator files ({i}/{len(todo)})...")
                _download(f"{spec['raw']}/{rel}", dest)
            return target
        if emu.get("fetch"):
            progress("Downloading emulator...")
            dest = os.path.join(root, emu["filename"])
            _download(emu["fetch"], dest)
            return dest
    except (urllib.error.URLError, OSError) as e:
        raise ApiError(
            "Couldn't download the emulator - check your internet connection, "
            f"or add the emulator file yourself.\n({e})")
    raise ApiError("There's no automatic download for this emulator - "
                   "please add the file yourself.")


# --------------------------------------------------------------------------
# Self-test (used by the automated Windows build, also handy locally)
# --------------------------------------------------------------------------

def selftest(fixtures_dir):
    """Build two real compilations headlessly. Returns (ok, report_text)."""
    lines, ok = [], True
    dest = tempfile.mkdtemp(prefix="gba-selftest-")
    cases = [
        ("pocketnes", ["test.nes"], "pocketnes.gba"),
        ("goomba", ["gbgame.gb"], "jagoombacolor.gba"),
    ]
    try:
        for bid, roms, emu in cases:
            emu_path = os.path.join(fixtures_dir, emu)
            res = run_build(bid, [os.path.join(fixtures_dir, r) for r in roms],
                            emu_path, {}, [], f"selftest-{bid}.gba", dest)
            gba = [p for p in res.get("saved", []) if p.lower().endswith(".gba")]
            good = bool(res["ok"] and gba
                        and os.path.getsize(gba[0]) > os.path.getsize(emu_path))
            ok = ok and good
            lines.append(f"{bid}: {'PASS' if good else 'FAIL'}"
                         + (f" ({human_size(os.path.getsize(gba[0]))})" if gba else ""))
            if not good:
                lines.append(f"  message: {res.get('message')}")
                lines.append("  log: " + (res.get("log") or "").strip()[:1500])
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    finally:
        shutil.rmtree(dest, ignore_errors=True)
    lines.append("SELFTEST " + ("PASSED" if ok else "FAILED"))
    return ok, "\n".join(lines) + "\n"
