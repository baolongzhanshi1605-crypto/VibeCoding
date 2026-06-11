from __future__ import annotations

import base64
from ctypes import (
    Structure,
    addressof,
    byref,
    c_ulong,
    c_ulonglong,
    c_void_p,
    c_wchar_p,
    create_string_buffer,
    create_unicode_buffer,
    memmove,
    sizeof,
    windll,
)
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import win32crypt


@dataclass(frozen=True)
class CookieRecord:
    host_key: str
    name: str
    value: str


class DataBlob(Structure):
    _fields_ = [("cbData", c_ulong), ("pbData", c_void_p)]


class AuthenticatedCipherModeInfo(Structure):
    _fields_ = [
        ("cbSize", c_ulong),
        ("dwInfoVersion", c_ulong),
        ("pbNonce", c_void_p),
        ("cbNonce", c_ulong),
        ("pbAuthData", c_void_p),
        ("cbAuthData", c_ulong),
        ("pbTag", c_void_p),
        ("cbTag", c_ulong),
        ("pbMacContext", c_void_p),
        ("cbMacContext", c_ulong),
        ("cbAAD", c_ulong),
        ("cbData", c_ulonglong),
        ("dwFlags", c_ulong),
    ]


def build_cookie_header(cookies: list[CookieRecord], domains: list[str]) -> str:
    parts = []
    normalized_domains = [domain.lower().lstrip(".") for domain in domains]
    for cookie in cookies:
        host = cookie.host_key.lower().lstrip(".")
        if any(host == domain or host.endswith("." + domain) for domain in normalized_domains):
            parts.append(f"{cookie.name}={cookie.value}")
    return "; ".join(parts)


def load_cookie_header(profile_dir: Path, domains: list[str]) -> str:
    cookies = load_cookies(profile_dir, domains)
    return build_cookie_header(cookies, domains)


def load_cookies(profile_dir: Path, domains: list[str]) -> list[CookieRecord]:
    local_state = profile_dir / "Local State"
    cookie_db = profile_dir / "Default" / "Network" / "Cookies"
    if not local_state.exists():
        raise FileNotFoundError(f"Edge Local State not found: {local_state}")
    if not cookie_db.exists():
        raise FileNotFoundError(f"Edge cookie database not found: {cookie_db}")

    master_key = _load_master_key(local_state)
    temp_db = Path(tempfile.gettempdir()) / "chaoxing_edge_cookies.sqlite"
    try:
        shutil.copy2(cookie_db, temp_db)
    except PermissionError as exc:
        raise RuntimeError(
            "Edge cookie database is locked. Close the dedicated Chaoxing Edge "
            "window, then run the check again."
        ) from exc

    rows = _read_cookie_rows(temp_db, domains)
    records = []
    for host_key, name, value, encrypted_value in rows:
        plain_value = value or _decrypt_cookie_value(encrypted_value, master_key)
        if plain_value:
            records.append(CookieRecord(host_key=host_key, name=name, value=plain_value))
    return records


def _read_cookie_rows(cookie_db: Path, domains: list[str]):
    clauses = []
    params = []
    for domain in domains:
        stripped = domain.lstrip(".")
        clauses.append("host_key = ? or host_key like ?")
        params.extend([stripped, f"%.{stripped}"])
    where = " or ".join(f"({clause})" for clause in clauses)

    connection = sqlite3.connect(cookie_db)
    try:
        return connection.execute(
            f"""
            select host_key, name, value, encrypted_value
            from cookies
            where {where}
            order by host_key, name
            """,
            params,
        ).fetchall()
    finally:
        connection.close()


def _load_master_key(local_state: Path) -> bytes:
    data = json.loads(local_state.read_text(encoding="utf-8"))
    encrypted_key = base64.b64decode(data["os_crypt"]["encrypted_key"])
    if encrypted_key.startswith(b"DPAPI"):
        encrypted_key = encrypted_key[5:]
    return _crypt_unprotect_data(encrypted_key)


def _decrypt_cookie_value(encrypted_value: bytes, master_key: bytes) -> str:
    if not encrypted_value:
        return ""
    if encrypted_value.startswith((b"v10", b"v11")):
        nonce = encrypted_value[3:15]
        ciphertext = encrypted_value[15:-16]
        tag = encrypted_value[-16:]
        plaintext = _aes_gcm_decrypt(master_key, nonce, ciphertext, tag)
    else:
        plaintext = _crypt_unprotect_data(encrypted_value)

    for candidate in (plaintext, plaintext[32:] if len(plaintext) > 32 else b""):
        try:
            return candidate.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return ""


def _crypt_unprotect_data(data: bytes) -> bytes:
    _description, plaintext = win32crypt.CryptUnprotectData(data, None, None, None, 0)
    return plaintext


def _aes_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    bcrypt = windll.bcrypt
    algorithm = c_void_p()
    key_handle = c_void_p()
    result_size = c_ulong()

    status = bcrypt.BCryptOpenAlgorithmProvider(
        byref(algorithm),
        c_wchar_p("AES"),
        None,
        0,
    )
    _check_status(status, "BCryptOpenAlgorithmProvider")
    try:
        chaining_mode = create_unicode_buffer("ChainingModeGCM")
        status = bcrypt.BCryptSetProperty(
            algorithm,
            c_wchar_p("ChainingMode"),
            c_void_p(addressof(chaining_mode)),
            sizeof(chaining_mode),
            0,
        )
        _check_status(status, "BCryptSetProperty")

        key_buffer = create_string_buffer(key)
        status = bcrypt.BCryptGenerateSymmetricKey(
            algorithm,
            byref(key_handle),
            None,
            0,
            key_buffer,
            len(key),
            0,
        )
        _check_status(status, "BCryptGenerateSymmetricKey")
        try:
            nonce_buffer = create_string_buffer(nonce)
            tag_buffer = create_string_buffer(tag)
            input_buffer = create_string_buffer(ciphertext)
            output_buffer = create_string_buffer(len(ciphertext))
            auth_info = AuthenticatedCipherModeInfo()
            auth_info.cbSize = sizeof(AuthenticatedCipherModeInfo)
            auth_info.dwInfoVersion = 1
            auth_info.pbNonce = c_void_p(addressof(nonce_buffer))
            auth_info.cbNonce = len(nonce)
            auth_info.pbTag = c_void_p(addressof(tag_buffer))
            auth_info.cbTag = len(tag)

            status = bcrypt.BCryptDecrypt(
                key_handle,
                input_buffer,
                len(ciphertext),
                byref(auth_info),
                None,
                0,
                output_buffer,
                len(ciphertext),
                byref(result_size),
                0,
            )
            _check_status(status, "BCryptDecrypt")
            return output_buffer.raw[: result_size.value]
        finally:
            bcrypt.BCryptDestroyKey(key_handle)
    finally:
        bcrypt.BCryptCloseAlgorithmProvider(algorithm, 0)

def _check_status(status: int, operation: str) -> None:
    if status < 0:
        raise OSError(f"{operation} failed with status {status:#x}")
