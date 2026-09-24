"""Uji untuk cc_pasang -- jalankan: python3 uji/uji_cc_pasang.py

settings.json milik pengguna biasanya sudah penuh hook alat lain. Uji ini
memakai cuplikan bentuk nyata dari mesin ini supaya pemasangan terbukti
tidak menabrak apa pun.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cc_pasang as cp
from cc_state import PERISTIWA

PERINTAH = "/home/ram/.claude/hooks/lagi-ngapain-hook.sh"

# Bentuk nyata: rtk memakai matcher Bash, context-mode memakai entri tanpa
# matcher, dan ada entri kosong bawaan yang tidak boleh ikut terhapus.
NYATA = {
    "permissions": {"defaultMode": "auto"},
    "hooks": {
        "SessionStart": [
            {"hooks": [{"type": "command", "command": "/home/ram/.claude/hooks/context-mode-cache-heal.mjs"}]},
            {"matcher": "", "hooks": []},
        ],
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]},
            {"matcher": "", "hooks": []},
        ],
        "Stop": [{"matcher": "", "hooks": []}],
    },
}


class Dasar(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.jalur = Path(self.dir.name) / "settings.json"

    def tearDown(self):
        self.dir.cleanup()

    def tulis(self, data):
        self.jalur.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def baca(self):
        return json.loads(self.jalur.read_text(encoding="utf-8"))


class UjiPasang(Dasar):
    def test_terpasang_di_semua_peristiwa(self):
        self.tulis(NYATA)
        ok, _ = cp.pasang(PERINTAH, self.jalur)
        self.assertTrue(ok)
        self.assertEqual(sorted(cp.terpasang(self.jalur)), sorted(PERISTIWA))

    def test_hook_alat_lain_tidak_tersentuh(self):
        self.tulis(NYATA)
        cp.pasang(PERINTAH, self.jalur)
        perintah = [
            h["command"]
            for daftar in self.baca()["hooks"].values()
            for e in daftar for h in e.get("hooks", [])
        ]
        self.assertIn("rtk hook claude", perintah)
        self.assertIn("/home/ram/.claude/hooks/context-mode-cache-heal.mjs", perintah)

    def test_matcher_bash_milik_rtk_tetap_utuh(self):
        self.tulis(NYATA)
        cp.pasang(PERINTAH, self.jalur)
        rtk = [e for e in self.baca()["hooks"]["PreToolUse"] if e.get("matcher") == "Bash"]
        self.assertEqual(len(rtk), 1)
        self.assertEqual(rtk[0]["hooks"][0]["command"], "rtk hook claude")

    def test_setelan_di_luar_hooks_tetap_utuh(self):
        self.tulis(NYATA)
        cp.pasang(PERINTAH, self.jalur)
        self.assertEqual(self.baca()["permissions"], {"defaultMode": "auto"})

    def test_pemasangan_ulang_tidak_menggandakan(self):
        self.tulis(NYATA)
        cp.pasang(PERINTAH, self.jalur)
        ok, pesan = cp.pasang(PERINTAH, self.jalur)
        self.assertTrue(ok)
        self.assertIn("sudah terpasang", pesan)
        milik_kita = [
            h for daftar in self.baca()["hooks"].values()
            for e in daftar for h in e.get("hooks", []) if cp.PENANDA in h["command"]
        ]
        self.assertEqual(len(milik_kita), len(PERISTIWA))

    def test_settings_belum_ada_dibuat(self):
        ok, _ = cp.pasang(PERINTAH, self.jalur)
        self.assertTrue(ok)
        self.assertEqual(sorted(cp.terpasang(self.jalur)), sorted(PERISTIWA))

    def test_settings_rusak_tidak_menghapus_apa_pun_diam_diam(self):
        self.jalur.write_text("{rusak", encoding="utf-8")
        ok, _ = cp.pasang(PERINTAH, self.jalur)
        self.assertTrue(ok)
        # Cadangannya tetap memuat berkas asli yang rusak, jadi tidak hilang.
        cadangan = self.jalur.with_suffix(".json.sebelum-lagi-ngapain")
        self.assertEqual(cadangan.read_text(encoding="utf-8"), "{rusak")

    def test_cadangan_dibuat(self):
        self.tulis(NYATA)
        cp.pasang(PERINTAH, self.jalur)
        cadangan = self.jalur.with_suffix(".json.sebelum-lagi-ngapain")
        self.assertTrue(cadangan.exists())
        self.assertEqual(json.loads(cadangan.read_text(encoding="utf-8")), NYATA)

    def test_bentuk_hooks_aneh_ditolak_bukan_ditimpa(self):
        self.tulis({"hooks": "bukan objek"})
        ok, pesan = cp.pasang(PERINTAH, self.jalur)
        self.assertFalse(ok)
        self.assertIn("bukan objek", pesan)

    def test_peristiwa_bukan_larik_ditolak(self):
        self.tulis({"hooks": {"Stop": {"salah": "bentuk"}}})
        ok, pesan = cp.pasang(PERINTAH, self.jalur)
        self.assertFalse(ok)
        self.assertIn("bukan larik", pesan)


class UjiCopot(Dasar):
    def test_hanya_milik_kita_yang_dicabut(self):
        self.tulis(NYATA)
        cp.pasang(PERINTAH, self.jalur)
        cp.copot(self.jalur)
        self.assertEqual(cp.terpasang(self.jalur), [])
        perintah = [
            h["command"]
            for daftar in self.baca()["hooks"].values()
            for e in daftar for h in e.get("hooks", [])
        ]
        self.assertIn("rtk hook claude", perintah)
        self.assertIn("/home/ram/.claude/hooks/context-mode-cache-heal.mjs", perintah)

    def test_entri_kosong_bawaan_tidak_ikut_terhapus(self):
        self.tulis(NYATA)
        cp.pasang(PERINTAH, self.jalur)
        cp.copot(self.jalur)
        self.assertIn({"matcher": "", "hooks": []}, self.baca()["hooks"]["Stop"])

    def test_copot_saat_belum_terpasang_aman(self):
        self.tulis(NYATA)
        ok, pesan = cp.copot(self.jalur)
        self.assertTrue(ok)
        self.assertIn("tidak ditemukan", pesan)

    def test_copot_tanpa_berkas_aman(self):
        ok, _ = cp.copot(self.jalur)
        self.assertTrue(ok)

    def test_pasang_copot_pulang_ke_bentuk_semula(self):
        self.tulis(NYATA)
        cp.pasang(PERINTAH, self.jalur)
        cp.copot(self.jalur)
        self.assertEqual(self.baca(), NYATA)


class UjiExecForm(Dasar):
    """macOS dan Windows memanggil hook Python tanpa shell: command + args."""

    PY = "/opt/homebrew/bin/python3"
    ARGS = ["-I", "-S", "/r/hooks/lagi-ngapain-hook.py", "/var/folders/ab/T/lagi-ngapain/ev"]

    def test_args_ikut_tertulis(self):
        self.tulis(NYATA)
        ok, _ = cp.pasang(self.PY, self.jalur, args=self.ARGS)
        self.assertTrue(ok)
        entri = self.baca()["hooks"]["PreToolUse"][-1]["hooks"][0]
        self.assertEqual(entri, {"type": "command", "command": self.PY, "args": self.ARGS})

    def test_tanpa_args_bentuk_lama_tidak_berubah(self):
        cp.pasang(PERINTAH, self.jalur)
        self.assertNotIn("args", self.baca()["hooks"]["Stop"][-1]["hooks"][0])

    def test_pasang_ulang_terkenali_lewat_args(self):
        # Penandanya ada di args, bukan di command (yang cuma jalur python).
        self.tulis(NYATA)
        cp.pasang(self.PY, self.jalur, args=self.ARGS)
        cp.pasang(self.PY, self.jalur, args=self.ARGS)
        for ev in PERISTIWA:
            milik_kita = [e for e in self.baca()["hooks"][ev] if cp._punya_kita(e)]
            self.assertEqual(len(milik_kita), 1, ev)

    def test_copot_mencabut_exec_form(self):
        self.tulis(NYATA)
        cp.pasang(self.PY, self.jalur, args=self.ARGS)
        cp.copot(self.jalur)
        self.assertEqual(cp.terpasang(self.jalur), [])
        self.assertEqual(self.baca(), NYATA)

    def test_args_bukan_larik_tidak_meledak(self):
        self.tulis({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x", "args": 5}]}]}})
        self.assertEqual(cp.terpasang(self.jalur), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
