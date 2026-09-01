from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from typing import Protocol


class SecretProtectionError(RuntimeError):
    """Raised when a saved secret cannot be protected or recovered."""


class SecretProvider(Protocol):
    name: str
    available: bool

    def protect(self, value: str) -> str: ...

    def unprotect(self, value: str) -> str: ...


class UnavailableSecretProvider:
    name = "unavailable"
    available = False

    def protect(self, value: str) -> str:
        if not value:
            return ""
        raise SecretProtectionError("Secure local secret storage is unavailable on this platform.")

    def unprotect(self, value: str) -> str:
        if not value:
            return ""
        raise SecretProtectionError("The saved secret provider is unavailable on this platform.")


class WindowsDpapiSecretProvider:
    name = "windows_dpapi"
    available = os.name == "nt"

    _description = "Video Note Generator local settings"
    _entropy = b"video-note-generator.settings.v2"
    _cryptprotect_ui_forbidden = 0x01

    def protect(self, value: str) -> str:
        if not value:
            return ""
        if not self.available:
            raise SecretProtectionError("Windows DPAPI is unavailable.")
        encrypted = self._crypt_protect(value.encode("utf-8"))
        return base64.b64encode(encrypted).decode("ascii")

    def unprotect(self, value: str) -> str:
        if not value:
            return ""
        if not self.available:
            raise SecretProtectionError("Windows DPAPI is unavailable.")
        try:
            encrypted = base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise SecretProtectionError("The saved secret payload is invalid.") from exc
        try:
            return self._crypt_unprotect(encrypted).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecretProtectionError("The saved secret payload is invalid.") from exc

    def _crypt_protect(self, value: bytes) -> bytes:
        crypt32, kernel32, data_blob = _windows_crypto_api()
        input_buffer, input_blob = _blob_from_bytes(value, data_blob)
        entropy_buffer, entropy_blob = _blob_from_bytes(self._entropy, data_blob)
        output_blob = data_blob()
        _ = input_buffer, entropy_buffer
        succeeded = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            self._description,
            ctypes.byref(entropy_blob),
            None,
            None,
            self._cryptprotect_ui_forbidden,
            ctypes.byref(output_blob),
        )
        if not succeeded:
            raise SecretProtectionError(f"Windows DPAPI encryption failed ({ctypes.get_last_error()}).")
        return _copy_and_free_blob(output_blob, kernel32)

    def _crypt_unprotect(self, value: bytes) -> bytes:
        crypt32, kernel32, data_blob = _windows_crypto_api()
        input_buffer, input_blob = _blob_from_bytes(value, data_blob)
        entropy_buffer, entropy_blob = _blob_from_bytes(self._entropy, data_blob)
        output_blob = data_blob()
        _ = input_buffer, entropy_buffer
        succeeded = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            self._cryptprotect_ui_forbidden,
            ctypes.byref(output_blob),
        )
        if not succeeded:
            raise SecretProtectionError(f"Windows DPAPI decryption failed ({ctypes.get_last_error()}).")
        return _copy_and_free_blob(output_blob, kernel32)


def get_default_secret_provider() -> SecretProvider:
    if os.name == "nt":
        return WindowsDpapiSecretProvider()
    return UnavailableSecretProvider()


def _windows_crypto_api():
    if os.name != "nt":
        raise SecretProtectionError("Windows DPAPI is unavailable.")

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    return crypt32, kernel32, DataBlob


def _blob_from_bytes(value: bytes, data_blob):
    buffer = ctypes.create_string_buffer(value)
    blob = data_blob(
        len(value),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return buffer, blob


def _copy_and_free_blob(blob, kernel32) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if blob.pbData:
            kernel32.LocalFree(ctypes.cast(blob.pbData, wintypes.HLOCAL))
