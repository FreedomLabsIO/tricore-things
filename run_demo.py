#!/usr/bin/env python3
import argparse
import os
import random
import struct
import time

from ftdi_compat import Ftdi
from mcd_backend import McdSession, mcd_backend_available
from miniwiggler_memtool_unlock import replay_miniwiggler_memtool_unlock_preamble

from ftdi_dap import (
    DAPBatch,
    DAPOperations,
    MiniWigglerBatch,
    TigardBatch,
    AssertInt,
    AssertNone,
)


SBU_ID = 0xf0036008
SBU_MANID = 0xf0036144
SBU_CHIPID = 0xf0036140
UCB_IFX = 0xaf101000
OCD_BASE = 0xf0000400
CPU0_CSFR_BASE = 0xf8810000
CPU1_CSFR_BASE = 0xf8830000
CPU2_CSFR_BASE = 0xf8850000
CPU3_CSFR_BASE = 0xf8870000
CPU4_CSFR_BASE = 0xf8890000
CPU6_CSFR_BASE = 0xf88d0000
CPU0_CSFR_DBGSR = 0xf881fd00
CPU0_CSFR_TR0EVT = 0xf881f000
CPU0_CSFR_TR0ADR = 0xf881f004


CMD_KEY_EXCHANGE = 0x76D6E24A

# PRO TIP: Upload your passwords to github to make sure you don't lose them!
UNLOCK_PASSWORD: None | list[int] = [
    0xCAFEBABE,
    0xDEADBEEF,
    0xAAAAAAAA,
    0x55555555,
    0x00000000,
    0xFFFFFFFF,
    0x00000000,
    0x00000000,
]

MINIWIGGLER_SYNC_SWEEP_A = bytes.fromhex(
    "f0033ff0033ff0033ff0033ff0033ff0033ff0033ff0033ff0033ff0033ff003"
    "3ff0033ff0033ff0033f70"
)
MINIWIGGLER_SYNC_SWEEP_B = bytes.fromhex(
    "f003c781e3f881e3388e1ff881e3f881e3c78f1ff88103077ee0c00f1c3870e0"
    "f871e0c771"
)
MINIWIGGLER_SYNC_SWEEP_C = bytes.fromhex("3f8e033ff0033ff0e3c071")
MINIWIGGLER_SYNC_PROBE = bytes.fromhex("801f3870fcf871")


def miniwiggler_sync(batch: DAPBatch, interface: MiniWigglerBatch) -> None:
    # MemTool does two families of slow sync sweeps before DAP answers. Those
    # sweeps are what the locked-board capture was missing from our old flow.
    for divisor in (5, 6, 4, 8, 3):
        interface.append(MiniWigglerBatch.GPIOH_INPUT)
        interface.append(MiniWigglerBatch.GPIOL_NORMAL)
        interface.append(MiniWigglerBatch.GPIOH_INPUT)
        interface.append(MiniWigglerBatch.GPIOL_NORMAL)
        interface.append(MiniWigglerBatch.GPIOH_INPUT)
        interface.append(MiniWigglerBatch.GPIOL_OPEN_CLK)
        interface.mpsse_set_clk_divisor(divisor)
        interface.append(MiniWigglerBatch.GPIOH_OUTPUT)
        interface.mpsse_clockout_bytes(MINIWIGGLER_SYNC_SWEEP_A)
        interface.append(MiniWigglerBatch.GPIOH_INPUT)
        interface.append(MiniWigglerBatch.GPIOH_OUTPUT)
        interface.mpsse_clockout_bytes(MINIWIGGLER_SYNC_PROBE)
        interface.append(MiniWigglerBatch.GPIOH_INPUT)
        interface.mpsse_clockin_bytes(30)
        interface.exec()

    for divisor in (5, 6, 4, 8, 3):
        interface.append(MiniWigglerBatch.GPIOH_INPUT)
        interface.append(MiniWigglerBatch.GPIOL_OPEN_CLK)
        interface.mpsse_set_clk_divisor(divisor)
        interface.append(MiniWigglerBatch.GPIOH_OUTPUT)
        interface.mpsse_clockout_bytes(MINIWIGGLER_SYNC_SWEEP_B)
        interface.append(MiniWigglerBatch.GPIOH_INPUT)
        interface.mpsse_clockin_bytes(20)
        interface.append(MiniWigglerBatch.GPIOH_OUTPUT)
        interface.mpsse_clockout_bytes(MINIWIGGLER_SYNC_SWEEP_C)
        interface.append(MiniWigglerBatch.GPIOH_INPUT)
        interface.mpsse_clockin_bytes(32)
        interface.exec()

    interface.append(MiniWigglerBatch.GPIOH_INPUT)
    interface.append(MiniWigglerBatch.GPIOL_NORMAL)
    batch.mpsse_set_clk_freq(400_000)
    interface.mpsse_clockout_bits(3, 0)
    interface.mpsse_clockout_bytes(b"\x00")
    sync = batch.dap_sync()
    batch.exec()
    if sync.value != 0xAAAAAAAA:
        raise RuntimeError(
            "MiniWiggler DAP sync did not respond after the capture-derived "
            "pre-init. Verify that the MiniWiggler debug interface is still "
            "bound to WinUSB and that no DAS/MemTool process is holding the "
            "adapter open."
        )


