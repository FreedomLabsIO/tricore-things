from __future__ import annotations

import base64
import json
import time
import zlib

from ftdi_compat import Ftdi


_CAPTURE_GROUPS_B85 = (
    "c-rk+(UR&Q4E-0M_aQ)l@GZ_hlmh?%2{%w%Yg^sAR@Yl$w9_FpIXN6MS~wmLP1AU?hp$88J"
    "O28^_t)`2jk6R;YMU$pLGUC<m2nN|)Qy?<jK?qEH)H?-NE+@DPBs7uK&iCt)xs&}DGnHp2_"
    "i9INNpl3I=dth*pjn=2U?fC0lnMI)NV7gyUk4QG_&i~1iLI-OCqX7`KpMbNZoyRWoznsSk>"
    "0X2rWM*+Kf3u#>_o-gnXoZU>?~`9P_{)VKh2zkmsYd=aYF*m4{hf`(z$u<ze#6%pju_J~P9J"
    "OB?WWA99Y;_IOK0&v-TJ(sCgmyq=yS$Q%*p+hXfOjIt4K@PL>84WwYyU>(g*j@4xEwhLu0QS"
    "_r!jz&&^#$R|T+@s|=0#R}o896BjBC;2GqD@}*EmYanIJz)kXpZA*q!C{cN#Sw?m1oNa+1fD"
    "JX>Mmp`$c>4j>@zb-V3sx2P&Y{NKn%rdDg?iKZ2W)dMiTtATOm6m*Y9NnM;)530eszf<EgjO"
    ")=lUI#!|liS6rIOc;%66FjR~<F(EYO3=~hp$@r?>(HMt*);EfXFWgNoJ`v|PN}1US1c~p&!N"
    "%^=qs(cT4|q`@wtBTniO=d18+1do8$SgD)nmCZdWO}=PI@8-CEUX)o9gd)o9gd)o9gd)o9g"
    "d)o9gd)o9gd)o9gd)o9gd)##HnYRc&isr9gjnC<hO#d0P?xYG;aJ6q?2XF|R08*y~JIVuqG"
    "+P>sX4<>t%C>=TNgGc=<FMG95c2bu171}V~cf`4V=pOr@_H0oLCM*4h|CP#2F7gpj>GJ`A`5"
    "xCze(#ParIR7rpuG=PuZbrgj@KVyz!$}9P7T}V$IJ8ApEMBo{P`<-38^%&uZj2S{5FgC|D59"
    "Z{s$tq31|"
)


def _load_capture_groups() -> tuple[tuple[bytes, bytes], ...]:
    payload = zlib.decompress(base64.b85decode(_CAPTURE_GROUPS_B85))
    raw_groups = json.loads(payload.decode("ascii"))
    return tuple((bytes.fromhex(tx), bytes.fromhex(rx)) for tx, rx in raw_groups)


MINIWIGGLER_MEMTOOL_UNLOCK_GROUPS = _load_capture_groups()
MINIWIGGLER_MEMTOOL_UNLOCK_PREAMBLE_GROUPS = MINIWIGGLER_MEMTOOL_UNLOCK_GROUPS[:76]


def _read_exact(ftdi: Ftdi, expected: int, timeout_s: float = 2.0) -> bytes:
    deadline = time.monotonic() + timeout_s
    data = bytearray()
    while len(data) < expected and time.monotonic() < deadline:
        chunk = ftdi.read_data(expected - len(data))
        if chunk:
            data.extend(chunk)
        else:
            time.sleep(0.001)
    return bytes(data)


def _group_label(index: int) -> str:
    if index <= 2:
        return "adapter init"
    if index <= 13:
        return "sync sweep"
    if index <= 16:
        return "attach"
    if index <= 73:
        return "lock probing"
    return "password preamble"


def replay_miniwiggler_memtool_unlock_preamble(
    ftdi: Ftdi,
    verbose: bool = False,
) -> None:
    # This sequence is the first 76 send-immediate groups from the known-good
    # MemTool password-unlock capture. It brings the MiniWiggler into the real
    # 0x080 "password expected" state without replaying the captured password
    # words, so the caller can inject the current UNLOCK_PASSWORD dynamically.
    for index, (tx, expected) in enumerate(MINIWIGGLER_MEMTOOL_UNLOCK_PREAMBLE_GROUPS):
        ftdi.write_data(tx)
        actual = _read_exact(ftdi, len(expected))
        if actual != expected:
            raise RuntimeError(
                "Capture-derived MiniWiggler unlock replay diverged at "
                f"group {index}: expected {expected.hex()} got {actual.hex()}"
            )
        if verbose:
            print(
                "unlock preamble "
                f"group {index:02d}/{len(MINIWIGGLER_MEMTOOL_UNLOCK_PREAMBLE_GROUPS) - 1:02d} "
                f"({_group_label(index)})"
            )
