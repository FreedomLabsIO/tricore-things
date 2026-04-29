from __future__ import annotations

import ctypes as ct
import ctypes.util
from ctypes import wintypes as wt
from enum import IntEnum
import os
from pathlib import Path
import time
from typing import Any


_DLL_DIR_HANDLES: list[Any] = []


def _find_libusb_dll() -> Path | None:
    env_path = os.environ.get("TRICORE_THINGS_LIBUSB_DLL", "").strip()
    candidates = [
        Path(env_path) if env_path else None,
        Path(__file__).resolve().parent / "vendor" / "libusb-1.0.dll",
        Path.cwd() / "vendor" / "libusb-1.0.dll",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    try:
        import libusb_package
    except Exception:
        return None
    try:
        package_path = libusb_package.get_library_path()
    except Exception:
        return None
    if package_path is not None and package_path.is_file():
        return package_path
    return None


def _configure_pyusb_libusb() -> Path | None:
    dll_path = _find_libusb_dll()
    if dll_path is None:
        return None

    dll_dir = str(dll_path.parent)
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        try:
            _DLL_DIR_HANDLES.append(os.add_dll_directory(dll_dir))
        except OSError:
            pass
    os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")

    try:
        import usb.backend.libusb1 as libusb1
    except Exception:
        return dll_path

    original = getattr(libusb1, "_tricore_things_original_get_backend", None)
    if original is None:
        original = libusb1.get_backend
        libusb1._tricore_things_original_get_backend = original

    def _finder(candidate: str) -> str | None:
        lowered = candidate.lower()
        if lowered in {"usb-1.0", "libusb-1.0", "usb"}:
            return str(dll_path)
        return ctypes.util.find_library(candidate)

    def _tricore_things_get_backend(find_library=None):
        return original(find_library=find_library or _finder)

    libusb1.get_backend = _tricore_things_get_backend
    return dll_path


_LIBUSB_DLL = _configure_pyusb_libusb()

try:
    from pyftdi.ftdi import Ftdi as _PyFtdi
except Exception:
    _PyFtdi = None


class _BitMode(IntEnum):
    RESET = 0x00
    ASYNC_BITBANG = 0x01
    MPSSE = 0x02
    SYNC_BITBANG = 0x04
    MCU_HOST = 0x08
    FAST_SERIAL = 0x10
    CBUS_BITBANG = 0x20
    SYNC_FIFO = 0x40


class _D2xxBackend:
    FT_OK = 0
    FT_PURGE_RX = 1
    FT_PURGE_TX = 2
    FT_FLOW_NONE = 0x0000
    FT_FLOW_RTS_CTS = 0x0100

    def __init__(self) -> None:
        self._dll = self._load_dll()
        self._bind()
        self._handle: wt.HANDLE | None = None

    @staticmethod
    def _load_dll() -> Any:
        arch = "amd64" if ct.sizeof(ct.c_void_p) == 8 else "i386"
        candidates = [
            Path(rf"C:\Program Files\DAS64\others\driver\ftdi\{arch}\ftd2xx64.dll"),
            Path(rf"C:\Program Files\DAS64\others\driver\ftdi\{arch}\ftd2xx.dll"),
            Path("ftd2xx64.dll"),
            Path("ftd2xx.dll"),
        ]
        for candidate in candidates:
            try:
                return ct.WinDLL(str(candidate))
            except OSError:
                continue
        raise OSError("Could not load an FTDI D2XX DLL.")

    def _bind(self) -> None:
        self._dll.FT_CreateDeviceInfoList.argtypes = [ct.POINTER(wt.DWORD)]
        self._dll.FT_CreateDeviceInfoList.restype = wt.ULONG

        self._dll.FT_GetDeviceInfoDetail.argtypes = [
            wt.DWORD,
            ct.POINTER(wt.DWORD),
            ct.POINTER(wt.DWORD),
            ct.POINTER(wt.DWORD),
            ct.POINTER(wt.DWORD),
            ct.c_char_p,
            ct.c_char_p,
            ct.POINTER(wt.HANDLE),
        ]
        self._dll.FT_GetDeviceInfoDetail.restype = wt.ULONG

        self._dll.FT_Open.argtypes = [ct.c_int, ct.POINTER(wt.HANDLE)]
        self._dll.FT_Open.restype = wt.ULONG

        self._dll.FT_Close.argtypes = [wt.HANDLE]
        self._dll.FT_Close.restype = wt.ULONG

        self._dll.FT_ResetDevice.argtypes = [wt.HANDLE]
        self._dll.FT_ResetDevice.restype = wt.ULONG

        self._dll.FT_SetUSBParameters.argtypes = [wt.HANDLE, wt.ULONG, wt.ULONG]
        self._dll.FT_SetUSBParameters.restype = wt.ULONG

        self._dll.FT_SetChars.argtypes = [wt.HANDLE, ct.c_ubyte, ct.c_ubyte, ct.c_ubyte, ct.c_ubyte]
        self._dll.FT_SetChars.restype = wt.ULONG

        self._dll.FT_SetTimeouts.argtypes = [wt.HANDLE, wt.ULONG, wt.ULONG]
        self._dll.FT_SetTimeouts.restype = wt.ULONG

        self._dll.FT_SetLatencyTimer.argtypes = [wt.HANDLE, ct.c_ubyte]
        self._dll.FT_SetLatencyTimer.restype = wt.ULONG

        self._dll.FT_SetFlowControl.argtypes = [wt.HANDLE, wt.USHORT, ct.c_ubyte, ct.c_ubyte]
        self._dll.FT_SetFlowControl.restype = wt.ULONG

        self._dll.FT_SetRts.argtypes = [wt.HANDLE]
        self._dll.FT_SetRts.restype = wt.ULONG

        self._dll.FT_ClrRts.argtypes = [wt.HANDLE]
        self._dll.FT_ClrRts.restype = wt.ULONG

        self._dll.FT_SetBitMode.argtypes = [wt.HANDLE, ct.c_ubyte, ct.c_ubyte]
        self._dll.FT_SetBitMode.restype = wt.ULONG

        self._dll.FT_Purge.argtypes = [wt.HANDLE, wt.ULONG]
        self._dll.FT_Purge.restype = wt.ULONG

        self._dll.FT_Write.argtypes = [wt.HANDLE, ct.c_void_p, wt.DWORD, ct.POINTER(wt.DWORD)]
        self._dll.FT_Write.restype = wt.ULONG

        self._dll.FT_Read.argtypes = [wt.HANDLE, ct.c_void_p, wt.DWORD, ct.POINTER(wt.DWORD)]
        self._dll.FT_Read.restype = wt.ULONG

    @property
    def is_connected(self) -> bool:
        return self._handle is not None

    def _require_handle(self) -> wt.HANDLE:
        if self._handle is None:
            raise OSError("FTDI device is not open.")
        return self._handle

    def _call(self, status: int, action: str) -> None:
        if status != self.FT_OK:
            raise OSError(f"{action} failed with FT_STATUS {status}")

    def _matching_indices(self, vendor: int, product: int) -> list[int]:
        count = wt.DWORD()
        self._call(self._dll.FT_CreateDeviceInfoList(ct.byref(count)), "FT_CreateDeviceInfoList")
        device_id = ((vendor & 0xFFFF) << 16) | (product & 0xFFFF)
        matches: list[int] = []

        for index in range(count.value):
            flags = wt.DWORD()
            dev_type = wt.DWORD()
            dev_id = wt.DWORD()
            loc_id = wt.DWORD()
            serial = ct.create_string_buffer(16)
            desc = ct.create_string_buffer(64)
            handle = wt.HANDLE()
            self._call(
                self._dll.FT_GetDeviceInfoDetail(
                    index,
                    ct.byref(flags),
                    ct.byref(dev_type),
                    ct.byref(dev_id),
                    ct.byref(loc_id),
                    serial,
                    desc,
                    ct.byref(handle),
                ),
                f"FT_GetDeviceInfoDetail({index})",
            )
            if dev_id.value == device_id:
                matches.append(index)

        return matches

    def open_mpsse(self, vendor: int, product: int, interface: int = 1) -> None:
        matches = self._matching_indices(vendor, product)
        if not matches:
            raise OSError(f"No FTDI device found for VID:PID {vendor:04x}:{product:04x}")

        if interface < 1:
            raise OSError(f"Invalid FTDI interface {interface}")

        chosen = matches[min(interface - 1, len(matches) - 1)]
        handle = wt.HANDLE()
        self._call(self._dll.FT_Open(chosen, ct.byref(handle)), f"FT_Open({chosen})")
        self._handle = handle

        self._call(self._dll.FT_ResetDevice(handle), "FT_ResetDevice")
        self._call(self._dll.FT_SetUSBParameters(handle, 65536, 65536), "FT_SetUSBParameters")
        self._call(self._dll.FT_SetChars(handle, 0, 0, 0, 0), "FT_SetChars")
        self._call(self._dll.FT_SetTimeouts(handle, 2000, 2000), "FT_SetTimeouts")
        self._call(self._dll.FT_SetLatencyTimer(handle, 2), "FT_SetLatencyTimer")
        self._call(self._dll.FT_Purge(handle, self.FT_PURGE_RX | self.FT_PURGE_TX), "FT_Purge")

    def set_latency_timer(self, latency_ms: int) -> None:
        self._call(
            self._dll.FT_SetLatencyTimer(self._require_handle(), latency_ms),
            "FT_SetLatencyTimer",
        )

    def set_flowctrl(self, mode: str) -> None:
        if mode == "hw":
            flow = self.FT_FLOW_RTS_CTS
        elif mode in {"", "none"}:
            flow = self.FT_FLOW_NONE
        else:
            raise ValueError(f"Unsupported flow control mode: {mode}")
        self._call(
            self._dll.FT_SetFlowControl(self._require_handle(), flow, 0, 0),
            "FT_SetFlowControl",
        )

    def set_rts(self, enabled: bool) -> None:
        handle = self._require_handle()
        if enabled:
            self._call(self._dll.FT_SetRts(handle), "FT_SetRts")
        else:
            self._call(self._dll.FT_ClrRts(handle), "FT_ClrRts")

    def set_bitmode(self, mask: int, mode: int) -> None:
        handle = self._require_handle()
        self._call(self._dll.FT_SetBitMode(handle, mask, int(mode)), "FT_SetBitMode")
        if int(mode) == int(_BitMode.MPSSE):
            time.sleep(0.05)
            self._call(self._dll.FT_Purge(handle, self.FT_PURGE_RX | self.FT_PURGE_TX), "FT_Purge")

    def write_data(self, data: bytes) -> int:
        if not data:
            return 0
        handle = self._require_handle()
        buf = ct.create_string_buffer(data)
        written = wt.DWORD()
        self._call(
            self._dll.FT_Write(handle, buf, len(data), ct.byref(written)),
            "FT_Write",
        )
        return written.value

    def read_data(self, size: int) -> bytes:
        if size <= 0:
            return b""
        handle = self._require_handle()
        buf = (ct.c_ubyte * size)()
        got = wt.DWORD()
        self._call(self._dll.FT_Read(handle, buf, size, ct.byref(got)), "FT_Read")
        return bytes(buf[: got.value])

    def close(self) -> None:
        if self._handle is not None:
            self._call(self._dll.FT_Close(self._handle), "FT_Close")
            self._handle = None


class Ftdi:
    BitMode = _BitMode

    def __init__(self) -> None:
        self._backend: Any | None = None

    @property
    def is_connected(self) -> bool:
        return self._backend is not None and bool(getattr(self._backend, "is_connected", False))

    def open_mpsse(self, vendor: int, product: int, interface: int = 1) -> None:
        backend_preference = os.environ.get("TRICORE_THINGS_FTDI_BACKEND", "").lower()
        errors: list[str] = []

        if backend_preference != "d2xx" and _PyFtdi is not None:
            try:
                backend = _PyFtdi()
                backend.open_mpsse(vendor, product, interface=interface)
                self._backend = backend
                return
            except Exception as exc:
                errors.append(f"pyftdi: {exc}")

        try:
            backend = _D2xxBackend()
            backend.open_mpsse(vendor, product, interface=interface)
            self._backend = backend
            return
        except Exception as exc:
            errors.append(f"d2xx: {exc}")

        raise OSError("Unable to open FTDI MPSSE device. " + " | ".join(errors))

    def close(self) -> None:
        if self._backend is not None and hasattr(self._backend, "close"):
            self._backend.close()
        self._backend = None

    def __getattr__(self, name: str) -> Any:
        if self._backend is None:
            raise AttributeError(f"FTDI backend is not initialized: {name}")
        return getattr(self._backend, name)