def miniwiggler_attach(batch: DAPBatch) -> None:
    batch.dap_dapisc(48, 0x4ABBAF530F00).then(AssertInt(0xF00))
    batch.dap_jtag_reset()
    batch.dap_jtag_swap_dr(0xAAAAAA83).then(AssertInt(0x201E9083))
    batch.dap_jtag_set_ir()
    batch.dap_jtag_swap_dr(0xAAAAAA83).then(AssertInt(0x201E9083))
    batch.exec()

    batch.mpsse_set_clk_freq(5_000_000)
    batch.dap_jtag_set_ir()
    batch.dap_jtag_swap_dr(0x00000000).then(AssertInt(0x201E9083))
    batch.dap_set_io_client(2)
    batch.dap_readreg(0xB, 2).then(AssertInt(0x0000))
    batch.dap_readreg(0xF, 2).then(AssertInt(0x0000))
    batch.dap_set_io_client(1)
    batch.exec()


def miniwiggler_wait_for_unlock_state(
    batch: DAPBatch,
    interface: MiniWigglerBatch,
) -> int:
    deadline = time.monotonic() + 0.22
    status = 0

    while time.monotonic() < deadline:
        batch.dap_set_io_client(1)
        current = batch.dap_readreg(0xB, 2)
        batch.exec()
        status = current.value or 0
        if status in (0x80, 0xC0, 0x400):
            return status
        time.sleep(0.01)

    # On locked boards MemTool performs one more low-level reset/open-clock
    # dance before re-issuing DAPISC(0400). That transition moves the target
    # from the intermediate 0xA0 state into the password handshake state.
    batch.mpsse_set_clk_freq(720_000)
    interface.append(MiniWigglerBatch.GPIOH_RESET)
    interface.append(MiniWigglerBatch.GPIOL_NORMAL)
    batch.exec()

    # MemTool keeps the transition into the password state in one send-immediate
    # window after the reset pulse instead of stopping at the intermediate 0xc0
    # status. Mirroring that batching matters on locked boards.
    interface.append(MiniWigglerBatch.GPIOH_INPUT)
    interface.append(MiniWigglerBatch.GPIOL_NORMAL)
    interface.append(MiniWigglerBatch.GPIOL_OPEN_CLK)
    interface.mpsse_clockout_bytes(b"\x00" * 25)
    interface.append(MiniWigglerBatch.GPIOL_NORMAL)
    interface.mpsse_clockout_bits(4, 0)
    batch.dap_dapisc(16, 0xF00).then(AssertNone())
    batch.dap_dapisc(48, 0x4ABBAF530400).then(AssertInt(0x400))
    batch.dap_set_io_client(1)
    status_before_ojconf = batch.dap_readreg(0xB, 2)
    batch.dap_write_ojconf(0x503)
    status_after_ojconf = batch.dap_readreg(0xB, 2)
    if UNLOCK_PASSWORD is not None:
        batch.write_comdata(CMD_KEY_EXCHANGE)
    samples = [batch.dap_readreg(0xB, 2) for _ in range(8)]
    batch.exec()
    sampled_statuses = [status_before_ojconf.value, status_after_ojconf.value]
    sampled_statuses.extend(s.value for s in samples)
    if 0x400 in sampled_statuses:
        return 0x400
    if 0x80 in sampled_statuses:
        return 0x80
    status = sampled_statuses[-1] or 0
    if status not in (0xA0, 0xC0):
        raise Exception(f"Unexpected post-reset DAP status: 0x{status:x}")
    return status


def read_dap_status(batch: DAPBatch) -> int:
    batch.dap_set_io_client(1)
    current = batch.dap_readreg(0xB, 2)
    batch.exec()
    return current.value or 0


