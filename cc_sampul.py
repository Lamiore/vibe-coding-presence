"""Pencarian sampul album untuk kartu musik.

Discord menerima URL ``https://`` mentah di ``assets.large_image`` -- klien
Discord sendiri yang menandatanganinya ke media proxy miliknya, jadi tidak
ada berkas yang perlu diunggah ke mana pun. Yang dibutuhkan modul ini cuma
satu URL yang bisa dijangkau publik.

Sebagian pemutar (Spotify desktop, mpd) sudah menyodorkan URL semacam itu
lewat ``mpris:artUrl``. Pemutar berbasis browser tidak: Chromium menulis
sampulnya ke berkas sementara di ``/tmp``, yang tidak berarti apa-apa buat
Discord. Untuk kasus itu sampulnya dicari lewat iTunes Search API -- tanpa
kunci, tanpa akun -- lalu disinggahi supaya satu lagu cuma ditanyakan sekali.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Denyut daemon satu detik; permintaan tanpa tenggat bisa membekukannya.
TENGGANG = 3.0
BATAS_SINGGAHAN = 200
# Tenggat urllib berlaku per operasi soket, bukan per permintaan, jadi
# pencarian yang macet bisa menahan denyut daemon beberapa kali TENGGANG.
# Galat tidak boleh disinggahi permanen, tapi juga tidak boleh diulang tiap
# denyut -- ini jarak minimum sebelum lagu yang sama dicoba lagi.
MASA_TENANG = 60.0
_UA = "lagi-ngapain (+https://github.com/Lamiore/vibe-coding-presence)"


def jalur_singgahan() -> Path:
    """Tempat singgahan sampul.

    ``CACHE_DIRECTORY`` disodorkan systemd lewat ``CacheDirectory=`` di berkas
    unit, dan itu satu-satunya jalur yang boleh ditulis service ini:
    sandboxnya (``ProtectHome=read-only``) bikin ~/.cache read-only, sehingga
    tanpa mengikutinya singgahan gagal ditulis diam-diam tiap lagu baru.
    Isinya sudah menunjuk ke direktori milik service, jadi tidak ditambahi
    nama aplikasi lagi. Beberapa direktori dipisah titik dua.
    """
    dari_systemd = (os.environ.get("CACHE_DIRECTORY") or "").split(":")[0].strip()
    if dari_systemd:
        return Path(dari_systemd) / "sampul.json"
    dasar = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(dasar) / "lagi-ngapain" / "sampul.json"


def dari_art_url(art_url) -> str:
    """URL sampul yang sudah siap pakai, atau "" kalau tidak ada."""
    teks = str(art_url or "").strip()
    return teks if teks.startswith(("http://", "https://")) else ""


def kunci(lagu: dict) -> str:
    """Penanda lagu untuk singgahan -- sengaja tidak memakai nama berkas.

    Chromium memakai ulang jalur berkas sementaranya dengan akhiran acak
    yang baru tiap lagu, jadi jalur itu bukan penanda yang stabil.
    """
    def ambil(k: str) -> str:
        return " ".join(str(lagu.get(k) or "").split()).lower()
    return "|".join((ambil("artis"), ambil("album"), ambil("judul")))


def _ambil_json(url: str):
    permintaan = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(permintaan, timeout=TENGGANG) as balasan:
        return json.loads(balasan.read().decode("utf-8", "replace"))


def _percobaan(artis: str, album: str, judul: str) -> list[tuple[str, str]]:
    """Kueri yang dicoba berurutan, dari yang paling tepat.

    Album lebih dulu kalau ada: satu album punya satu sampul, sedangkan
    pencarian per lagu bisa nyasar ke rilis lain milik artis yang sama.
    Tapi ``entity=album`` sering nihil walau albumnya jelas ada -- diukur ke
    API sungguhan, "LANY a beautiful blur (deluxe)" tidak membalas apa-apa
    sementara "LANY XXL (Stripped)" per lagu ketemu. Jadi pencarian per lagu
    dipakai sebagai jatuhan, bukan pengganti.
    """
    urut = []
    if album:
        urut.append(("album", " ".join(x for x in (artis, album) if x)))
    if judul:
        urut.append(("song", " ".join(x for x in (artis, judul) if x)))
    return [(entitas, istilah.strip()) for entitas, istilah in urut if istilah.strip()]


def cari_itunes(artis: str, album: str, judul: str) -> str:
    """Cari sampul lewat iTunes Search API. "" kalau tidak ketemu.

    Paling banyak dua permintaan, jadi kasus terburuknya dua kali TENGGANG.
    """
    for entitas, istilah in _percobaan(artis, album, judul):
        url = ("https://itunes.apple.com/search?term=" + urllib.parse.quote_plus(istilah)
               + "&entity=" + entitas + "&limit=1")
        hasil = (_ambil_json(url) or {}).get("results") or []
        # Bawaannya 100 piksel -- terlalu kecil untuk kartu Discord, dan
        # ukurannya memang cuma ruas di dalam URL-nya.
        seni = str((hasil[0] if hasil else {}).get("artworkUrl100") or "")
        if seni:
            return seni.replace("100x100bb", "600x600bb")
    return ""


class PencariSampul:
    """Pemetaan lagu -> URL sampul, dengan singgahan yang bertahan di disk."""

    def __init__(self, cari=cari_itunes, jalur=None, batas: int = BATAS_SINGGAHAN,
                 jam=time.monotonic, masa_tenang: float = MASA_TENANG) -> None:
        self._cari = cari
        self.jalur = Path(jalur) if jalur else jalur_singgahan()
        self.batas = max(1, int(batas))
        self._jam = jam
        self.masa_tenang = masa_tenang
        self._peta = self._muat()
        # Kunci yang pencariannya barusan galat, beserta kapan galatnya.
        # Sengaja tidak ikut ke disk: ini rem sesaat, bukan jawaban.
        self._gagal: dict[str, float] = {}

    def _muat(self) -> dict:
        try:
            isi = json.loads(self.jalur.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return isi if isinstance(isi, dict) else {}

    def _simpan(self) -> None:
        try:
            self.jalur.parent.mkdir(parents=True, exist_ok=True)
            sementara = self.jalur.with_suffix(".tmp")
            sementara.write_text(json.dumps(self._peta, ensure_ascii=False), encoding="utf-8")
            sementara.replace(self.jalur)
        except OSError:
            pass  # singgahan itu kenyamanan, bukan syarat

    def untuk(self, lagu) -> str:
        if not lagu or not lagu.get("judul"):
            return ""
        langsung = dari_art_url(lagu.get("sampul_mentah"))
        if langsung:
            return langsung

        k = kunci(lagu)
        if k in self._peta:
            return self._peta[k]

        sekarang = self._jam()
        gagal_terakhir = self._gagal.get(k)
        if gagal_terakhir is not None and sekarang - gagal_terakhir < self.masa_tenang:
            return ""
        try:
            hasil = self._cari(lagu.get("artis", ""), lagu.get("album", ""), lagu.get("judul", ""))
        except (OSError, ValueError):
            # Jaringan lagi mati atau balasannya rusak. Jangan disinggahi:
            # kalau disimpan sebagai "tidak ada", sampulnya tidak akan pernah
            # muncul lagi walau internetnya sudah pulih.
            self._gagal[k] = sekarang
            return ""
        self._gagal.pop(k, None)

        # "" ikut disimpan -- itu jawaban "memang tidak ketemu", dan tanpa
        # menyimpannya lagu tak dikenal akan ditanyakan terus-menerus.
        self._peta[k] = str(hasil or "")
        while len(self._peta) > self.batas:
            self._peta.pop(next(iter(self._peta)))
        self._simpan()
        return self._peta[k]
