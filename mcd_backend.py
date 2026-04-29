from __future__ import annotations

import ctypes as ct
import struct
from dataclasses import dataclass
from pathlib import Path


MCD_API_MAJOR = 1
MCD_API_MINOR = 1
MCD_API_AUTHOR = b"SPRINT Release"

MCD_API_IMP_VENDOR_LEN = 32
MCD_UNIQUE_NAME_LEN = 64
MCD_HOSTNAME_LEN = 64
MCD_KEY_LEN = 64
MCD_INFO_STR_LEN = 256
MCD_MEM_SPACE_NAME_LEN = 32

MCD_NOTUSED_ID = 0
MCD_TX_AT_R = 0x00000001
MCD_TX_AT_W = 0x00000002


class McdApiVersion(ct.Structure):
    _fields_ = [
        ("v_api_major", ct.c_uint16),
        ("v_api_minor", ct.c_uint16),
        ("author", ct.c_char * MCD_API_IMP_VENDOR_LEN),
    ]


class McdImplVersionInfo(ct.Structure):
    _fields_ = [
        ("v_api", McdApiVersion),
        ("v_imp_major", ct.c_uint16),
        ("v_imp_minor", ct.c_uint16),
        ("v_imp_build", ct.c_uint16),
        ("vendor", ct.c_char * MCD_API_IMP_VENDOR_LEN),
        ("date", ct.c_char * 16),
    ]


class McdServer(ct.Structure):
    _fields_ = [
        ("instance", ct.c_void_p),
        ("host", ct.c_char_p),
        ("config_string", ct.c_char_p),
    ]


class McdCoreConInfo(ct.Structure):
    _fields_ = [
        ("host", ct.c_char * MCD_HOSTNAME_LEN),
        ("server_port", ct.c_uint32),
        ("server_key", ct.c_char * MCD_KEY_LEN),
        ("system_key", ct.c_char * MCD_KEY_LEN),
        ("device_key", ct.c_char * MCD_KEY_LEN),
        ("system", ct.c_char * MCD_UNIQUE_NAME_LEN),
        ("system_instance", ct.c_char * MCD_UNIQUE_NAME_LEN),
        ("acc_hw", ct.c_char * MCD_UNIQUE_NAME_LEN),
        ("device_type", ct.c_uint32),
        ("device", ct.c_char * MCD_UNIQUE_NAME_LEN),
        ("device_id", ct.c_uint32),
        ("core", ct.c_char * MCD_UNIQUE_NAME_LEN),
        ("core_type", ct.c_uint32),
        ("core_id", ct.c_uint32),
    ]


class McdCore(ct.Structure):
    _fields_ = [
        ("instance", ct.c_void_p),
        ("core_con_info", ct.POINTER(McdCoreConInfo)),
    ]


class McdMemSpace(ct.Structure):
    _fields_ = [
        ("mem_space_id", ct.c_uint32),
        ("mem_space_name", ct.c_char * MCD_MEM_SPACE_NAME_LEN),
        ("mem_type", ct.c_uint32),
        ("bits_per_mau", ct.c_uint32),
        ("invariance", ct.c_uint8),
        ("endian", ct.c_uint32),
        ("min_addr", ct.c_uint64),
        ("max_addr", ct.c_uint64),
        ("num_mem_blocks", ct.c_uint32),
        ("supported_access_options", ct.c_uint32),
        ("core_mode_mask_read", ct.c_uint32),
        ("core_mode_mask_write", ct.c_uint32),
    ]


class McdAddr(ct.Structure):
    _fields_ = [
        ("address", ct.c_uint64),
        ("mem_space_id", ct.c_uint32),
        ("addr_space_id", ct.c_uint32),
        ("addr_space_type", ct.c_uint32),
    ]