def wait_for_dap_status(
    batch: DAPBatch,
    accepted: set[int],
    timeout_s: float = 0.25,
    poll_s: float = 0.01,
) -> int:
    deadline = time.monotonic() + timeout_s
    last = 0
    while time.monotonic() < deadline:
        last = read_dap_status(batch)
        if last in accepted:
            return last
        time.sleep(poll_s)
    raise TimeoutError(
        "Timed out waiting for DAP status in "
        + ", ".join(f"0x{x:03x}" for x in sorted(accepted))
        + f" (last=0x{last:03x})"
    )


def prefer_mcd_backend(use_miniwiggler: bool) -> bool:
    requested = os.environ.get("TRICORE_THINGS_BACKEND", "").strip().lower()
    if requested:
        if requested not in {"mcd", "mpsse"}:
            raise ValueError(
                "TRICORE_THINGS_BACKEND must be either 'mcd' or 'mpsse' "
                f"(got {requested!r})."
            )
        return requested == "mcd"
    return use_miniwiggler and os.name == "nt" and mcd_backend_available()


def open_ftdi_device(use_miniwiggler: bool) -> Ftdi:
    if use_miniwiggler:
        ftdi = Ftdi()
        ftdi.open_mpsse(0x58B, 0x43, interface=1)
    else:
        ftdi = Ftdi()
        ftdi.open_mpsse(0x403, 0x6010, interface=2)

    ftdi.set_latency_timer(2)
    ftdi.set_flowctrl("hw")
    ftdi.set_rts(True)
    ftdi.set_bitmode(0, Ftdi.BitMode.RESET)
    ftdi.set_bitmode(0, Ftdi.BitMode.MPSSE)
    assert ftdi.is_connected
    return ftdi


def pause_before_password_word(index: int, total: int) -> None:
    prompt = f"Press Enter to send password word {index}/{total}..."
    try:
        input(prompt)
    except EOFError as exc:
        raise RuntimeError(
            "--password-pause requires interactive stdin so each password "
            "word can wait for Enter."
        ) from exc


