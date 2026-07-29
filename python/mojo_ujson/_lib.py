"""ctypes bindings for the Mojo JSON kernels."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.join(ROOT, "dist", "libmojo-ujson.so")
SOURCE = os.path.join(ROOT, "src", "ujson.mojo")

I = ctypes.c_int64
_SIGNATURES = {
    "mujson_parse": ([I] * 9, I),
    "mujson_encode": ([I] * 10, I),
}


class BuildError(RuntimeError):
    pass


def build(force: bool = False) -> str:
    if not force and os.path.exists(LIB) and os.path.getmtime(LIB) >= os.path.getmtime(SOURCE):
        return LIB
    pixi = shutil.which("pixi")
    if not pixi:
        raise BuildError("the Mojo library is missing; run `pixi run build`")
    proc = subprocess.run(
        [pixi, "run", "--manifest-path", os.path.join(ROOT, "pixi.toml"), "build"],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if proc.returncode or not os.path.exists(LIB):
        raise BuildError((proc.stderr or proc.stdout).strip()[:4000])
    return LIB


_library: ctypes.CDLL | None = None


def lib() -> ctypes.CDLL:
    global _library
    if _library is None:
        # The kernels borrow Python- and NumPy-owned buffers.  PyDLL keeps the
        # GIL held for the entire synchronous call, so another Python thread
        # cannot mutate a writable input buffer while Mojo is reading it.
        _library = ctypes.PyDLL(build())
        for name, (argtypes, restype) in _SIGNATURES.items():
            fn = getattr(_library, name)
            fn.argtypes = argtypes
            fn.restype = restype
    return _library
