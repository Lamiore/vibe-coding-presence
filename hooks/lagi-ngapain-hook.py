"""Hook lagi-ngapain untuk macOS dan Windows: tulis muatan hook apa adanya ke spool.

Kembaran lagi-ngapain-hook.sh. bash bawaan macOS (3.2) tidak punya
EPOCHREALTIME, dan Windows belum tentu punya bash sama sekali, jadi di sana
Claude Code memanggil berkas ini lewat exec form -- tanpa shell:

    python -I -S lagi-ngapain-hook.py <folder spool>

-I -S melewati site-packages dan variabel lingkungan Python; ~25 ms per
tool call di Mac, dibanding ~4 ms versi bash. Tetap tidak ada JSON yang
diurai dan tidak ada soket: daemon yang mengerjakan semuanya.

Nama berkasnya <detik>.<mikrodetik>-<pid>.json, sama persis dengan versi
bash, jadi urutan nama tetap urutan waktu. Hook diam kalau detak daemon
basi: di Windows daemon yang dibunuh paksa tidak sempat membereskan spool,
dan tanpa pemeriksaan ini tiap tool call menumpuk satu berkas di sana.
"""

import os
import sys
import time

BASI = 30  # detik; daemon menyentuh berkas detak tiap denyut

try:
    spool = sys.argv[1]
    if time.time() - os.stat(os.path.join(os.path.dirname(spool), "detak")).st_mtime < BASI:
        with open(os.path.join(spool, f"{time.time():.6f}-{os.getpid()}.json"), "wb") as f:
            f.write(sys.stdin.buffer.read())
except (OSError, IndexError):
    pass  # daemon mati atau spool hilang: diam, jangan ganggu Claude Code