def open_raw_dap(
    use_miniwiggler: bool,
    verbose_unlock: bool = False,
    password_pause: bool = False,
) -> tuple[Ftdi, DAPOperations]:
    ftdi = open_ftdi_device(use_miniwiggler)

    if use_miniwiggler:
        interface = MiniWigglerBatch(ftdi)
    else:
        interface = TigardBatch(ftdi)

    batch = DAPBatch(interface)

    if use_miniwiggler:
        miniwiggler_sync(batch, interface)
        miniwiggler_attach(batch)
        dap_status = miniwiggler_wait_for_unlock_state(batch, interface)
    else:
        batch.test_reset()
        batch.mpsse_set_clk_freq(720_000)
        batch.reset()
        batch.exec()
        batch.dap_dapisc(16, 0xF00).then(AssertNone())
        batch.dap_dapisc(48, 0x4ABBAF530400).then(AssertInt(0x400))
        batch.dap_set_io_client(1)
        status = batch.dap_readreg(0xB, 2)
        batch.exec()
        dap_status = status.value or 0

    print(f"DAP status before unlock decision: 0x{dap_status:03x}")

    if dap_status == 0x400:
        print("DAP was already unlocked")
    else:
        if use_miniwiggler and UNLOCK_PASSWORD is not None:
            ftdi.close()
            ftdi = open_ftdi_device(True)
            replay_miniwiggler_memtool_unlock_preamble(
                ftdi,
                verbose=verbose_unlock,
            )
            interface = MiniWigglerBatch(ftdi, initialize=False)
            batch = DAPBatch(interface)
            batch.dap_set_io_client(1)
            password_state = batch.dap_readreg(0xB, 2)
            batch.exec()
            status_after_preamble = password_state.value or 0
            if verbose_unlock:
                print(
                    "unlock preamble complete, "
                    f"DAP status is 0x{status_after_preamble:03x}"
                )
            if status_after_preamble != 0x80:
                raise RuntimeError(
                    "Capture-derived MiniWiggler preamble did not reach the "
                    f"password-ready state, got 0x{status_after_preamble:03x}"
                )

            for index, pw in enumerate(UNLOCK_PASSWORD):
                if password_pause:
                    pause_before_password_word(index + 1, len(UNLOCK_PASSWORD))
                batch.dap_readreg(0xB, 2).then(AssertInt(0x80))
                batch.write_comdata(pw)
                batch.exec()
                if verbose_unlock:
                    print(
                        f"password word {index + 1}/{len(UNLOCK_PASSWORD)} "
                        "sent while DAP status was 0x080"
                    )

            batch.dap_set_io_client(2)
            batch.dap_readreg(0xB, 2).then(AssertInt(0x0000))
            batch.dap_readreg(0xF, 2).then(AssertInt(0x0000))
            batch.dap_set_io_client(1)
            final_status = batch.dap_readreg(0xB, 2)
            batch.exec()
            if (final_status.value or 0) != 0x400:
                raise RuntimeError(
                    "Unlock failed after the password sequence; "
                    f"final DAP status was 0x{(final_status.value or 0):03x}. "
                    "Check UNLOCK_PASSWORD."
                )

            print("Unlocked with capture-derived MiniWiggler sequence")
            print("DAP status after unlock handling: 0x400")
        else:
            if dap_status == 0xC0:
                batch.dap_write_ojconf(0x503)
                status_after_ojconf = batch.dap_readreg(0xB, 2)
                if UNLOCK_PASSWORD is not None:
                    # See "3.1.1.7.7 Debug System handling" in TC3xx User's Manual
                    batch.write_comdata(CMD_KEY_EXCHANGE)
                status_samples = [batch.dap_readreg(0xB, 2) for _ in range(8)]
                batch.exec()
                sampled_statuses = [status_after_ojconf.value] + [s.value for s in status_samples]
                if 0x80 not in sampled_statuses:
                    dap_status = wait_for_dap_status(batch, {0x80}, timeout_s=0.4)
                else:
                    dap_status = 0x80
                dap_status = 0x80
                print("DAP transitioned to password-unlock state: 0x080")

            if dap_status != 0x80:
                raise Exception(f"Unexpected status: 0x{dap_status:x}")

            print("DAP is locked, attempting unlock")
            assert UNLOCK_PASSWORD is not None
            batch.dap_set_io_client(1)
            batch.dap_readreg(0xB, 2).then(AssertInt(0x80))
            batch.exec()
            for index, pw in enumerate(UNLOCK_PASSWORD):
                if password_pause:
                    pause_before_password_word(index + 1, len(UNLOCK_PASSWORD))
                batch.dap_readreg(0xB, 2).then(AssertInt(0x80))
                batch.write_comdata(pw)
                batch.exec()
            batch.dap_set_io_client(2)
            batch.dap_readreg(0xB, 2).then(AssertInt(0x0000))
            batch.dap_readreg(0xF, 2).then(AssertInt(0x0000))
            batch.dap_set_io_client(1)
            batch.exec()
            batch.dap_set_io_client(1)
            batch.dap_readreg(0xB, 2).then(AssertInt(0x400))
            batch.exec()
            print("Unlocked")
            print("DAP status after unlock handling: 0x400")

    batch.dap_set_io_client(1)
    batch.dap_readreg(0xB, 2).then(AssertInt(0x400))
    batch.exec()

    batch.dap_set_io_client(1)
    batch.dap_readreg(0xB, 2).then(AssertInt(0x400))
    batch.dap_write_ojconf(0x4501)
    batch.dap_writereg_0(0xC1)
    batch.exec()

    batch.mpsse_set_clk_freq(5_000_000)
    batch.exec()

    return ftdi, DAPOperations(batch)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verbose-unlock",
        action="store_true",
        help=(
            "Print the capture-derived MiniWiggler unlock preamble progress "
            "and each password-word handoff."
        ),
    )
    parser.add_argument(
        "--password-pause",
        action="store_true",
        help=(
            "Wait for Enter before sending each 32-bit password word during "
            "unlock."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_self_test = True
    use_miniwiggler = True
    base_addr = 0x7000002C

    ftdi: Ftdi | None = None
    mcd_session: McdSession | None = None

    try:
        if prefer_mcd_backend(use_miniwiggler):
            mcd_session = McdSession.connect_default()
            mcd_session.reset_and_halt()
            ops = mcd_session
            print(f"Using backend: MCD ({mcd_session.device_name} / {mcd_session.core_name})")
        else:
            ftdi, ops = open_raw_dap(
                use_miniwiggler,
                verbose_unlock=args.verbose_unlock,
                password_pause=args.password_pause,
            )
            print("Using backend: raw MPSSE/DAP")

        if run_self_test:
            ref = random.randbytes(0x400)
            ops.write(base_addr, ref)
            readback = ops.read(base_addr, 0x400)
            assert readback == ref

            assert ops.read8(base_addr) == ref[0]
            assert ops.read8(base_addr + 1) == ref[1]
            assert ops.read8(base_addr + 2) == ref[2]
            assert ops.read8(base_addr + 3) == ref[3]
            assert ops.read16(base_addr) == struct.unpack("<H", ref[0:2])[0]
            assert ops.read16(base_addr + 2) == struct.unpack("<H", ref[2:4])[0]
            assert ops.read32(base_addr) == struct.unpack("<I", ref[0:4])[0]
            assert ops.read32(base_addr + 4) == struct.unpack("<I", ref[4:8])[0]

            ops.write8(base_addr, 0xA5)
            assert 0xA5 == ops.read8(base_addr)

            ops.write16(base_addr, 0xC0FE)
            assert 0xC0FE == ops.read16(base_addr)

            ops.write32(base_addr, 0xCAFEBABE)
            assert 0xCAFEBABE == ops.read32(base_addr)

            print("Self test completed successfully")
            return

        # Send Software Debug Event on CPU0
        ops.write32(0xF881FD10, 0x2A)
        # Halt all 6 CPUs
        ops.write32(0xF881FD00, 6)
        ops.write32(0xF883FD00, 6)
        ops.write32(0xF885FD00, 6)
        ops.write32(0xF887FD00, 6)
        ops.write32(0xF889FD00, 6)
        ops.write32(0xF88DFD00, 6)

        # Set program counter on first CPU.
        # 0x80000000 is the reset vector for running from flash.
        ops.write32(0xF881FE08, 0x80000000)

        # Run CPU0 by resetting HALT[0].
        # CPU0 will start other CPUs in the code running from flash.
        ops.write(0xF881FD00, b"\x04\x00\x00\x00")
        if mcd_session is not None:
            mcd_session.run_global()

        print(hex(ops.read32(0xF881FE08)))
        print(hex(ops.read32(0xF883FE08)))
        print(hex(ops.read32(0xF885FE08)))
        print(hex(ops.read32(0xF887FE08)))
        print(hex(ops.read32(0xF889FE08)))
        print(hex(ops.read32(0xF88DFE08)))

        import base64
        import zlib

        logo = zlib.decompress(
            base64.decodebytes(
                b"eJytlVty0zAUhhtZx7JiJ07SJDwALdMn2ADXcllAYQVAWQB7YB3cpsMwrFP9z5EtK/Kl"
                b"ZeBBo3P5P0mWj6Qvbqb+OKVOXaZ+O63uO1K/0E7QrtAeIHaFRtDt0Qj2T/EztUXTja+h"
                b"3aCx/0PihLwW/3vT7ySfBX/f9N+aceYuo3kSsy4niz6LYoUrqBBdpr42+qGYcXZSl46X"
                b"JfMWYS2cI6xPRes7/Kb0my+xV+fJvrxH/yLZuw+InSf762N+7z+if4n+FD3br5p/dIn2"
                b"GmOcoH2C/QbswuVoM6ypBkPqHfwzd6yeB3urnqF/K/ZOPQ32Xj0ZtHPsgznw5/Af/6PP"
                b"411M+A9l3jiWq0eDMZK+jdmG5dgGtbR0hs6iXAV/1+TXjqh0JeXojdPEMW9z3M/F+eNI"
                b"P3cLIvS52KzPxWZ9gfE5v4n01tWkR/Wsq2ndfHMt9bZq9Fo0sd7I+CtaHehzrCcn1Kas"
                b"yzMm2MavRTSHnP/OMS6Xubym44z4HaepSjiCrryB4+/zXCF2ytUy9xCnaZFwWv7pIbdE"
                b"3vvDTOZsb66Y4bk8Y8W+HaNRa75+Zqi7llOuDPvouQLn08o/Hee2qL2U0cjrwCnYdeA0"
                b"/L/nFObzXIV1GlUkbNWMPc2W2JuY5TPTZ9leBZbXxOwc/z0P7FJqYJrNMG/HGmV6rN8L"
                b"CiyFNXeslfqeZsuIs8R5Pt95xFTShhmN2iiRtz2mwFwxU4X/7xl/ZjrmrtQP18mYvozu"
                b"rb7eyP61DPbslkx7BmLGKOox/jzznaJuYBbu3iTDd90wo0XfMlk40+OMdctGH983Y/pC"
                b"/ssY074HfcaiJjzTvxNv4mrR9+/g/8F1fsd57TTLZ8JGrOG7Ss6JPwfdW9O9Ty17R94q"
                b"zlf+jou4VfIGtsxe8XuX6nXvzWz1O8Xv6SLSG9Gnb3Kr32IvFqjVQz2FN5/f505fuTXu"
                b"9JIuULufpX6Pjq4BJegSDg=="
            )
        )

        for i in range(0, len(logo), 1024):
            ops.write(base_addr + i, logo[i:i + 1024])

        print("All tests passed")
    finally:
        if ftdi is not None:
            ftdi.close()
        if mcd_session is not None:
            mcd_session.close()


if __name__ == "__main__":
    main()
