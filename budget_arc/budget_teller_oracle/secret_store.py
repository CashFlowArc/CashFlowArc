from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import os
from pathlib import Path

from .crypto import generate_master_key

_ENTROPY = b"budget_teller_oracle:v1"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def dpapi_available() -> bool:
    return os.name == "nt"


def dpapi_key_path() -> Path:
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return root / "BudgetTellerOracle" / "budget_master_key.dpapi"


def _blob_from_bytes(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _protect(data: bytes) -> bytes:
    if not dpapi_available():
        raise RuntimeError("Windows DPAPI is only available on Windows")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    data_blob, data_buffer = _blob_from_bytes(data)
    entropy_blob, entropy_buffer = _blob_from_bytes(_ENTROPY)
    output_blob = _DataBlob()

    ok = crypt32.CryptProtectData(
        ctypes.byref(data_blob),
        "BudgetTellerOracle master key",
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    # Keep buffers alive until after the native call.
    _ = (data_buffer, entropy_buffer)
    if not ok:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _unprotect(data: bytes) -> bytes:
    if not dpapi_available():
        raise RuntimeError("Windows DPAPI is only available on Windows")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    data_blob, data_buffer = _blob_from_bytes(data)
    entropy_blob, entropy_buffer = _blob_from_bytes(_ENTROPY)
    output_blob = _DataBlob()

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(data_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    _ = (data_buffer, entropy_buffer)
    if not ok:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def store_master_key_dpapi(master_key: str, *, overwrite: bool = False) -> Path:
    path = dpapi_key_path()
    if path.exists() and not overwrite:
        raise RuntimeError(f"DPAPI master key already exists at {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    protected = base64.b64encode(_protect(master_key.encode("ascii"))).decode("ascii")
    path.write_text(protected, encoding="ascii")
    return path


def load_master_key_dpapi() -> str:
    path = dpapi_key_path()
    if not path.exists():
        raise RuntimeError(f"DPAPI master key file is missing at {path}")

    protected = base64.b64decode(path.read_text(encoding="ascii").strip())
    return _unprotect(protected).decode("ascii")


def ensure_master_key_dpapi() -> Path:
    path = dpapi_key_path()
    if path.exists():
        return path
    return store_master_key_dpapi(generate_master_key())


def migrate_env_master_key_to_dpapi(env_path: Path, *, overwrite: bool = False) -> tuple[Path, bool]:
    text = env_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    found_plaintext_key: str | None = None
    has_source = False
    new_lines: list[str] = []

    for line in lines:
        if line.startswith("BUDGET_MASTER_KEY_SOURCE="):
            has_source = True
            new_lines.append("BUDGET_MASTER_KEY_SOURCE=dpapi")
            continue
        if line.startswith("BUDGET_MASTER_KEY="):
            _, _, value = line.partition("=")
            found_plaintext_key = value.strip() or None
            new_lines.append("BUDGET_MASTER_KEY=")
            continue
        new_lines.append(line)

    if found_plaintext_key:
        path = store_master_key_dpapi(found_plaintext_key, overwrite=overwrite)
        migrated = True
    else:
        path = ensure_master_key_dpapi()
        migrated = False

    if not has_source:
        insert_at = None
        for index, line in enumerate(new_lines):
            if line.startswith("BUDGET_MASTER_KEY="):
                insert_at = index + 1
                break
        if insert_at is None:
            new_lines.append("BUDGET_MASTER_KEY=")
            new_lines.append("BUDGET_MASTER_KEY_SOURCE=dpapi")
        else:
            new_lines.insert(insert_at, "BUDGET_MASTER_KEY_SOURCE=dpapi")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return path, migrated

