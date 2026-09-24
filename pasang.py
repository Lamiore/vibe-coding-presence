#!/usr/bin/env python3
"""Pemasang lagi-ngapain untuk macOS dan Windows.

    python3 pasang.py [APPLICATION_ID]     # macOS
    py pasang.py [APPLICATION_ID]          # Windows
    python3 pasang.py --copot              # cabut lagi

Linux tetap lewat ./pasang.sh (systemd). Hook alat lain di settings.json
tidak disentuh.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DIR))

import cc_daemon
import cc_konfig
import cc_layanan
import cc_pasang
import cc_sampul

HOOK = DIR / "hooks" / "lagi-ngapain-hook.py"


def say(*a) -> None:
    print("  " + " ".join(str(x) for x in a))


def python_hook() -> str:
    # Windows: python.exe dengan jalur mutlak -- "python" telanjang bisa
    # jatuh ke alias Microsoft Store yang cuma membuka toko.
    return cc_layanan.python_mac() if sys.platform == "darwin" else sys.executable


def copot() -> int:
    say(cc_layanan.copot())
    say(cc_pasang.copot()[1])
    # Singgahan sampul murni turunan -- beda dengan konfig, tidak ada yang
    # hilang kalau dibuang.
    shutil.rmtree(cc_sampul.jalur_singgahan().parent, ignore_errors=True)
    print(f"Dicopot. Konfig di {cc_konfig.jalur_konfig().parent} sengaja dibiarkan.")
    return 0


def main(argv: list[str]) -> int:
    if sys.platform not in ("darwin", "win32"):
        print("Di Linux pakai ./pasang.sh (systemd).")
        return 1
    if argv[:1] == ["--copot"]:
        return copot()

    print("==> Konfigurasi")
    cid = (argv[0] if argv else "") or cc_konfig.muat()["client_id"]
    if not cid:
        print()
        say("Application ID Discord belum ada. Bikin dulu:")
        say("  1. buka https://discord.com/developers/applications")
        say("  2. New Application, namai mis.: Terminal")
        say("     (nama aplikasi ini jadi baris paling atas di presence;")
        say('      "Claude Code" ditolak Discord karena nama merek)')
        say("  3. salin Application ID di halaman General Information")
        print()
        cid = input("  Tempel Application ID di sini: ")
    cid = cid.strip()
    if not cid:
        print("Application ID wajib diisi.")
        return 1
    return pasang_semua(cid)


def pasang_semua(cid: str) -> int:
    """Konfig, hook, dan autostart sekaligus; dipakai juga oleh atur.py."""
    cfg = cc_konfig.muat()
    cfg["client_id"] = cid
    say("konfig:", cc_konfig.simpan(cfg))
    say("mode privasi:", cfg["mode"])

    print("==> Hook Claude Code")
    # Dicopot dulu supaya jalur python atau repo yang berubah ikut diperbarui;
    # pasang() sendiri tidak menimpa entri yang sudah ada.
    cc_pasang.copot()
    ok, pesan = cc_pasang.pasang(python_hook(),
                                 args=["-I", "-S", str(HOOK), str(cc_daemon.dir_spool())])
    say(pesan)
    say("settings:", cc_pasang.jalur_settings())
    if not ok:
        return 1

    print("==> Autostart")
    say(cc_layanan.pasang())

    print()
    print("Selesai. Presence muncul dalam ~15 detik.")
    say("Sesi Claude Code yang sedang jalan ikut terpantau -- settings.json")
    say("dibaca ulang saat itu juga, jadi tidak perlu dibuka ulang.")
    if sys.platform == "darwin":
        say("Pertama kali lagu dibaca, macOS menanyakan izin python3 mengendalikan")
        say("Spotify/Music -- izinkan, atau tampilan lagunya tetap kosong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
