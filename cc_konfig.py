"""Konfigurasi lagi-ngapain.

Menyimpan Application ID Discord dan tingkat privasi. Berkasnya di
``$XDG_CONFIG_HOME/lagi-ngapain/konfig.json`` (bawaan ``~/.config``).

Tingkat privasi (``mode``) sengaja bawaannya kasar: Rich Presence terbaca
oleh seluruh daftar teman, jadi jalur berkas dan isi perintah tidak pernah
ditampilkan kecuali diminta eksplisit.

* ``minimal`` -- tidak ada nama proyek sama sekali.
* ``normal``  -- nama folder proyek saja (bawaan).
* ``detail``  -- tambah nama berkas yang disunting / perintah yang dijalankan.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MODE_VALID = ("minimal", "normal", "detail")
SUMBER_TIMER_VALID = ("nyala_pc", "sesi")

BAWAAN: dict = {
    # Application ID dari https://discord.com/developers/applications
    # Nama aplikasinya jadi baris paling atas di presence. "Claude Code"
    # ditolak Discord (nama merek), jadi pakai nama lain, mis. "Terminal".
    "client_id": "",
    "mode": "normal",
    # Proyek yang namanya tidak boleh tampil walau mode >= normal.
    # Dicocokkan ke nama folder, tidak peka huruf besar-kecil.
    "proyek_privat": [],
    # Discord membatasi laju SET_ACTIVITY (~5 per 20 detik). Nilai ini
    # jarak minimum antar penerbitan, bukan jarak polling.
    "jeda_publish": 15,
    # Sesi yang tidak mengirim kabar selama ini dianggap mati. Menjaga
    # presence tidak nyangkut kalau terminal ditutup paksa (SessionEnd
    # tidak sempat jalan).
    "ttl_sesi": 900,
    "tampilkan_timer": True,
    # Dari mana timer dihitung. "nyala_pc": sejak PC dinyalakan, sama di
    # semua kartu dan tidak kereset saat daemon dimuat ulang. "sesi": sejak
    # sesi Claude Code tertua, cuma di kartu kerja (perilaku lama).
    "sumber_timer": "nyala_pc",
    # Kata di pojok atas presence: 0 Playing, 2 Listening to, 3 Watching,
    # 5 Competing in. Nilai lain ditolak Discord, jadi disaring di sini.
    # Tetap tampilkan presence walau tidak ada sesi dan tidak ada yang diputar.
    "kartu_kosong": True,
    "tipe_kerja": 0,
    "tipe_musik": 2,
    # Tampilkan lagu yang sedang diputar saat tidak ada yang dikerjakan.
    "musik": True,
    # Cari sampul album lagu yang sedang diputar. Untuk pemutar berbasis
    # browser sampulnya tidak ikut di metadata, jadi artis dan judulnya
    # dikirim ke iTunes Search API (tanpa akun, tanpa kunci). Matikan kalau
    # tidak mau lagunya diketahui pihak lain.
    "sampul": True,
    # Pasang sampulnya juga di kartu kerja, bukan cuma saat nganggur. Slot
    # gambar itu yang biasanya diisi ikon aplikasi, jadi mematikan ini
    # berarti ikon aplikasinya tetap terlihat selagi ngoding.
    "sampul_saat_kerja": True,
    # Awalan nama pemutar yang tidak boleh dibaca sama sekali, mis.
    # ["brave", "firefox"] untuk menutup judul video dari browser.
    "abaikan_pemutar": [],
    # Timpaan label kegiatan, mis. {"Bash": "Ngetik perintah", "idle": "Rehat"}.
    # Kunci yang tidak disebut memakai bawaan di cc_state.LABEL_BAWAAN.
    "label": {},
}


def dir_runtime() -> Path:
    """Folder per pengguna tempat soket Discord dan spool berada.

    ``XDG_RUNTIME_DIR`` didahulukan di semua OS: Discord sendiri memeriksanya
    lebih dulu, dan uji memakainya untuk membelokkan spool. macOS jatuh ke
    ``$TMPDIR`` -- di situ Discord menaruh soketnya -- dan karena launchd
    tidak selalu mengisinya, ditanyakan ke ``getconf``. Windows memakai
    ``%LOCALAPPDATA%``: jalurnya sama dari terminal mana pun, sedangkan TEMP
    di Git Bash bisa menunjuk ke tempat lain.
    """
    dasar = os.environ.get("XDG_RUNTIME_DIR")
    if dasar:
        return Path(dasar)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    if sys.platform == "darwin":
        dasar = os.environ.get("TMPDIR") or _getconf("DARWIN_USER_TEMP_DIR")
        if dasar:
            return Path(dasar)
    return Path(f"/run/user/{os.getuid()}")


def _getconf(nama: str) -> str:
    try:
        return subprocess.run(["getconf", nama], capture_output=True, text=True,
                              encoding="utf-8", timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def jalur_konfig() -> Path:
    dasar = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(dasar) / "lagi-ngapain" / "konfig.json"


def muat(jalur: Path | None = None) -> dict:
    """Baca konfigurasi, lengkapi kunci yang hilang dengan bawaan."""
    jalur = jalur or jalur_konfig()
    cfg = dict(BAWAAN)
    try:
        isi = json.loads(jalur.read_text(encoding="utf-8"))
        if isinstance(isi, dict):
            cfg.update({k: v for k, v in isi.items() if k in BAWAAN})
    except (OSError, ValueError):
        pass

    if cfg["mode"] not in MODE_VALID:
        cfg["mode"] = BAWAAN["mode"]
    if cfg["sumber_timer"] not in SUMBER_TIMER_VALID:
        cfg["sumber_timer"] = BAWAAN["sumber_timer"]
    if not isinstance(cfg["proyek_privat"], list):
        cfg["proyek_privat"] = []
    from cc_state import TIPE_KERJA, TIPE_MUSIK, TIPE_VALID
    for kunci, bawaan in (("tipe_kerja", TIPE_KERJA), ("tipe_musik", TIPE_MUSIK)):
        try:
            cfg[kunci] = int(cfg[kunci])
        except (TypeError, ValueError):
            cfg[kunci] = bawaan
        if cfg[kunci] not in TIPE_VALID:
            cfg[kunci] = bawaan
    if not isinstance(cfg["abaikan_pemutar"], list):
        cfg["abaikan_pemutar"] = []
    if not isinstance(cfg["label"], dict):
        cfg["label"] = {}
    else:
        # Nilai non-teks akan meledak saat dirakit; buang di sini selagi murah.
        cfg["label"] = {str(k): str(v) for k, v in cfg["label"].items() if isinstance(v, str)}
    # Jeda di bawah 15 detik menabrak batas laju Discord.
    cfg["jeda_publish"] = max(15, int(cfg["jeda_publish"] or 15))
    cfg["ttl_sesi"] = max(60, int(cfg["ttl_sesi"] or 900))
    cfg["client_id"] = str(cfg["client_id"] or "").strip()
    return cfg


def simpan(cfg: dict, jalur: Path | None = None) -> Path:
    jalur = jalur or jalur_konfig()
    jalur.parent.mkdir(parents=True, exist_ok=True)
    sementara = jalur.with_suffix(".tmp")
    sementara.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sementara.replace(jalur)
    return jalur