class McdTx(ct.Structure):
    _fields_ = [
        ("addr", McdAddr),
        ("access_type", ct.c_uint32),
        ("options", ct.c_uint32),
        ("access_width", ct.c_uint8),
        ("core_mode", ct.c_uint8),
        ("data", ct.POINTER(ct.c_uint8)),
        ("num_bytes", ct.c_uint32),
        ("num_bytes_ok", ct.c_uint32),
    ]


class McdTxList(ct.Structure):
    _fields_ = [
        ("tx", ct.POINTER(McdTx)),
        ("num_tx", ct.c_uint32),
        ("num_tx_ok", ct.c_uint32),
    ]


@dataclass
class CoreSelection:
    system: McdCoreConInfo
    device: McdCoreConInfo
    core: McdCoreConInfo


def decode_c_string(buffer: bytes) -> str:
    return buffer.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")


def default_mcd_dll() -> Path:
    candidates = [
        Path(r"C:\Program Files\DAS64\clients\mcdxdas.dll"),
        Path(r"C:\Program Files\DAS64\win32\mcdxdas.dll"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not locate mcdxdas.dll in the default DAS64 install paths.")


def mcd_backend_available() -> bool:
    try:
        default_mcd_dll()
    except FileNotFoundError:
        return False
    return True


class McdApi:
    def __init__(self, dll_path: Path) -> None:
        self.dll = ct.CDLL(str(dll_path))
        self._bind()

    def _bind(self) -> None:
        self.dll.mcd_initialize_f.argtypes = [ct.POINTER(McdApiVersion), ct.POINTER(McdImplVersionInfo)]
        self.dll.mcd_initialize_f.restype = ct.c_uint32

        self.dll.mcd_open_server_f.argtypes = [ct.c_char_p, ct.c_char_p, ct.POINTER(ct.POINTER(McdServer))]
        self.dll.mcd_open_server_f.restype = ct.c_uint32

        self.dll.mcd_qry_systems_f.argtypes = [ct.c_uint32, ct.POINTER(ct.c_uint32), ct.POINTER(McdCoreConInfo)]
        self.dll.mcd_qry_systems_f.restype = ct.c_uint32

        self.dll.mcd_qry_devices_f.argtypes = [
            ct.POINTER(McdCoreConInfo),
            ct.c_uint32,
            ct.POINTER(ct.c_uint32),
            ct.POINTER(McdCoreConInfo),
        ]
        self.dll.mcd_qry_devices_f.restype = ct.c_uint32

        self.dll.mcd_qry_cores_f.argtypes = [
            ct.POINTER(McdCoreConInfo),
            ct.c_uint32,
            ct.POINTER(ct.c_uint32),
            ct.POINTER(McdCoreConInfo),
        ]
        self.dll.mcd_qry_cores_f.restype = ct.c_uint32

        self.dll.mcd_open_core_f.argtypes = [ct.POINTER(McdCoreConInfo), ct.POINTER(ct.POINTER(McdCore))]
        self.dll.mcd_open_core_f.restype = ct.c_uint32

        self.dll.mcd_qry_rst_classes_f.argtypes = [ct.POINTER(McdCore), ct.POINTER(ct.c_uint32)]
        self.dll.mcd_qry_rst_classes_f.restype = ct.c_uint32

        self.dll.mcd_rst_f.argtypes = [ct.POINTER(McdCore), ct.c_uint32, ct.c_uint32]
        self.dll.mcd_rst_f.restype = ct.c_uint32

        self.dll.mcd_run_f.argtypes = [ct.POINTER(McdCore), ct.c_uint32]
        self.dll.mcd_run_f.restype = ct.c_uint32

        self.dll.mcd_stop_f.argtypes = [ct.POINTER(McdCore), ct.c_uint32]
        self.dll.mcd_stop_f.restype = ct.c_uint32

        self.dll.mcd_qry_mem_spaces_f.argtypes = [
            ct.POINTER(McdCore),
            ct.c_uint32,
            ct.POINTER(ct.c_uint32),
            ct.POINTER(McdMemSpace),
        ]
        self.dll.mcd_qry_mem_spaces_f.restype = ct.c_uint32

        self.dll.mcd_execute_txlist_f.argtypes = [ct.POINTER(McdCore), ct.POINTER(McdTxList)]
        self.dll.mcd_execute_txlist_f.restype = ct.c_uint32

        self.dll.mcd_close_core_f.argtypes = [ct.POINTER(McdCore)]
        self.dll.mcd_close_core_f.restype = ct.c_uint32

        self.dll.mcd_close_server_f.argtypes = [ct.POINTER(McdServer)]
        self.dll.mcd_close_server_f.restype = ct.c_uint32

        self.dll.mcd_exit_f.argtypes = []
        self.dll.mcd_exit_f.restype = None

    @staticmethod
    def _check(rc: int, action: str) -> None:
        if rc != 0:
            raise RuntimeError(f"{action} failed with MCD return code 0x{rc:08x}")

    def initialize(self) -> McdImplVersionInfo:
        version = McdApiVersion()
        version.v_api_major = MCD_API_MAJOR
        version.v_api_minor = MCD_API_MINOR
        version.author = MCD_API_AUTHOR

        impl = McdImplVersionInfo()
        self._check(self.dll.mcd_initialize_f(ct.byref(version), ct.byref(impl)), "mcd_initialize_f")
        return impl

    def open_server(self, config: str) -> ct.POINTER(McdServer):
        server = ct.POINTER(McdServer)()
        self._check(
            self.dll.mcd_open_server_f(b"", config.encode("utf-8"), ct.byref(server)),
            "mcd_open_server_f",
        )
        return server

    def query_systems(self) -> list[McdCoreConInfo]:
        count = ct.c_uint32(0)
        self._check(self.dll.mcd_qry_systems_f(0, ct.byref(count), None), "mcd_qry_systems_f(count)")
        if count.value == 0:
            return []
        items = (McdCoreConInfo * count.value)()
        self._check(self.dll.mcd_qry_systems_f(0, ct.byref(count), items), "mcd_qry_systems_f")
        return list(items[: count.value])

    def query_devices(self, system: McdCoreConInfo) -> list[McdCoreConInfo]:
        count = ct.c_uint32(0)
        self._check(
            self.dll.mcd_qry_devices_f(ct.byref(system), 0, ct.byref(count), None),
            "mcd_qry_devices_f(count)",
        )
        if count.value == 0:
            return []
        items = (McdCoreConInfo * count.value)()
        self._check(
            self.dll.mcd_qry_devices_f(ct.byref(system), 0, ct.byref(count), items),
            "mcd_qry_devices_f",
        )
        return list(items[: count.value])

    def query_cores(self, device: McdCoreConInfo) -> list[McdCoreConInfo]:
        count = ct.c_uint32(0)
        self._check(
            self.dll.mcd_qry_cores_f(ct.byref(device), 0, ct.byref(count), None),
            "mcd_qry_cores_f(count)",
        )
        if count.value == 0:
            return []
        items = (McdCoreConInfo * count.value)()
        self._check(
            self.dll.mcd_qry_cores_f(ct.byref(device), 0, ct.byref(count), items),
            "mcd_qry_cores_f",
        )
        return list(items[: count.value])

    def open_core(self, core_info: McdCoreConInfo) -> ct.POINTER(McdCore):
        core = ct.POINTER(McdCore)()
        self._check(self.dll.mcd_open_core_f(ct.byref(core_info), ct.byref(core)), "mcd_open_core_f")
        return core

    def query_reset_classes(self, core: ct.POINTER(McdCore)) -> int:
        vector = ct.c_uint32()
        self._check(self.dll.mcd_qry_rst_classes_f(core, ct.byref(vector)), "mcd_qry_rst_classes_f")
        return vector.value

    def reset(self, core: ct.POINTER(McdCore), vector: int, halt_after_reset: bool) -> None:
        self._check(
            self.dll.mcd_rst_f(core, vector, 1 if halt_after_reset else 0),
            "mcd_rst_f",
        )

    def run(self, core: ct.POINTER(McdCore), global_run: bool = True) -> None:
        self._check(self.dll.mcd_run_f(core, 1 if global_run else 0), "mcd_run_f")

    def stop(self, core: ct.POINTER(McdCore), global_stop: bool = True) -> None:
        self._check(self.dll.mcd_stop_f(core, 1 if global_stop else 0), "mcd_stop_f")

    def query_mem_spaces(self, core: ct.POINTER(McdCore)) -> list[McdMemSpace]:
        count = ct.c_uint32(0)
        self._check(
            self.dll.mcd_qry_mem_spaces_f(core, 0, ct.byref(count), None),
            "mcd_qry_mem_spaces_f(count)",
        )
        if count.value == 0:
            return []
        items = (McdMemSpace * count.value)()
        self._check(
            self.dll.mcd_qry_mem_spaces_f(core, 0, ct.byref(count), items),
            "mcd_qry_mem_spaces_f",
        )
        return list(items[: count.value])

    def execute_txlist(self, core: ct.POINTER(McdCore), txlist: McdTxList) -> None:
        self._check(self.dll.mcd_execute_txlist_f(core, ct.byref(txlist)), "mcd_execute_txlist_f")

    def close_core(self, core: ct.POINTER(McdCore)) -> None:
        self._check(self.dll.mcd_close_core_f(core), "mcd_close_core_f")

    def close_server(self, server: ct.POINTER(McdServer)) -> None:
        self._check(self.dll.mcd_close_server_f(server), "mcd_close_server_f")

    def exit(self) -> None:
        self.dll.mcd_exit_f()


def select_target(
    api: McdApi,
    system_index: int,
    device_index: int,
    core_index: int,
) -> CoreSelection:
    systems = api.query_systems()
    if system_index >= len(systems):
        raise IndexError(f"System index {system_index} is out of range (found {len(systems)} systems).")

    devices = api.query_devices(systems[system_index])
    if device_index >= len(devices):
        raise IndexError(f"Device index {device_index} is out of range (found {len(devices)} devices).")

    cores = api.query_cores(devices[device_index])
    if core_index >= len(cores):
        raise IndexError(f"Core index {core_index} is out of range (found {len(cores)} cores).")

    return CoreSelection(systems[system_index], devices[device_index], cores[core_index])


class McdSession:
    def __init__(
        self,
        dll_path: Path | None = None,
        server_config: str = "",
        system_index: int = 0,
        device_index: int = 0,
        core_index: int = 0,
    ) -> None:
        self._dll_path = dll_path or default_mcd_dll()
        self._server_config = server_config
        self._system_index = system_index
        self._device_index = device_index
        self._core_index = core_index

        self.api = McdApi(self._dll_path)
        self.impl: McdImplVersionInfo | None = None
        self.server: ct.POINTER(McdServer) | None = None
        self.selection: CoreSelection | None = None
        self.core: ct.POINTER(McdCore) | None = None
        self.mem_spaces: list[McdMemSpace] = []

    @classmethod
    def connect_default(cls) -> "McdSession":
        session = cls()
        session.open()
        return session

    @property
    def device_name(self) -> str:
        if self.selection is None:
            return ""
        return decode_c_string(self.selection.device.device)

    @property
    def core_name(self) -> str:
        if self.selection is None:
            return ""
        return decode_c_string(self.selection.core.core)

    def open(self) -> None:
        self.impl = self.api.initialize()
        self.server = self.api.open_server(self._server_config)
        self.selection = select_target(
            self.api,
            self._system_index,
            self._device_index,
            self._core_index,
        )
        self.core = self.api.open_core(self.selection.core)
        self.mem_spaces = self.api.query_mem_spaces(self.core)
        if not self.mem_spaces:
            raise RuntimeError("The selected core does not expose any memory spaces through the MCD API.")

    def reset_and_halt(self) -> None:
        if self.core is None:
            raise RuntimeError("MCD session is not open.")
        reset_vector = self.api.query_reset_classes(self.core)
        self.api.reset(self.core, reset_vector, halt_after_reset=True)

    def run_global(self) -> None:
        if self.core is None:
            raise RuntimeError("MCD session is not open.")
        self.api.run(self.core, global_run=True)

    def stop_global(self) -> None:
        if self.core is None:
            raise RuntimeError("MCD session is not open.")
        self.api.stop(self.core, global_stop=True)

    def _resolve_mem_space(self, address: int, size: int) -> McdMemSpace:
        end_address = address + max(size, 1) - 1
        for mem_space in self.mem_spaces:
            if mem_space.min_addr <= address <= mem_space.max_addr and end_address <= mem_space.max_addr:
                return mem_space
        raise ValueError(f"No MCD memory space covers 0x{address:08x}..0x{end_address:08x}.")

    @staticmethod
    def _best_access_width(address: int, remaining: int) -> int:
        if remaining >= 4 and address % 4 == 0:
            return 4
        if remaining >= 2 and address % 2 == 0:
            return 2
        return 1

    def _transfer(self, address: int, size: int, write_data: bytes | None = None) -> bytes:
        if self.core is None:
            raise RuntimeError("MCD session is not open.")
        if size <= 0:
            return b""

        mem_space = self._resolve_mem_space(address, size)
        output = bytearray()
        offset = 0

        while offset < size:
            chunk_addr = address + offset
            remaining = size - offset
            access_width = self._best_access_width(chunk_addr, remaining)
            chunk_size = min(remaining, 0x4000)
            chunk_size -= chunk_size % access_width
            if chunk_size == 0:
                chunk_size = access_width

            if write_data is None:
                buf = (ct.c_uint8 * chunk_size)()
            else:
                chunk = write_data[offset:offset + chunk_size]
                buf = (ct.c_uint8 * chunk_size).from_buffer_copy(chunk)

            tx = McdTx(
                addr=McdAddr(chunk_addr, mem_space.mem_space_id, 0, MCD_NOTUSED_ID),
                access_type=MCD_TX_AT_W if write_data is not None else MCD_TX_AT_R,
                options=0,
                access_width=access_width,
                core_mode=0,
                data=ct.cast(buf, ct.POINTER(ct.c_uint8)),
                num_bytes=chunk_size,
                num_bytes_ok=0,
            )
            txlist = McdTxList(ct.pointer(tx), 1, 0)
            self.api.execute_txlist(self.core, txlist)

            if txlist.num_tx_ok != 1 or tx.num_bytes_ok != chunk_size:
                raise RuntimeError(
                    "Incomplete MCD transaction "
                    f"(tx_ok={txlist.num_tx_ok}, bytes_ok={tx.num_bytes_ok}, expected={chunk_size})."
                )

            if write_data is None:
                output.extend(bytes(buf))

            offset += chunk_size

        return bytes(output)

    def read(self, address: int, size: int) -> bytes:
        return self._transfer(address, size, write_data=None)

    def write(self, address: int, data: bytes) -> None:
        self._transfer(address, len(data), write_data=data)

    def read8(self, address: int) -> int:
        return self.read(address, 1)[0]

    def read16(self, address: int) -> int:
        return struct.unpack("<H", self.read(address, 2))[0]

    def read32(self, address: int) -> int:
        return struct.unpack("<I", self.read(address, 4))[0]

    def write8(self, address: int, value: int) -> None:
        self.write(address, bytes([value & 0xFF]))

    def write16(self, address: int, value: int) -> None:
        self.write(address, struct.pack("<H", value & 0xFFFF))

    def write32(self, address: int, value: int) -> None:
        self.write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def close(self) -> None:
        if self.core is not None:
            self.api.close_core(self.core)
            self.core = None
        if self.server is not None:
            self.api.close_server(self.server)
            self.server = None
        self.api.exit()
