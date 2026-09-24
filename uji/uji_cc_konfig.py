"""Uji untuk cc_konfig -- jalankan: python3 uji/uji_cc_konfig.py"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cc_konfig as ck


class UjiKonfig(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.jalur = Path(self.dir.name) / "konfig.json"

    def tearDown(self):
        self.dir.cleanup()

    def tulis(self, isi):
        self.jalur.write_text(json.dumps(isi), encoding="utf-8")

    def test_berkas_tidak_ada_pakai_bawaan(self):
        cfg = ck.muat(self.jalur)
        self.assertEqual(cfg["mode"], "normal")
        self.assertEqual(cfg["client_id"], "")

    def test_berkas_rusak_tidak_melempar(self):
        self.jalur.write_text("{bukan json", encoding="utf-8")
        self.assertEqual(ck.muat(self.jalur)["mode"], "normal")

    def test_kunci_hilang_dilengkapi(self):
        self.tulis({"client_id": "123"})
        cfg = ck.muat(self.jalur)
        self.assertEqual(cfg["client_id"], "123")
        self.assertEqual(cfg["ttl_sesi"], ck.BAWAAN["ttl_sesi"])

    def test_kunci_asing_diabaikan(self):
        self.tulis({"client_id": "123", "rahasia": "jangan-kepakai"})
        self.assertNotIn("rahasia", ck.muat(self.jalur))

    def test_mode_ngawur_jatuh_ke_bawaan(self):
        self.tulis({"mode": "bocorin-semua"})
        self.assertEqual(ck.muat(self.jalur)["mode"], "normal")

    def test_jeda_publish_tidak_boleh_di_bawah_batas_laju(self):
        # Discord membatasi SET_ACTIVITY; nilai kecil harus dinaikkan paksa.
        self.tulis({"jeda_publish": 1})
        self.assertEqual(ck.muat(self.jalur)["jeda_publish"], 15)

    def test_ttl_terlalu_kecil_dinaikkan(self):
        self.tulis({"ttl_sesi": 5})
        self.assertEqual(ck.muat(self.jalur)["ttl_sesi"], 60)

    def test_client_id_dirapikan(self):
        self.tulis({"client_id": "  123456  "})
        self.assertEqual(ck.muat(self.jalur)["client_id"], "123456")

    def test_proyek_privat_bukan_larik_diabaikan(self):
        self.tulis({"proyek_privat": "skripsi"})
        self.assertEqual(ck.muat(self.jalur)["proyek_privat"], [])

    def test_label_bukan_objek_diabaikan(self):
        self.tulis({"label": ["bukan", "objek"]})
        self.assertEqual(ck.muat(self.jalur)["label"], {})

    def test_label_bernilai_bukan_teks_dibuang(self):
        # Nilai non-teks baru meledak jauh di belakang, saat presence dirakit.
        self.tulis({"label": {"Bash": "oke", "Read": 123, "Edit": None}})
        self.assertEqual(ck.muat(self.jalur)["label"], {"Bash": "oke"})

    def test_tipe_ngawur_jatuh_ke_bawaan(self):
        self.tulis({"tipe_kerja": 99, "tipe_musik": 1})
        cfg = ck.muat(self.jalur)
        self.assertEqual(cfg["tipe_kerja"], 0)
        self.assertEqual(cfg["tipe_musik"], 2)

    def test_tipe_berupa_teks_angka_tetap_diterima(self):
        self.tulis({"tipe_kerja": "3"})
        self.assertEqual(ck.muat(self.jalur)["tipe_kerja"], 3)

    def test_tipe_bukan_angka_jatuh_ke_bawaan(self):
        self.tulis({"tipe_kerja": "playing"})
        self.assertEqual(ck.muat(self.jalur)["tipe_kerja"], 0)

    def test_simpan_lalu_muat_pulang_pergi(self):
        cfg = ck.muat(self.jalur)
        cfg["client_id"] = "987"
        cfg["proyek_privat"] = ["Skripsi"]
        ck.simpan(cfg, self.jalur)
        lagi = ck.muat(self.jalur)
        self.assertEqual(lagi["client_id"], "987")
        self.assertEqual(lagi["proyek_privat"], ["Skripsi"])


class UjiKunciSampul(unittest.TestCase):
    def test_sampul_bawaannya_nyala(self):
        self.assertIs(ck.BAWAAN["sampul"], True)

    def test_sampul_saat_kerja_bawaannya_nyala(self):
        self.assertIs(ck.BAWAAN["sampul_saat_kerja"], True)

    def test_sampul_saat_kerja_terbaca_dari_berkas(self):
        with tempfile.TemporaryDirectory() as d:
            jalur = Path(d) / "konfig.json"
            jalur.write_text(json.dumps({"sampul_saat_kerja": False}), encoding="utf-8")
            self.assertIs(ck.muat(jalur)["sampul_saat_kerja"], False)


class UjiSumberTimer(unittest.TestCase):
    def muat_dengan(self, isi):
        with tempfile.TemporaryDirectory() as d:
            jalur = Path(d) / "konfig.json"
            jalur.write_text(json.dumps(isi), encoding="utf-8")
            return ck.muat(jalur)

    def test_bawaannya_waktu_nyala_pc(self):
        self.assertEqual(ck.BAWAAN["sumber_timer"], "nyala_pc")

    def test_sesi_terbaca_dari_berkas(self):
        self.assertEqual(self.muat_dengan({"sumber_timer": "sesi"})["sumber_timer"], "sesi")

    def test_nilai_ngawur_jatuh_ke_bawaan(self):
        self.assertEqual(self.muat_dengan({"sumber_timer": "kapan-kapan"})["sumber_timer"], "nyala_pc")


class UjiDirRuntime(unittest.TestCase):
    """Soket Discord dan spool harus dicari di folder yang sama dengan Discord."""

    def _dengan(self, platform, **env):
        bersih = {k: v for k, v in os.environ.items()
                  if k not in ("XDG_RUNTIME_DIR", "TMPDIR", "LOCALAPPDATA")}
        bersih.update(env)
        with mock.patch.dict(os.environ, bersih, clear=True), \
                mock.patch.object(ck.sys, "platform", platform):
            return ck.dir_runtime()

    def test_xdg_didahulukan_di_semua_os(self):
        for platform in ("linux", "darwin", "win32"):
            with self.subTest(platform=platform):
                self.assertEqual(self._dengan(platform, XDG_RUNTIME_DIR="/x/run"), Path("/x/run"))

    def test_macos_memakai_tmpdir(self):
        self.assertEqual(self._dengan("darwin", TMPDIR="/var/folders/ab/T/"), Path("/var/folders/ab/T"))

    def test_macos_tanpa_tmpdir_bertanya_ke_getconf(self):
        with mock.patch.object(ck, "_getconf", return_value="/var/folders/cd/T/"):
            self.assertEqual(self._dengan("darwin"), Path("/var/folders/cd/T"))

    def test_windows_memakai_localappdata(self):
        self.assertEqual(self._dengan("win32", LOCALAPPDATA=r"C:\Users\x\AppData\Local"),
                         Path(r"C:\Users\x\AppData\Local"))


class UjiAktif(unittest.TestCase):
    """Saklar presence dari menu atur.py; harus bertahan lewat restart."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.jalur = Path(self.dir.name) / "konfig.json"

    def test_bawaannya_nyala(self):
        self.assertIs(ck.muat(self.jalur)["aktif"], True)

    def test_mati_terbaca_dari_berkas(self):
        self.jalur.write_text(json.dumps({"aktif": False}), encoding="utf-8")
        self.assertIs(ck.muat(self.jalur)["aktif"], False)

    def test_nilai_ngawur_dianggap_nyala(self):
        # Cuma false yang eksplisit yang boleh mematikan presence diam-diam.
        for nilai in ("false", 0, None, "mati"):
            with self.subTest(nilai=nilai):
                self.jalur.write_text(json.dumps({"aktif": nilai}), encoding="utf-8")
                self.assertIs(ck.muat(self.jalur)["aktif"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
