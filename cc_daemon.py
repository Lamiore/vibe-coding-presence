#!/usr/bin/env python3
"""Daemon lagi-ngapain: menyalakan Discord Rich Presence untuk Claude Code.

Hook Claude Code berumur sangat pendek -- prosesnya mati begitu selesai,
dan Rich Presence ikut hilang saat soketnya tertutup. Jadi hook hanya
menumpahkan muatannya ke spool, dan proses inilah yang memegang koneksi
IPC serta menerbitkan pembaruan dengan laju yang aman.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cc_konfig
from cc_ipc import DiscordTidakAda, KlienDiscord
from cc_musik import PembacaMusik
import cc_sampul
from cc_sampul import PencariSampul
from cc_state import Registry

# Jeda antar denyut. Jauh lebih rapat dari jeda penerbitan supaya peristiwa
# cepat terserap; penerbitannya sendiri yang direm.
DENYUT = 1.0
# Jeda coba-sambung ulang saat Discord tidak ada.
JEDA_SAMBUNG = 10.0
# Berkas spool yang JSON-nya belum utuh dibiarkan selama ini sebelum
# dianggap rusak -- menutup lomba baca/tulis tanpa membebani hook.
TENGGANG_RUSAK = 3.0
# Dua berkas di samping spool, pengganti pengawas proses di OS yang tidak
# punya systemd. Detak disentuh tiap denyut; hook Python diam kalau detaknya
# basi. Tanda berhenti ditaruh pemasang untuk meminta daemon keluar dengan
# rapi -- di Windows os.kill selalu berarti TerminateProcess.
DETAK = "detak"
BERHENTI = "berhenti"

# Penanda "belum pernah menerbitkan apa pun". Tidak bisa memakai None karena
# None adalah muatan yang sah (artinya: kosongkan presence).
BELUM_PERNAH = object()


def dir_spool() -> Path:
    return cc_konfig.dir_runtime() / "lagi-ngapain" / "ev"


def jalur_log() -> Path:
    """Log daemon kalau tidak ada yang menampung stdout-nya (pythonw di Windows)."""
    return cc_sampul.jalur_singgahan().parent / "daemon.log"


def _urai_boottime(teks: str) -> float:
    """``sysctl -n kern.boottime`` -> epoch: ``{ sec = 1790039066, usec = ... } ...``."""
    return float(int(teks.split("sec =")[1].split(",")[0]))


def waktu_nyala_pc(jalur_stat: Path = Path("/proc/stat")) -> float:
    """Kapan PC dinyalakan, dalam epoch detik.

    ``btime`` di /proc/stat angka bulat yang tetap sepanjang boot, jadi
    daemon yang dimuat ulang menerbitkan timer yang persis sama. Kalau
    berkasnya tidak kebaca (sandbox bisa menyembunyikan /proc), dihitung
    dari jam CLOCK_BOOTTIME -- yang ikut menghitung masa suspend, sama
    seperti ``uptime``. macOS dan Windows tidak punya keduanya dan ditanya
    lewat jalannya sendiri.
    """
    try:
        for baris in jalur_stat.read_text(encoding="utf-8").splitlines():
            if baris.startswith("btime "):
                return float(int(baris.split()[1]))
    except (OSError, ValueError, IndexError):
        pass
    if sys.platform == "darwin":
        try:
            return _urai_boottime(subprocess.run(
                ["sysctl", "-n", "kern.boottime"], capture_output=True, text=True,
                encoding="utf-8", timeout=2).stdout)
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            pass
    if sys.platform == "win32":
        import ctypes
        detak = ctypes.windll.kernel32.GetTickCount64
        detak.restype = ctypes.c_uint64
        return float(round(time.time() - detak() / 1000))
    if hasattr(time, "CLOCK_BOOTTIME"):
        return float(round(time.time() - time.clock_gettime(time.CLOCK_BOOTTIME)))
    return float(round(time.time()))  # jalan terakhir: timer mulai dari sekarang


def _log(*a) -> None:
    baris = " ".join([time.strftime("[%H:%M:%S]"), *map(str, a)])
    try:
        print(baris, flush=True)
    except UnicodeEncodeError:
        # Konsol cp1252 di Windows tidak kenal emoji; log tidak boleh
        # menjatuhkan daemon.
        print(baris.encode("ascii", "replace").decode("ascii"), flush=True)


def _siapkan_keluaran() -> None:
    """Log selalu UTF-8: emoji di presence meledakkan cp1252 di Windows."""
    if sys.stdout is None:  # pythonw di Windows: tidak ada konsol sama sekali
        log = jalur_log()
        log.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(log, "w", encoding="utf-8", buffering=1)
        return
    for aliran in (sys.stdout, sys.stderr):
        if hasattr(aliran, "reconfigure"):
            aliran.reconfigure(encoding="utf-8", errors="replace")


class Daemon:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.spool = dir_spool()
        self.berkas_detak = self.spool.parent / DETAK
        self.tanda_berhenti = self.spool.parent / BERHENTI
        self.registry = Registry(
            ttl=cfg["ttl_sesi"],
            mode=cfg["mode"],
            proyek_privat=cfg["proyek_privat"],
            tampilkan_timer=cfg["tampilkan_timer"],
            # Dibaca sekali di sini, bukan tiap denyut: angka yang goyang
            # sedikit saja bikin muatannya dianggap berubah dan diterbitkan ulang.
            mulai_tetap=waktu_nyala_pc() if cfg["sumber_timer"] == "nyala_pc" else 0.0,
            label=cfg["label"],
            tipe_kerja=cfg["tipe_kerja"],
            tipe_musik=cfg["tipe_musik"],
            kartu_kosong=cfg["kartu_kosong"],
            sampul_saat_kerja=cfg["sampul_saat_kerja"],
        )
        self.klien = KlienDiscord(cfg["client_id"])
        # Dibaca berkala, bukan tiap denyut: satu pembacaan memanggil
        # beberapa proses busctl, sementara lagu tidak berganti tiap detik.
        self.musik = PembacaMusik(abaikan=cfg["abaikan_pemutar"]) if cfg["musik"] else None
        # Mode minimal menjanjikan judul lagu tidak ke mana-mana -- termasuk
        # tidak ke API pencarian sampul.
        self.sampul = (PencariSampul() if self.musik and cfg.get("sampul", True)
                       and cfg["mode"] != "minimal" else None)
        self.terakhir_terbit = 0.0
        self.terakhir_muatan = BELUM_PERNAH
        self.coba_sambung_lagi = 0.0
        self.jalan = True

    # -- spool --------------------------------------------------------------

    def siapkan_spool(self) -> None:
        """Membuat direktori spool -- inilah yang 'menyalakan' hook."""
        self.spool.mkdir(parents=True, exist_ok=True)
        for f in self.spool.iterdir():  # buang sisa jalan sebelumnya
            f.unlink(missing_ok=True)
        # Tanda yang tidak sempat dijawab daemon lama tidak boleh langsung
        # mematikan daemon yang baru.
        self.tanda_berhenti.unlink(missing_ok=True)
        self.detak()

    def detak(self) -> None:
        try:
            self.berkas_detak.touch()
        except OSError:
            pass

    def bereskan_spool(self) -> None:
        """Menghapus direktori spool supaya hook kembali jadi no-op."""
        self.berkas_detak.unlink(missing_ok=True)
        try:
            for f in self.spool.iterdir():
                f.unlink(missing_ok=True)
            self.spool.rmdir()
        except OSError:
            pass

    def serap_peristiwa(self, sekarang: float) -> bool:
        """Baca seluruh berkas spool sesuai urutan waktu. True kalau berubah."""
        try:
            berkas = sorted(self.spool.iterdir(), key=lambda p: p.name)
        except OSError:
            return False

        berubah = False
        for f in berkas:
            try:
                ev = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Kemungkinan besar hook masih menulisnya. Biarkan dulu;
                # kalau tetap tidak terbaca sampai tenggang, baru dibuang.
                try:
                    if sekarang - f.stat().st_mtime > TENGGANG_RUSAK:
                        f.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            f.unlink(missing_ok=True)
            if isinstance(ev, dict) and self.registry.terapkan(ev, sekarang):
                berubah = True
        return berubah

    def lagu_kini(self, sekarang: float):
        """Lagu yang sedang diputar, dilengkapi URL sampulnya kalau ketemu.

        Pencariannya di sini, bukan di Registry: Registry sengaja tidak
        menyentuh jaringan supaya perakitan presence tetap murni logika.
        """
        lagu = self.musik.sekarang(sekarang) if self.musik else None
        if lagu and self.sampul:
            lagu = dict(lagu, sampul=self.sampul.untuk(lagu))
        return lagu

    # -- penerbitan ---------------------------------------------------------

    def pastikan_tersambung(self, sekarang: float) -> bool:
        if self.klien.tersambung:
            return True
        if sekarang < self.coba_sambung_lagi:
            return False
        try:
            self.klien.sambung()
            _log("tersambung ke Discord")
            # Paksa terbit ulang: presence hilang saat koneksi putus.
            self.terakhir_muatan = BELUM_PERNAH
            self.terakhir_terbit = 0.0
            return True
        except ValueError as e:  # client_id ditolak -- tidak ada gunanya mengulang
            # Keluar dengan kode 0 disengaja: Restart=on-failure tidak boleh
            # memutar ulang daemon yang konfigurasinya salah.
            _log("FATAL:", e)
            _log("Perbaiki client_id di", cc_konfig.jalur_konfig())
            self.jalan = False
            return False
        except DiscordTidakAda:
            self.coba_sambung_lagi = sekarang + JEDA_SAMBUNG
            return False

    def terbitkan(self, activity, sekarang: float) -> None:
        if activity == self.terakhir_muatan:
            return
        if sekarang - self.terakhir_terbit < self.cfg["jeda_publish"]:
            return  # direm: Discord membatasi laju SET_ACTIVITY
        try:
            self.klien.set_activity(activity)
        except DiscordTidakAda as e:
            _log("koneksi putus:", e)
            self.coba_sambung_lagi = sekarang + JEDA_SAMBUNG
            return
        self.terakhir_muatan = activity
        self.terakhir_terbit = sekarang
        if activity is None:
            _log("presence dikosongkan")
        else:
            from cc_state import TIPE_VALID
            ruas = [TIPE_VALID.get(activity.get("type"), "?"), activity.get("details")]
            if activity.get("state"):  # kartu kosong tidak punya baris kedua
                ruas.append(activity["state"])
            # Gambar yang ditolak Discord tidak menimbulkan galat apa pun,
            # jadi journal ini satu-satunya tanda sampulnya ikut terkirim.
            if activity.get("assets", {}).get("large_image"):
                ruas.append("+sampul")
            _log("presence:", " | ".join(ruas))

    # -- daur hidup ---------------------------------------------------------

    def berhenti(self, *a) -> None:
        self.jalan = False

    def jalankan(self) -> int:
        if not self.cfg["client_id"]:
            _log("client_id belum diisi di", cc_konfig.jalur_konfig())
            _log("Buat aplikasi di https://discord.com/developers/applications,")
            _log('namai mis. "Terminal", lalu salin Application ID-nya ke situ.')
            return 2

        signal.signal(signal.SIGTERM, self.berhenti)
        signal.signal(signal.SIGINT, self.berhenti)
        self.siapkan_spool()
        _log("daemon jalan, spool:", self.spool, "| mode:", self.cfg["mode"])

        try:
            while self.jalan:
                if self.tanda_berhenti.exists():
                    self.tanda_berhenti.unlink(missing_ok=True)
                    _log("diminta berhenti")
                    break
                self.detak()
                sekarang = time.time()
                self.serap_peristiwa(sekarang)
                self.registry.bersihkan(sekarang)
                if self.pastikan_tersambung(sekarang):
                    self.terbitkan(self.registry.rakit(sekarang, self.lagu_kini(sekarang)), sekarang)
                time.sleep(DENYUT)
        finally:
            if self.klien.tersambung:
                try:
                    self.klien.set_activity(None)
                except DiscordTidakAda:
                    pass
                self.klien.tutup()
            self.bereskan_spool()
            _log("daemon berhenti")
        return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Discord Rich Presence untuk Claude Code CLI")
    p.add_argument("--mode", choices=cc_konfig.MODE_VALID, help="timpa tingkat privasi sekali jalan")
    p.add_argument("--client-id", help="timpa Application ID sekali jalan")
    p.add_argument("--status", action="store_true", help="tampilkan keadaan lalu keluar")
    p.add_argument("--musik", choices=("on", "off"),
                   help="nyalakan/matikan tampilan lagu, lalu muat ulang service")
    args = p.parse_args(argv)

    cfg = cc_konfig.muat()
    if args.mode:
        cfg["mode"] = args.mode
    if args.client_id:
        cfg["client_id"] = args.client_id.strip()

    if args.musik:
        cfg["musik"] = args.musik == "on"
        cc_konfig.simpan(cfg)
        print("musik:", "nyala" if cfg["musik"] else "MATI")
        # Daemon membaca konfig sekali saat start, jadi perubahannya baru
        # berlaku setelah dimuat ulang. Dilakukan di sini supaya "tombol
        # panik" benar-benar satu perintah.
        import cc_layanan
        print("service:", "dimuat ulang" if cc_layanan.muat_ulang() else "belum jalan, tidak dimuat ulang")
        return 0

    if args.status:
        from cc_ipc import cari_soket
        print("konfig       :", cc_konfig.jalur_konfig())
        print("client_id    :", cfg["client_id"] or "(belum diisi)")
        print("mode privasi :", cfg["mode"])
        print("musik        :", "nyala" if cfg["musik"] else "mati",
              ("(abaikan: " + ", ".join(cfg["abaikan_pemutar"]) + ")") if cfg["abaikan_pemutar"] else "")
        singgahan = cc_sampul.jalur_singgahan()
        print("sampul       :", "nyala" if cfg["sampul"] else "mati",
              "(kartu kerja ikut)" if cfg["sampul_saat_kerja"] else "(kartu musik saja)",
              "|", singgahan if singgahan.exists() else f"{singgahan} (belum ada)")
        if not cfg["tampilkan_timer"]:
            print("timer        : mati")
        elif cfg["sumber_timer"] == "nyala_pc":
            print("timer        : sejak PC nyala,",
                  time.strftime("%Y-%m-%d %H:%M", time.localtime(waktu_nyala_pc())))
        else:
            print("timer        : sejak sesi Claude Code tertua (kartu kerja saja)")
        print("soket Discord:", ", ".join(cari_soket()) or "(tidak ketemu -- Discord belum jalan?)")
        spool = dir_spool()
        print("spool        :", spool, "(aktif)" if spool.is_dir() else "(daemon mati)")
        return 0

    _siapkan_keluaran()
    return Daemon(cfg).jalankan()


if __name__ == "__main__":
    raise SystemExit(main())
