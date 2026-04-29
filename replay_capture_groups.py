#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path

from ftdi_compat import Ftdi
from scapy_ftdi import iterate_ftdi_usb_capture


def collect_groups(pcap_path: Path) -> list[tuple[bytes, bytes]]:
    groups: list[tuple[bytes, bytes]] = []
    outbuf = bytearray()
    inbuf = bytearray()

    for xfer in iterate_ftdi_usb_capture(str(pcap_path)):
        outbuf.extend(bytes([xfer.cmd]) + xfer.arg)
        inbuf.extend(xfer.rsp)
        if xfer.cmd == 0x87:
            groups.append((bytes(outbuf), bytes(inbuf)))
            outbuf.clear()
            inbuf.clear()

    if outbuf:
        groups.append((bytes(outbuf), bytes(inbuf)))
    return groups


def read_exact(ftdi: Ftdi, expected: int, timeout_s: float = 2.0) -> bytes:
    deadline = time.monotonic() + timeout_s
    data = bytearray()
    while len(data) < expected and time.monotonic() < deadline:
        chunk = ftdi.read_data(expected - len(data))
        if chunk:
            data.extend(chunk)
        else:
            time.sleep(0.001)
    return bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pcap")
    parser.add_argument("--start-group", type=int, default=0)
    parser.add_argument("--num-groups", type=int, default=10)
    parser.add_argument(
        "--preinit",
        choices=("none", "memtool", "full"),
        default="none",
        help="Apply a small live adapter pre-initialization before replay.",
    )
    args = parser.parse_args()

    groups = collect_groups(Path(args.pcap))
    print(f"parsed {len(groups)} groups")

    ftdi = Ftdi()
    ftdi.open_mpsse(0x58B, 0x43, interface=1)
    ftdi.set_latency_timer(2)
    ftdi.set_flowctrl("hw")
    ftdi.set_rts(True)
    ftdi.set_bitmode(0, Ftdi.BitMode.RESET)
    ftdi.set_bitmode(0, Ftdi.BitMode.MPSSE)

    try:
        if args.preinit == "memtool":
            # This gets the live GPIO state much closer to what the capture
            # shows at the first visible MemTool commands.
            ftdi.write_data(bytes.fromhex("8257f78080db87"))
            _ = read_exact(ftdi, 0)
        elif args.preinit == "full":
            ftdi.write_data(bytes.fromhex("aaab87"))
            _ = read_exact(ftdi, 4)
            ftdi.write_data(bytes.fromhex("8a978d8257f78080db87"))
            _ = read_exact(ftdi, 0)

        for group_index in range(args.start_group, min(args.start_group + args.num_groups, len(groups))):
            outbuf, expected = groups[group_index]
            ftdi.write_data(outbuf)
            actual = read_exact(ftdi, len(expected))
            ok = actual == expected
            print(
                f"group {group_index:03d}: "
                f"tx={len(outbuf)} bytes rx={len(actual)}/{len(expected)} "
                f"{'OK' if ok else 'MISMATCH'}"
            )
            if not ok:
                print(f"  expected={expected.hex()}")
                print(f"  actual  ={actual.hex()}")
                break
    finally:
        ftdi.close()


if __name__ == "__main__":
    main()
