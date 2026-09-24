#!/usr/bin/env python3
"""Menu terminal: Application ID dan saklar presence.

    presence             # sesudah dipasang sekali
    python3 atur.py      # Linux, macOS
    py atur.py           # Windows

Cuma pustaka baku, jadi menunya angka + input() biasa: curses tidak ada di
Python Windows. "Matiin" bertahan lewat restart -- lihat ``aktif`` di
cc_konfig. "Nyalain" yang pertama sekaligus memasang hook dan autostart.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DIR))

import cc_daemon
import cc_ipc
import cc_konfig
import cc_layanan
import cc_pasang

WARNA = False  # diputuskan di siapkan_terminal(): cuma kalau keluarannya terminal


# -- aksi -------------------------------------------------------------------

def id_sah(teks: str) -> bool:
    """Application ID Discord berupa snowflake: 17-20 digit angka."""
    teks = teks.strip()
    return teks.isascii() and teks.isdigit() and 17 <= len(teks) <= 20


def terpasang() -> bool:
    return bool(cc_pasang.terpasang()) and cc_layanan.terpasang()


def daemon_jalan() -> bool:
    """Dari detak, bukan dari proses: detak basi berarti daemonnya sudah mati."""
    detak = cc_daemon.dir_spool().parent / cc_daemon.DETAK
    try:
        return time.time() - detak.stat().st_mtime < 30
    except OSError:
        return False


def discord_kebuka() -> bool:
    """Ada Discord yang benar-benar mendengarkan.

    Berkas soket saja tidak cukup: di macOS ``discord-ipc-0`` tertinggal di
    $TMPDIR sesudah Discord ditutup.
    """
    for jalur in cc_ipc.cari_soket():
        try:
            cc_ipc.buka(jalur, 0.5).close()
            return True
        except OSError:
            continue
    return False


def keadaan() -> dict:
    cfg = cc_konfig.muat()
    return {"aktif": cfg["aktif"], "client_id": cfg["client_id"], "terpasang": terpasang(),
            "daemon": daemon_jalan(), "discord": discord_kebuka()}


def _simpan(**ubah) -> dict:
    cfg = cc_konfig.muat()
    cfg.update(ubah)
    cc_konfig.simpan(cfg)
    return cfg


def simpan_id(teks: str) -> tuple[bool, str]:
    cid = teks.strip()
    if not id_sah(cid):
        return False, "Application ID harus angka 17-20 digit (salin dari Developer Portal)"
    cfg = _simpan(client_id=cid)
    # Daemon membaca konfig sekali saat start. Presence yang sedang dimatikan
    # tidak ikut dinyalakan hanya karena ID-nya diganti.
    if cfg["aktif"] and terpasang():
        cc_layanan.muat_ulang()
    return True, "Application ID disimpan"


def _pasang(cid: str) -> bool:
    if sys.platform.startswith("linux"):
        return subprocess.run(["bash", str(DIR / "pasang.sh"), cid]).returncode == 0
    import pasang
    return pasang.pasang_semua(cid) == 0


def nyalakan() -> tuple[bool, str]:
    cid = cc_konfig.muat()["client_id"]
    if not cid:
        return False, "isi Application ID dulu (pilihan 1)"
    _simpan(aktif=True)
    ok = _pasang(cid) if not terpasang() else cc_layanan.muat_ulang()
    return (True, "presence dinyalakan") if ok else (False, "gagal menyalakan daemon -- cek log-nya")


def matikan() -> tuple[bool, str]:
    _simpan(aktif=False)
    if terpasang():
        # Daemon dibangunkan ulang, membaca aktif: false, lalu keluar dengan
        # rapi: presence dikosongkan dan hook kembali diam.
        cc_layanan.muat_ulang()
    return True, "presence dimatikan -- tetap mati walau PC di-restart"


# -- tampilan ---------------------------------------------------------------

def _w(kode: str, teks: str) -> str:
    return f"\033[{kode}m{teks}\033[0m" if WARNA else teks


def tampilkan(k: dict) -> None:
    garis = _w("2", "─" * 38)
    print()
    print(" " + _w("1", "vibe-coding-presence"))
    print(" " + garis)
    if not k["terpasang"]:
        presence = _w("33", "○ belum dipasang")
    elif k["aktif"]:
        presence = _w("32", "● nyala")
    else:
        presence = _w("31", "○ mati")
    for label, nilai in (
        ("Presence", presence),
        ("Daemon", "jalan" if k["daemon"] else _w("2", "berhenti")),
        ("Discord", "kebuka" if k["discord"] else _w("2", "belum kebuka")),
        ("App ID", k["client_id"] or _w("33", "(belum diisi)")),
    ):
        print(f" {label:<9} {nilai}")
    print(" " + garis)
    nyalain = "Nyalain presence" + ("" if k["terpasang"] else " (sekalian pasang)")
    for kunci, teks in (("1", "Masukin / ganti Application ID"), ("2", nyalain),
                        ("3", "Matiin presence"), ("q", "Keluar")):
        print(f"  {_w('1', kunci)}  {teks}")


def lapor(ok: bool, pesan: str) -> None:
    print("  " + (_w("32", "✓") if ok else _w("31", "✗")) + " " + pesan)


def minta_id() -> None:
    if not cc_konfig.muat()["client_id"]:
        print("  Bikin dulu di https://discord.com/developers/applications -> New Application")
        print('  (namai mis. "Terminal"), lalu salin Application ID di General Information.')
    lapor(*simpan_id(input("  Application ID: ")))


def _tunggu_daemon(harapan: bool, tenggat: float = 5.0) -> None:
    """Supaya tampilan berikutnya sudah memperlihatkan hasilnya, bukan keadaan lama."""
    batas = time.monotonic() + tenggat
    while daemon_jalan() != harapan and time.monotonic() < batas:
        time.sleep(0.2)


def siapkan_terminal() -> None:
    global WARNA
    for aliran in (sys.stdout, sys.stderr):
        if hasattr(aliran, "reconfigure"):
            aliran.reconfigure(errors="replace")
    WARNA = (sys.stdout.isatty() and not os.environ.get("NO_COLOR")
             and os.environ.get("TERM") != "dumb")
    if WARNA and sys.platform == "win32":
        # String kosong yang tetap -- tidak ada masukan luar yang lewat sini.
        # Efek sampingnya menyalakan kode warna ANSI di konsol Windows lama.
        os.system("")


def main() -> int:
    siapkan_terminal()
    try:
        while True:
            tampilkan(keadaan())
            pilihan = input(" > ").strip().lower()
            if pilihan == "q":
                return 0
            if pilihan == "1":
                minta_id()
            elif pilihan == "2":
                if not cc_konfig.muat()["client_id"]:
                    minta_id()
                if cc_konfig.muat()["client_id"]:
                    lapor(*nyalakan())
                    _tunggu_daemon(True)
            elif pilihan == "3":
                lapor(*matikan())
                _tunggu_daemon(False)
            elif pilihan:
                lapor(False, "pilih 1, 2, 3, atau q")
    except (EOFError, KeyboardInterrupt):
        print()
        if not sys.stdin.isatty():
            # Mis. dijalankan lewat "!" di Claude Code: tidak ada keyboard,
            # jadi menu tertutup sebelum sempat memilih apa pun.
            print("  menu ini butuh terminal interaktif -- buka jendela terminal biasa"
                  " lalu ketik: presence")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
