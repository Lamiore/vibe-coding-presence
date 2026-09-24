"""Uji untuk hooks/lagi-ngapain-hook.py -- jalankan: python3 uji/uji_hook_py.py

Hook-nya dijalankan sungguhan sebagai proses, persis seperti Claude Code
memanggilnya lewat exec form: python -I -S <hook> <spool>.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "lagi-ngapain-hook.py"
MUATAN = b'{"session_id": "a", "hook_event_name": "Stop", "cwd": "/x/\xc3\xa9"}'


class UjiHookPython(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.spool = Path(d.name) / "lagi-ngapain" / "ev"
        self.spool.mkdir(parents=True)
        self.detak = self.spool.parent / "detak"

    def jalankan(self, muatan=MUATAN):
        hasil = subprocess.run([sys.executable, "-I", "-S", str(HOOK), str(self.spool)],
                               input=muatan, capture_output=True, timeout=30)
        self.assertEqual(hasil.returncode, 0, hasil.stderr)
        self.assertEqual(hasil.stdout, b"", "stdout hook dibaca Claude Code; harus kosong")
        return sorted(p.name for p in self.spool.iterdir()) if self.spool.exists() else []

    def test_detak_segar_muatan_ditulis_apa_adanya(self):
        self.detak.touch()
        nama = self.jalankan()
        self.assertEqual(len(nama), 1)
        self.assertEqual((self.spool / nama[0]).read_bytes(), MUATAN)
        # Bentuknya sama dengan versi bash: <EPOCHREALTIME>-<pid>.json
        self.assertRegex(nama[0], r"^\d{10}\.\d{6}-\d+\.json$")

    def test_urutan_nama_mengikuti_urutan_panggilan(self):
        self.detak.touch()
        pertama = self.jalankan()[0]
        kedua = [n for n in self.jalankan() if n != pertama][0]
        self.assertEqual(sorted([kedua, pertama]), [pertama, kedua])

    def test_detak_basi_hook_diam(self):
        # Daemon yang dibunuh paksa tidak sempat membereskan spool.
        self.detak.touch()
        os.utime(self.detak, (0, 0))
        self.assertEqual(self.jalankan(), [])

    def test_tanpa_detak_hook_diam(self):
        self.assertEqual(self.jalankan(), [])

    def test_spool_hilang_tidak_melempar(self):
        self.detak.touch()
        self.spool.rmdir()
        self.assertEqual(self.jalankan(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
