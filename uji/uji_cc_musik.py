"""Uji untuk cc_musik -- jalankan: python3 uji/uji_cc_musik.py

D-Bus sungguhan tidak dipanggil; ``_busctl`` diganti dengan jawaban palsu
supaya bentuk balasan yang aneh (pemutar dijeda, artis berupa larik,
busctl gagal) bisa diuji tanpa memutar musik betulan.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cc_musik as cm

BRAVE = "org.mpris.MediaPlayer2.brave.instance123"
SPOTIFY = "org.mpris.MediaPlayer2.spotify"


def balasan(peta):
    """Bikin pengganti _busctl dari peta sederhana {bus: (status, metadata)}."""
    def palsu(*arg):
        if arg[0] == "call":
            return [list(peta)]
        _, bus, _, _, prop = arg
        status, meta = peta[bus]
        return status if prop == "PlaybackStatus" else meta
    return palsu


class UjiPerataanNilai(unittest.TestCase):
    def test_artis_berupa_larik_digabung(self):
        self.assertEqual(cm._teks(["A", "B"]), "A, B")

    def test_nilai_terbungkus_dict_dibuka(self):
        self.assertEqual(cm._teks({"type": "s", "data": "Halo"}), "Halo")

    def test_none_jadi_teks_kosong(self):
        self.assertEqual(cm._teks(None), "")

    def test_larik_kosong_jadi_teks_kosong(self):
        self.assertEqual(cm._teks([]), "")


class UjiPrioritas(unittest.TestCase):
    def test_pemutar_musik_menang_atas_tab_browser(self):
        # Tab browser sering ketinggalan video yang dijeda; pemutar khusus
        # musik lebih bisa dipercaya.
        urut = sorted([BRAVE, SPOTIFY], key=cm._urutan)
        self.assertEqual(urut[0], SPOTIFY)

    def test_pemutar_tak_dikenal_tetap_urut_stabil(self):
        a, b = "org.mpris.MediaPlayer2.zed", "org.mpris.MediaPlayer2.apa"
        self.assertEqual(sorted([a, b], key=cm._urutan), [b, a])


class UjiLaguSekarang(unittest.TestCase):
    def _jalankan(self, peta):
        with mock.patch.object(cm, "_busctl", balasan(peta)):
            return cm.lagu_sekarang()

    def test_mengambil_pemutar_yang_playing(self):
        lagu = self._jalankan({BRAVE: ("Playing", {
            "xesam:title": "Too Soon", "xesam:artist": ["Oliver Steele"]})})
        self.assertEqual(lagu["judul"], "Too Soon")
        self.assertEqual(lagu["artis"], "Oliver Steele")
        self.assertEqual(lagu["pemutar"], "brave")

    def test_pemutar_dijeda_dilewati(self):
        self.assertIsNone(self._jalankan({BRAVE: ("Paused", {"xesam:title": "X"})}))

    def test_yang_playing_dipilih_walau_ada_yang_dijeda(self):
        lagu = self._jalankan({
            SPOTIFY: ("Paused", {"xesam:title": "Basi"}),
            BRAVE: ("Playing", {"xesam:title": "Segar"}),
        })
        self.assertEqual(lagu["judul"], "Segar")

    def test_tanpa_judul_dilewati(self):
        # Sebagian tab browser mengumumkan diri tanpa metadata apa pun.
        self.assertIsNone(self._jalankan({BRAVE: ("Playing", {"xesam:album": "X"})}))

    def test_tanpa_artis_tetap_dipakai(self):
        lagu = self._jalankan({BRAVE: ("Playing", {"xesam:title": "Nada"})})
        self.assertEqual(lagu["artis"], "")

    def test_tidak_ada_pemutar_balikan_none(self):
        self.assertIsNone(self._jalankan({}))

    def test_busctl_gagal_tidak_melempar(self):
        # Daemon tidak boleh mati cuma karena D-Bus lagi rewel.
        with mock.patch.object(cm, "_busctl", lambda *a: None):
            self.assertIsNone(cm.lagu_sekarang())
            self.assertEqual(cm.daftar_pemutar(), [])

    def test_busctl_hilang_dari_sistem_tidak_melempar(self):
        with mock.patch.object(cm.subprocess, "run", side_effect=OSError("tidak ada")):
            self.assertIsNone(cm._busctl("call"))


class UjiSaringanPemutar(unittest.TestCase):
    """Pemutar tertentu bisa ditutup seluruhnya -- ini rem privasinya."""

    def _jalankan(self, peta, abaikan):
        with mock.patch.object(cm, "_busctl", balasan(peta)):
            return cm.lagu_sekarang(abaikan)

    def test_pemutar_yang_diabaikan_tidak_dibaca(self):
        hasil = self._jalankan({BRAVE: ("Playing", {"xesam:title": "Video Rahasia"})}, ["brave"])
        self.assertIsNone(hasil)

    def test_pemutar_lain_tetap_kebaca(self):
        hasil = self._jalankan({
            BRAVE: ("Playing", {"xesam:title": "Video Rahasia"}),
            SPOTIFY: ("Playing", {"xesam:title": "Lagu"}),
        }, ["brave"])
        self.assertEqual(hasil["judul"], "Lagu")

    def test_pencocokan_tidak_peka_huruf_besar(self):
        self.assertIsNone(self._jalankan({BRAVE: ("Playing", {"xesam:title": "X"})}, ["BRAVE"]))

    def test_daftar_kosong_tidak_menyaring_apa_pun(self):
        self.assertIsNotNone(self._jalankan({BRAVE: ("Playing", {"xesam:title": "X"})}, []))

    def test_entri_kosong_tidak_menyaring_semuanya(self):
        # "" adalah awalan dari segalanya -- kalau lolos, semua pemutar mati.
        self.assertIsNotNone(self._jalankan({BRAVE: ("Playing", {"xesam:title": "X"})}, ["", "  "]))

    def test_saringan_diteruskan_lewat_singgahan(self):
        dipanggil = []
        p = cm.PembacaMusik(sumber=lambda ab: dipanggil.append(ab), abaikan=["brave"])
        p.sekarang(0.0)
        self.assertEqual(dipanggil, [("brave",)])


class UjiSinggahan(unittest.TestCase):
    def setUp(self):
        self.panggilan = 0

    def _sumber(self, abaikan=()):
        self.panggilan += 1
        return {"judul": f"lagu-{self.panggilan}", "artis": "", "pemutar": "x"}

    def test_dibaca_sekali_dalam_satu_jendela(self):
        p = cm.PembacaMusik(jeda=5.0, sumber=self._sumber)
        p.sekarang(100.0)
        p.sekarang(102.0)
        p.sekarang(104.9)
        self.assertEqual(self.panggilan, 1)

    def test_dibaca_lagi_setelah_jendela_lewat(self):
        p = cm.PembacaMusik(jeda=5.0, sumber=self._sumber)
        self.assertEqual(p.sekarang(100.0)["judul"], "lagu-1")
        self.assertEqual(p.sekarang(105.0)["judul"], "lagu-2")

    def test_pembacaan_pertama_tidak_menunggu(self):
        p = cm.PembacaMusik(jeda=5.0, sumber=self._sumber)
        self.assertIsNotNone(p.sekarang(0.0))


class UjiMetadataSampul(unittest.TestCase):
    """Data yang dibutuhkan pencarian sampul ikut dibaca dari MPRIS."""

    def _jalankan(self, meta):
        with mock.patch.object(cm, "_busctl", balasan({BRAVE: ("Playing", meta)})):
            return cm.lagu_sekarang()

    def test_album_dan_art_url_ikut_terbaca(self):
        lagu = self._jalankan({
            "xesam:title": "august", "xesam:artist": ["Taylor Swift"],
            "xesam:album": "folklore", "mpris:artUrl": "file:///tmp/x.png"})
        self.assertEqual(lagu["album"], "folklore")
        self.assertEqual(lagu["sampul_mentah"], "file:///tmp/x.png")

    def test_metadata_tanpa_album_tetap_punya_kuncinya(self):
        # Pencari sampul membaca kunci ini langsung; kalau hilang, meledak.
        lagu = self._jalankan({"xesam:title": "Nada"})
        self.assertEqual(lagu["album"], "")
        self.assertEqual(lagu["sampul_mentah"], "")


class UjiMac(unittest.TestCase):
    """AppleScript ke Spotify dan Music; tidak ada MPRIS di macOS."""

    SPOTIFY = "Lonely Night\tCozy Apartment\tSoothing Jazz\thttps://i.scdn.co/image/ab67"

    def _baca(self, jalan, balasan, abaikan=()):
        ditanya = []

        def osascript(skrip):
            nama = "Spotify" if '"Spotify"' in skrip else "Music"
            ditanya.append(nama)
            return balasan.get(nama, "")

        with mock.patch.object(cm, "_jalan", lambda n: n in jalan), \
                mock.patch.object(cm, "_osascript", osascript):
            return cm.lagu_mac(abaikan), ditanya

    def test_ruas_tab_terurai(self):
        lagu = cm._urai_mac("Spotify", self.SPOTIFY)
        self.assertEqual(lagu, {"judul": "Lonely Night", "artis": "Cozy Apartment",
                                "album": "Soothing Jazz", "pemutar": "spotify",
                                "sampul_mentah": "https://i.scdn.co/image/ab67"})

    def test_keluaran_kosong_berarti_tidak_memutar(self):
        self.assertIsNone(cm._urai_mac("Music", ""))
        self.assertIsNone(cm._urai_mac("Music", "\t\t\t"))

    def test_pemutar_yang_mati_tidak_ditanya(self):
        # "tell application" ke aplikasi yang mati justru menyalakannya.
        lagu, ditanya = self._baca({"Music"}, {"Music": "A\tB\tC\t"})
        self.assertEqual(ditanya, ["Music"])
        self.assertEqual(lagu["pemutar"], "music")

    def test_spotify_didahulukan(self):
        lagu, _ = self._baca({"Spotify", "Music"}, {"Spotify": self.SPOTIFY, "Music": "A\tB\tC\t"})
        self.assertEqual(lagu["pemutar"], "spotify")

    def test_spotify_dijeda_jatuh_ke_music(self):
        lagu, ditanya = self._baca({"Spotify", "Music"}, {"Music": "A\tB\tC\t"})
        self.assertEqual(ditanya, ["Spotify", "Music"])
        self.assertEqual(lagu["judul"], "A")

    def test_abaikan_pemutar_berlaku(self):
        lagu, ditanya = self._baca({"Spotify"}, {"Spotify": self.SPOTIFY}, abaikan=["spotify"])
        self.assertIsNone(lagu)
        self.assertEqual(ditanya, [])

    def test_ruas_kosong_di_ujung_tidak_hilang(self):
        # Skrip Music selalu diakhiri tab & "" -- strip() biasa ikut memakan
        # tab itu dan lagunya tidak pernah tampil. Lewat subprocess.run
        # sungguhan, bukan _osascript palsu, supaya pembersihannya ikut teruji.
        balasan = subprocess.CompletedProcess([], 0, "Judul\tArtis\tAlbum\t\n", "")
        with mock.patch.object(cm, "_jalan", lambda n: n == "Music"), \
                mock.patch.object(cm.subprocess, "run", return_value=balasan):
            lagu = cm.lagu_mac()
        self.assertEqual((lagu["judul"], lagu["album"], lagu["sampul_mentah"]), ("Judul", "Album", ""))

    def test_ruas_kurang_tetap_terbaca_selama_ada_judul(self):
        self.assertEqual(cm._urai_mac("Spotify", "Judul\tArtis")["artis"], "Artis")

    def test_izin_automation_ditolak_cuma_diperingatkan_sekali(self):
        ditolak = subprocess.CompletedProcess([], 1, "", "execution error: Not authorized (-1743)")
        with mock.patch.object(cm.subprocess, "run", return_value=ditolak), \
                mock.patch.object(cm, "_sudah_diperingatkan", False), \
                mock.patch("sys.stderr") as err:
            self.assertEqual(cm._osascript("x"), "")
            self.assertEqual(cm._osascript("x"), "")
        self.assertEqual(sum("-1743" in str(c) for c in err.write.call_args_list), 1)

    @unittest.skipUnless(sys.platform == "darwin", "pgrep macOS")
    def test_pgrep_sungguhan_mengenali_proses(self):
        # Proses milik sendiri: pgrep di sandbox tidak melihat proses root.
        tidur = subprocess.Popen(["sleep", "30"])
        self.addCleanup(tidur.wait)
        self.addCleanup(tidur.kill)
        self.assertTrue(cm._jalan("sleep"))
        self.assertFalse(cm._jalan("tidak-ada-proses-bernama-ini"))


class UjiWindows(unittest.TestCase):
    """Windows Media Session lewat PowerShell; keluarannya JSON."""

    def sesi(self, **k):
        d = {"app": "Spotify.exe", "status": "Playing", "judul": "Lagu", "artis": "Artis", "album": "Album"}
        d.update(k)
        return d

    def test_nama_pemutar_dari_aumid(self):
        for app, nama in (("Spotify.exe", "spotify"), ("Chrome", "chrome"), ("MSEdge", "msedge"),
                          ("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "microsoft.zunemusic"),
                          (None, "")):
            with self.subTest(app=app):
                self.assertEqual(cm._pemutar_windows(app), nama)

    def test_yang_playing_dipilih(self):
        teks = json.dumps([self.sesi(status="Paused", judul="Dijeda"), self.sesi(judul="Jalan")])
        self.assertEqual(cm._urai_windows(teks)["judul"], "Jalan")

    def test_satu_sesi_berupa_objek_bukan_larik(self):
        # ConvertTo-Json di PowerShell 5.1 membuka larik satu elemen.
        self.assertEqual(cm._urai_windows(json.dumps(self.sesi()))["pemutar"], "spotify")

    def test_pemutar_musik_menang_atas_browser(self):
        teks = json.dumps([self.sesi(app="Chrome", judul="Video"), self.sesi(judul="Musik")])
        self.assertEqual(cm._urai_windows(teks)["judul"], "Musik")

    def test_abaikan_pemutar_berlaku(self):
        teks = json.dumps([self.sesi(), self.sesi(app="Chrome", judul="Video")])
        self.assertEqual(cm._urai_windows(teks, ["spotify"])["pemutar"], "chrome")

    def test_keluaran_rusak_atau_kosong_tidak_melempar(self):
        for teks in ("", "[]", "bukan json", "5", json.dumps([None, "x", self.sesi(judul="")])):
            with self.subTest(teks=teks):
                self.assertIsNone(cm._urai_windows(teks))

    def test_bentuk_lagu_sama_dengan_mpris(self):
        lagu = cm._urai_windows(json.dumps([self.sesi()]))
        self.assertEqual(set(lagu), {"judul", "artis", "album", "sampul_mentah", "pemutar"})

    @unittest.skipUnless(sys.platform == "win32", "PowerShell + WinRT cuma di Windows")
    def test_skrip_powershell_sungguhan_jalan(self):
        hasil = cm._powershell()
        self.assertEqual(hasil.returncode, 0, hasil.stderr.decode("utf-8", "replace"))
        self.assertIsInstance(json.loads(hasil.stdout.decode("utf-8") or "[]"), list)


class UjiSumberPerOs(unittest.TestCase):
    def test_tiap_os_dapat_pembacanya(self):
        for platform, sumber in (("linux", cm.lagu_sekarang), ("darwin", cm.lagu_mac),
                                 ("win32", cm.lagu_windows)):
            with self.subTest(platform=platform), mock.patch.object(cm.sys, "platform", platform):
                self.assertIs(cm.sumber_bawaan(), sumber)


if __name__ == "__main__":
    unittest.main(verbosity=2)
