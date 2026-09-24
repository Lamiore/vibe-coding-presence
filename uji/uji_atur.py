"""Uji untuk atur.py -- jalankan: python3 uji/uji_atur.py

Yang diuji aksi di balik tiap pilihan menu, bukan loop input()-nya:
autostart dan pemasang diganti tiruan, konfig dan spool diarahkan ke
folder sementara.
"""

import contextlib
import io
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import atur
import cc_daemon
import cc_konfig

ID = "1402837465912837465"


class Dasar(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d.name, "XDG_RUNTIME_DIR": d.name})
        env.start()
        self.addCleanup(env.stop)
        self.muat_ulang = self._tiru("cc_layanan.muat_ulang", return_value=True)
        self.pasang = self._tiru("_pasang", return_value=True)
        self.set_terpasang(True)

    def _tiru(self, sasaran, **kw):
        modul, _, nama = sasaran.rpartition(".")
        pemilik = getattr(atur, modul) if modul else atur
        t = mock.patch.object(pemilik, nama, **kw)
        self.addCleanup(t.stop)
        return t.start()

    def set_terpasang(self, nilai):
        self._tiru("terpasang", return_value=nilai)

    def cfg(self):
        return cc_konfig.muat()


class UjiApplicationId(Dasar):
    def test_id_sah(self):
        self.assertTrue(atur.id_sah(ID))
        for salah in ("", "abc", "12345", "1402837465912837465x", "1" * 25):
            with self.subTest(salah=salah):
                self.assertFalse(atur.id_sah(salah))

    def test_id_sah_disimpan(self):
        ok, _ = atur.simpan_id(f"  {ID}  ")
        self.assertTrue(ok)
        self.assertEqual(self.cfg()["client_id"], ID)

    def test_id_salah_tidak_disimpan(self):
        ok, pesan = atur.simpan_id("bukan-angka")
        self.assertFalse(ok)
        self.assertIn("angka", pesan)
        self.assertEqual(self.cfg()["client_id"], "")

    def test_ganti_id_memuat_ulang_daemon_yang_terpasang(self):
        atur.simpan_id(ID)
        self.muat_ulang.assert_called_once()

    def test_ganti_id_saat_presence_mati_tidak_menyalakannya(self):
        atur.matikan()
        self.muat_ulang.reset_mock()
        atur.simpan_id(ID)
        self.muat_ulang.assert_not_called()


class UjiSaklar(Dasar):
    def test_nyalakan_tanpa_id_ditolak(self):
        ok, pesan = atur.nyalakan()
        self.assertFalse(ok)
        self.assertIn("Application ID", pesan)
        self.pasang.assert_not_called()

    def test_nyalakan_pertama_kali_memasang(self):
        self.set_terpasang(False)
        atur.simpan_id(ID)
        ok, _ = atur.nyalakan()
        self.assertTrue(ok)
        self.pasang.assert_called_once_with(ID)
        self.assertTrue(self.cfg()["aktif"])

    def test_nyalakan_yang_sudah_terpasang_cuma_memuat_ulang(self):
        atur.simpan_id(ID)
        atur.matikan()
        self.muat_ulang.reset_mock()
        ok, _ = atur.nyalakan()
        self.assertTrue(ok)
        self.assertTrue(self.cfg()["aktif"])
        self.muat_ulang.assert_called_once()
        self.pasang.assert_not_called()

    def test_matikan_bertahan_di_konfig(self):
        atur.simpan_id(ID)
        ok, pesan = atur.matikan()
        self.assertTrue(ok)
        self.assertFalse(self.cfg()["aktif"])
        self.assertIn("restart", pesan)

    def test_matikan_membangunkan_daemon_supaya_keluar(self):
        atur.matikan()
        self.muat_ulang.assert_called_once()

    def test_matikan_yang_belum_terpasang_tidak_memanggil_autostart(self):
        self.set_terpasang(False)
        atur.matikan()
        self.muat_ulang.assert_not_called()


class UjiKeadaan(Dasar):
    def detak(self):
        return cc_daemon.dir_spool().parent / cc_daemon.DETAK

    def test_daemon_jalan_dari_detak_segar(self):
        self.assertFalse(atur.daemon_jalan())
        self.detak().parent.mkdir(parents=True, exist_ok=True)
        self.detak().touch()
        self.assertTrue(atur.daemon_jalan())
        os.utime(self.detak(), (0, 0))
        self.assertFalse(atur.daemon_jalan(), "detak basi = daemon sudah mati")

    @unittest.skipUnless(hasattr(socket, "AF_UNIX"), "soket Unix tidak ada di Windows")
    def test_soket_basi_bukan_berarti_discord_kebuka(self):
        # Kejadian nyata di Mac: discord-ipc-0 tertinggal sesudah Discord ditutup.
        jalur = str(Path(os.environ["XDG_RUNTIME_DIR"]) / "discord-ipc-0")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(jalur)
        s.listen(1)
        self.assertTrue(atur.discord_kebuka())
        s.close()  # berkasnya tetap ada, tapi tidak ada yang mendengarkan
        self.assertTrue(Path(jalur).exists())
        self.assertFalse(atur.discord_kebuka())

    def tampil(self, **k):
        keadaan = {"aktif": True, "client_id": "", "terpasang": True, "daemon": False, "discord": False}
        keadaan.update(k)
        keluaran = io.StringIO()
        with contextlib.redirect_stdout(keluaran), mock.patch.object(atur, "WARNA", False):
            atur.tampilkan(keadaan)
        return keluaran.getvalue()

    def test_tampilan_tanpa_warna_memuat_keadaan(self):
        teks = self.tampil(aktif=False)
        self.assertIn("○ mati", teks)
        self.assertIn("belum diisi", teks)
        self.assertNotIn("\033[", teks, "tanpa warna berarti tanpa kode ANSI")

    def test_belum_terpasang_tidak_mengaku_nyala(self):
        teks = self.tampil(terpasang=False)
        self.assertIn("belum dipasang", teks)
        self.assertNotIn("● nyala", teks)
        self.assertIn("sekalian pasang", teks)


if __name__ == "__main__":
    unittest.main(verbosity=2)
