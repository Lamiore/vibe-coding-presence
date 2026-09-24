"""Uji untuk cc_layanan -- jalankan: python3 uji/uji_cc_layanan.py

launchctl dan registry tidak disentuh; yang diuji isi yang akan dipasang
dan cara daemon diminta berhenti tanpa sinyal.
"""

import os
import plistlib
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cc_daemon
import cc_layanan as cl


class UjiIsiPasangan(unittest.TestCase):
    def test_plist_menjalankan_daemon_dan_restart_hanya_saat_jatuh(self):
        daemon = Path("/r/cc_daemon.py")
        isi = cl.isi_plist("/opt/homebrew/bin/python3", daemon)
        self.assertEqual(isi["Label"], cl.LABEL)
        self.assertEqual(isi["ProgramArguments"], ["/opt/homebrew/bin/python3", str(daemon)])
        self.assertTrue(isi["RunAtLoad"])
        # client_id ditolak keluar dengan kode 0 -- tidak boleh diputar ulang.
        self.assertEqual(isi["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(isi["StandardOutPath"], isi["StandardErrorPath"])
        plistlib.dumps(isi)  # harus bisa ditulis apa adanya

    def test_nilai_run_mengutip_jalur_berspasi(self):
        with mock.patch.object(cl, "pythonw", return_value=r"C:\Program Files\Python\pythonw.exe"):
            nilai = cl.perintah_run(Path(r"C:\Users\Lam Ram\vibe\cc_daemon.py"))
        self.assertEqual(nilai, '"C:\\Program Files\\Python\\pythonw.exe" '
                                '"' + str(Path(r"C:\Users\Lam Ram\vibe\cc_daemon.py")) + '"')

    def test_python_mac_memakai_jalur_tak_berversi(self):
        # Jalur Cellar Homebrew berversi putus saat brew naik versi mayor.
        with mock.patch.object(cl.shutil, "which", return_value="/opt/homebrew/bin/python3"):
            self.assertEqual(cl.python_mac(), "/opt/homebrew/bin/python3")


class UjiHentikan(unittest.TestCase):
    """Windows: daemon diminta berhenti lewat berkas tanda, bukan os.kill."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        patch = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": d.name})
        patch.start()
        self.addCleanup(patch.stop)
        self.spool = cc_daemon.dir_spool()
        self.tanda = self.spool.parent / cc_daemon.BERHENTI

    def test_tanpa_daemon_langsung_selesai(self):
        mulai = time.monotonic()
        self.assertTrue(cl.hentikan(tenggat=5))
        self.assertLess(time.monotonic() - mulai, 1)
        self.assertFalse(self.tanda.exists())

    def test_spool_yatim_dibereskan(self):
        # Daemon sudah mati tanpa membereskan spool (dibunuh paksa).
        self.spool.mkdir(parents=True)
        (self.spool / "1.json").write_text("{}")
        self.assertFalse(cl.hentikan(tenggat=0.3))
        self.assertFalse(self.spool.exists())
        self.assertFalse(self.tanda.exists(), "tanda basi tidak boleh tertinggal")

    def test_daemon_hidup_menjawab_tanda(self):
        self.spool.mkdir(parents=True)

        def daemon_palsu():
            while not self.tanda.exists():
                time.sleep(0.05)
            self.tanda.unlink()
            self.spool.rmdir()

        t = threading.Thread(target=daemon_palsu, daemon=True)
        t.start()
        self.assertTrue(cl.hentikan(tenggat=5))
        t.join(1)


class UjiPerintahPendek(unittest.TestCase):
    """`presence` di terminal: symlink di ~/.local/bin, .cmd di WindowsApps."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.jalur = Path(d.name) / ("presence.cmd" if sys.platform == "win32" else "presence")
        t = mock.patch.object(cl, "jalur_perintah", return_value=self.jalur)
        t.start()
        self.addCleanup(t.stop)

    def test_dibuat_menunjuk_ke_atur(self):
        cl.pasang_perintah()
        if sys.platform == "win32":
            self.assertIn(str(cl.ATUR), self.jalur.read_text(encoding="oem"))
        else:
            self.assertEqual(self.jalur.resolve(), cl.ATUR)

    def test_pasang_ulang_aman(self):
        cl.pasang_perintah()
        cl.pasang_perintah()
        self.assertTrue(cl._milik_kita(self.jalur))

    def test_nama_yang_dipakai_program_lain_tidak_ditimpa(self):
        self.jalur.write_text("program orang lain")
        pesan = cl.pasang_perintah()
        self.assertIn("dipakai", pesan)
        self.assertEqual(self.jalur.read_text(), "program orang lain")

    def test_copot_hanya_mencabut_milik_kita(self):
        cl.pasang_perintah()
        cl.copot_perintah()
        self.assertFalse(self.jalur.exists() or self.jalur.is_symlink())
        self.jalur.write_text("program orang lain")
        cl.copot_perintah()
        self.assertTrue(self.jalur.exists())

    @unittest.skipIf(sys.platform == "win32", "symlink")
    def test_symlink_ke_program_lain_tidak_ditimpa(self):
        lain = self.jalur.with_name("program-lain")
        lain.write_text("x")
        self.jalur.symlink_to(lain)
        cl.pasang_perintah()
        self.assertEqual(self.jalur.resolve(), lain.resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
