"""Uji untuk cc_daemon -- jalankan: python3 uji/uji_cc_daemon.py

Yang diuji bagian yang tidak kelihatan saat dipakai: penyerapan spool,
rem laju penerbitan, berkas yang tertangkap separuh tertulis, dan terbit
ulang setelah koneksi pulih.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cc_daemon
import cc_konfig
import cc_state
from cc_ipc import DiscordTidakAda


class KlienPalsu:
    """Pengganti KlienDiscord yang mencatat apa saja yang diterbitkan."""

    def __init__(self, *a, **kw):
        self.tersambung = False
        self.terbit = []
        self.gagal_kirim = False
        self.gagal_sambung = False

    def sambung(self):
        if self.gagal_sambung:
            raise DiscordTidakAda("Discord belum jalan")
        self.tersambung = True

    def set_activity(self, activity):
        if self.gagal_kirim:
            self.tersambung = False
            raise DiscordTidakAda("koneksi ditutup Discord")
        self.terbit.append(activity)
        return {}

    def tutup(self):
        self.tersambung = False


def ev(sid, peristiwa, cwd="/home/ram/workspace/projects/aio-lcd", **tambahan):
    d = {"session_id": sid, "hook_event_name": peristiwa, "cwd": cwd}
    d.update(tambahan)
    return d


class DasarDaemon(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.lama = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.dir.name
        cfg = dict(cc_konfig.BAWAAN)
        cfg["client_id"] = "123456"
        self.d = cc_daemon.Daemon(cfg)
        self.d.klien = KlienPalsu()
        self.d.siapkan_spool()

    def tearDown(self):
        if self.lama is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = self.lama
        self.dir.cleanup()

    def taruh(self, nama, muatan):
        f = self.d.spool / nama
        f.write_text(muatan if isinstance(muatan, str) else json.dumps(muatan), encoding="utf-8")
        return f


class UjiSpool(DasarDaemon):
    def test_peristiwa_terserap_dan_berkasnya_dihapus(self):
        self.taruh("1.json", ev("a", "PreToolUse", tool_name="Bash"))
        self.assertTrue(self.d.serap_peristiwa(100.0))
        self.assertIn("a", self.d.registry.sesi)
        self.assertEqual(list(self.d.spool.iterdir()), [], "spool harus dikosongkan")

    def test_urutan_nama_berkas_menentukan_urutan_peristiwa(self):
        # Nama berkas diawali EPOCHREALTIME, jadi urut leksikal = urut waktu.
        self.taruh("1789206000.100000-1.json", ev("a", "PreToolUse", tool_name="Bash"))
        self.taruh("1789206000.200000-2.json", ev("a", "Stop"))
        self.d.serap_peristiwa(100.0)
        self.assertEqual(self.d.registry.sesi["a"].keadaan, "idle")

    def test_berkas_separuh_tertulis_ditahan_bukan_dibuang(self):
        # Hook mungkin masih menulis saat daemon menyapu.
        f = self.taruh("1.json", '{"session_id": "a", "hook_ev')
        self.d.serap_peristiwa(100.0)
        self.assertTrue(f.exists(), "harus diberi kesempatan dibaca lagi")

    def test_berkas_rusak_akhirnya_dibuang(self):
        f = self.taruh("1.json", "{bukan json")
        os.utime(f, (0, 0))  # bikin tua supaya lewat tenggang
        self.d.serap_peristiwa(cc_daemon.TENGGANG_RUSAK + 100.0)
        self.assertFalse(f.exists(), "berkas rusak tidak boleh menyumbat spool")

    def test_json_sah_tapi_bukan_objek_diabaikan(self):
        self.taruh("1.json", [1, 2, 3])
        self.d.serap_peristiwa(100.0)
        self.assertEqual(self.d.registry.sesi, {})

    def test_spool_dibereskan_supaya_hook_jadi_nooop(self):
        self.taruh("1.json", ev("a", "Stop"))
        self.d.bereskan_spool()
        self.assertFalse(self.d.spool.exists())

    def test_siapkan_spool_membuang_sisa_jalan_sebelumnya(self):
        self.taruh("basi.json", ev("hantu", "PreToolUse"))
        self.d.siapkan_spool()
        self.assertEqual(list(self.d.spool.iterdir()), [])


class UjiTandaHidup(DasarDaemon):
    """Detak dan tanda berhenti: pengganti systemd di OS yang tidak punya."""

    def test_siapkan_spool_menyalakan_detak(self):
        self.assertTrue(self.d.berkas_detak.exists())

    def test_tanda_berhenti_sisa_tidak_mematikan_daemon_baru(self):
        self.d.tanda_berhenti.touch()
        self.d.siapkan_spool()
        self.assertFalse(self.d.tanda_berhenti.exists())

    def test_bereskan_spool_ikut_mematikan_detak(self):
        self.d.bereskan_spool()
        self.assertFalse(self.d.berkas_detak.exists())

    def test_tanda_berhenti_menghentikan_daemon_dengan_rapi(self):
        self.d.musik = self.d.sampul = None
        # Tanda ditaruh selagi daemon tidur di denyut pertama -- persis yang
        # dilakukan pemasang di Windows.
        with mock.patch.object(cc_daemon.time, "sleep",
                               lambda _: self.d.tanda_berhenti.touch()), \
                mock.patch.object(cc_daemon.signal, "signal"):
            self.assertEqual(self.d.jalankan(), 0)
        self.assertFalse(self.d.spool.exists(), "spool harus dibereskan")
        self.assertFalse(self.d.tanda_berhenti.exists(), "tanda harus dibuang")
        self.assertFalse(self.d.berkas_detak.exists(), "hook harus kembali diam")
        self.assertIsNone(self.d.klien.terbit[-1], "presence harus dikosongkan")


class UjiRemLaju(DasarDaemon):
    def test_terbitan_pertama_langsung_jalan(self):
        self.d.terbitkan({"details": "x"}, 100.0)
        self.assertEqual(len(self.d.klien.terbit), 1)

    def test_muatan_sama_tidak_diterbitkan_ulang(self):
        self.d.terbitkan({"details": "x"}, 100.0)
        self.d.terbitkan({"details": "x"}, 500.0)
        self.assertEqual(len(self.d.klien.terbit), 1)

    def test_perubahan_dalam_jeda_ditahan(self):
        # Discord membatasi SET_ACTIVITY; tanpa rem ini batasnya jebol saat
        # tool call beruntun.
        self.d.terbitkan({"details": "x"}, 100.0)
        self.d.terbitkan({"details": "y"}, 100.0 + cc_konfig.BAWAAN["jeda_publish"] - 1)
        self.assertEqual(len(self.d.klien.terbit), 1)

    def test_perubahan_setelah_jeda_diterbitkan(self):
        self.d.terbitkan({"details": "x"}, 100.0)
        self.d.terbitkan({"details": "y"}, 100.0 + cc_konfig.BAWAAN["jeda_publish"] + 1)
        self.assertEqual(len(self.d.klien.terbit), 2)

    def test_mengosongkan_presence_terhitung_perubahan(self):
        self.d.terbitkan({"details": "x"}, 100.0)
        self.d.terbitkan(None, 200.0)
        self.assertEqual(self.d.klien.terbit[-1], None)

    def test_registry_kosong_di_awal_tetap_mengosongkan_sekali(self):
        # None tidak boleh disamakan dengan "belum pernah terbit".
        self.d.terbitkan(None, 100.0)
        self.assertEqual(self.d.klien.terbit, [None])

    def test_keadaan_yang_tertahan_rem_terbit_saat_jendelanya_buka(self):
        # Giliran pendek (prompt -> tool -> stop) terjadi dalam beberapa detik,
        # jadi penerbitan pertama menang dan sisanya ketahan. Yang penting:
        # keadaan terakhir tidak ditelan selamanya -- denyut berikutnya
        # merakit ulang dari registry, jadi begitu jendelanya buka yang
        # terbit adalah keadaan SEKARANG, bukan yang basi.
        jeda = self.d.cfg["jeda_publish"]
        self.d.terbitkan({"details": "x", "state": "Berpikir"}, 100.0)
        for detik in range(1, jeda):  # ketahan seluruh jendela
            self.d.terbitkan({"details": "x", "state": "Menunggu perintah"}, 100.0 + detik)
        self.assertEqual(len(self.d.klien.terbit), 1)
        self.d.terbitkan({"details": "x", "state": "Menunggu perintah"}, 100.0 + jeda)
        self.assertEqual(self.d.klien.terbit[-1]["state"], "Menunggu perintah")

    def test_kirim_gagal_menjadwalkan_sambung_ulang(self):
        self.d.klien.gagal_kirim = True
        self.d.terbitkan({"details": "x"}, 100.0)
        self.assertGreater(self.d.coba_sambung_lagi, 100.0)
        self.assertIsNot(self.d.terakhir_muatan, {"details": "x"})


class UjiKoneksi(DasarDaemon):
    def test_discord_mati_dijadwalkan_ulang_bukan_berhenti(self):
        self.d.klien.gagal_sambung = True
        self.assertFalse(self.d.pastikan_tersambung(100.0))
        self.assertTrue(self.d.jalan, "daemon harus tetap hidup menunggu Discord")
        self.assertEqual(self.d.coba_sambung_lagi, 100.0 + cc_daemon.JEDA_SAMBUNG)

    def test_tidak_mencoba_sambung_sebelum_jedanya_lewat(self):
        self.d.klien.gagal_sambung = True
        self.d.pastikan_tersambung(100.0)
        self.d.klien.gagal_sambung = False
        self.assertFalse(self.d.pastikan_tersambung(101.0))
        self.assertTrue(self.d.pastikan_tersambung(100.0 + cc_daemon.JEDA_SAMBUNG + 1))

    def test_client_id_ditolak_menghentikan_daemon(self):
        def tolak():
            raise ValueError("Discord menolak: Invalid Client ID")
        self.d.klien.sambung = tolak
        self.assertFalse(self.d.pastikan_tersambung(100.0))
        self.assertFalse(self.d.jalan, "mengulang tidak akan menolong")

    def test_sambung_ulang_memaksa_terbit_lagi(self):
        # Presence hilang saat koneksi putus, jadi muatan yang sama harus
        # dikirim ulang -- kalau tidak, Discord tetap kosong.
        self.d.pastikan_tersambung(100.0)
        self.d.terbitkan({"details": "x"}, 100.0)
        self.d.klien.tutup()
        self.d.pastikan_tersambung(200.0)
        self.d.terbitkan({"details": "x"}, 200.0)
        self.assertEqual(len(self.d.klien.terbit), 2)


class UjiDaurPenuh(DasarDaemon):
    def test_dari_hook_sampai_presence(self):
        self.taruh("1.json", ev("a", "PreToolUse", tool_name="Edit",
                                tool_input={"file_path": "/home/ram/workspace/projects/aio-lcd/x.py"}))
        sekarang = 100.0
        self.d.serap_peristiwa(sekarang)
        self.d.registry.bersihkan(sekarang)
        self.d.pastikan_tersambung(sekarang)
        self.d.terbitkan(self.d.registry.rakit(sekarang), sekarang)
        hasil = self.d.klien.terbit[-1]
        self.assertEqual(hasil["details"], "\U0001f4c1 aio-lcd")
        self.assertEqual(hasil["state"], cc_state.LABEL_BAWAAN["Edit"])
        self.assertNotIn("x.py", hasil["state"], "mode normal tidak boleh bocor nama berkas")

    def test_sesi_basi_mengosongkan_presence(self):
        self.taruh("1.json", ev("a", "UserPromptSubmit"))
        self.d.serap_peristiwa(100.0)
        self.d.pastikan_tersambung(100.0)
        self.d.terbitkan(self.d.registry.rakit(100.0), 100.0)
        jauh = 100.0 + cc_konfig.BAWAAN["ttl_sesi"] + 10
        self.d.registry.bersihkan(jauh)
        self.d.terbitkan(self.d.registry.rakit(jauh), jauh)
        self.assertNotIn("state", self.d.klien.terbit[-1],
                         "harusnya jatuh ke kartu kosong, bukan kartu sesi")


class PencariPalsu:
    def __init__(self, hasil="https://cover/x.jpg"):
        self.hasil = hasil
        self.diminta = []

    def untuk(self, lagu):
        self.diminta.append(lagu.get("judul"))
        return self.hasil


class UjiSampul(unittest.TestCase):
    """Sampul dicari di daemon, bukan di Registry -- Registry tetap tanpa jaringan."""

    LAGU = {"judul": "august", "artis": "Taylor Swift", "album": "folklore",
            "pemutar": "brave", "sampul_mentah": "file:///tmp/x.png"}

    def _daemon(self, **timpa):
        cfg = dict(cc_konfig.BAWAAN, client_id="123456")
        cfg.update(timpa)
        return cc_daemon.Daemon(cfg)

    def test_sampul_dilekatkan_ke_lagu(self):
        d = self._daemon()
        d.musik = type("M", (), {"sekarang": lambda _s, _w: dict(UjiSampul.LAGU)})()
        d.sampul = PencariPalsu()
        self.assertEqual(d.lagu_kini(10.0)["sampul"], "https://cover/x.jpg")

    def test_sampul_dimatikan_tidak_menyentuh_pencari(self):
        d = self._daemon(sampul=False)
        self.assertIsNone(d.sampul)

    def test_mode_minimal_tidak_pernah_mencari_sampul(self):
        # Mode minimal menjanjikan judul lagu tidak ke mana-mana -- termasuk
        # tidak ke API pencarian sampul.
        self.assertIsNone(self._daemon(mode="minimal").sampul)

    def test_musik_dimatikan_tidak_perlu_pencari(self):
        self.assertIsNone(self._daemon(musik=False).sampul)

    def test_saklar_sampul_saat_kerja_diteruskan_ke_registry(self):
        # Gampang lupa: menambah kunci konfig tanpa menyambungkannya bikin
        # saklarnya diam saja tanpa galat apa pun.
        self.assertIs(self._daemon(sampul_saat_kerja=False).registry.sampul_saat_kerja, False)

    def test_tanpa_lagu_pencari_tidak_dipanggil(self):
        d = self._daemon()
        d.musik = type("M", (), {"sekarang": lambda _s, _w: None})()
        d.sampul = PencariPalsu()
        self.assertIsNone(d.lagu_kini(10.0))
        self.assertEqual(d.sampul.diminta, [])


class UjiWaktuNyalaPc(unittest.TestCase):
    """Jam timer dibaca daemon sekali saat start; Registry cuma menerima angkanya."""

    def test_dibaca_dari_btime(self):
        with tempfile.TemporaryDirectory() as d:
            stat = Path(d) / "stat"
            stat.write_text("cpu  1 2 3 4\nintr 5\nbtime 1789478631\nprocesses 99\n", encoding="utf-8")
            self.assertEqual(cc_daemon.waktu_nyala_pc(stat), 1789478631.0)

    @unittest.skipUnless(sys.platform.startswith("linux"), "CLOCK_BOOTTIME cuma ada di Linux")
    def test_tanpa_btime_jatuh_ke_jam_boottime(self):
        # /proc/stat bisa disembunyikan sandbox systemd (ProcSubset=pid).
        perkiraan = time.time() - time.clock_gettime(time.CLOCK_BOOTTIME)
        self.assertAlmostEqual(cc_daemon.waktu_nyala_pc(Path("/tidak/ada/stat")), perkiraan, delta=2)

    def test_tanpa_proc_stat_tetap_masuk_akal_di_semua_os(self):
        # macOS dan Windows tidak punya /proc sama sekali.
        nyala = cc_daemon.waktu_nyala_pc(Path("/tidak/ada/stat"))
        self.assertLess(nyala, time.time())
        self.assertGreater(nyala, time.time() - 365 * 86400)

    def test_keluaran_sysctl_macos_terurai(self):
        teks = "{ sec = 1790039066, usec = 280999 } Tue Sep 22 09:04:26 2026\n"
        self.assertEqual(cc_daemon._urai_boottime(teks), 1790039066.0)

    def _daemon(self, **timpa):
        return cc_daemon.Daemon(dict(cc_konfig.BAWAAN, client_id="123456", **timpa))

    def test_waktu_nyala_diteruskan_ke_registry(self):
        # Gampang lupa: kunci konfig yang tidak disambungkan diam saja tanpa galat.
        mulai = self._daemon(sumber_timer="nyala_pc").registry.mulai_tetap
        self.assertAlmostEqual(mulai, cc_daemon.waktu_nyala_pc(), delta=2)

    def test_sumber_sesi_tidak_mematok_timer(self):
        self.assertEqual(self._daemon(sumber_timer="sesi").registry.mulai_tetap, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
