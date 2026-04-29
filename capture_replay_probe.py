#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from scapy_ftdi import iterate_ftdi_usb_capture


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pcap")
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args()

    pcap_path = Path(args.pcap)
    for index, xfer in enumerate(iterate_ftdi_usb_capture(str(pcap_path))):
        cmdbuf = bytes([xfer.cmd]) + xfer.arg
        print(
            f"{index:04d}  t={xfer.time:9.6f}  "
            f"cmd={cmdbuf.hex()}  rsp={xfer.rsp.hex()}"
        )
        if index + 1 >= args.limit:
            break


if __name__ == "__main__":
    main()
