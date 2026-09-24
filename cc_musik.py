"""Pembacaan lagu yang sedang diputar, per OS.

* Linux: MPRIS di D-Bus sesi (``lagu_sekarang``).
* macOS: AppleScript ke Spotify dan Music (``lagu_mac``). Tab browser tidak
  terbaca -- API now-playing sistem dikunci Apple sejak macOS 15.4.
* Windows: Windows Media Session lewat PowerShell (``lagu_windows``); semua
  yang muncul di panel media Windows terbaca, tab browser termasuk.

Ketiganya membalas bentuk yang sama, jadi sisa daemon tidak perlu tahu OS.

Di Linux dipakai `busctl --json=short` alih-alih pustaka D-Bus mana pun: pip sistem
terkunci PEP 668, dan busctl sudah pasti ada karena bagian dari systemd.
Keluarannya JSON, jadi tidak ada penguraian teks yang rapuh.

Hampir semua pemutar di Linux mengumumkan diri lewat MPRIS -- Spotify,
VLC, mpv, dan tab browser (Brave/Chrome/Firefox) termasuk. Jadi ini tidak
terikat ke satu aplikasi.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys

AWALAN = "org.mpris.MediaPlayer2."
_IFACE = "org.mpris.MediaPlayer2.Player"
_OBJ = "/org/mpris/MediaPlayer2"
_TIMEOUT = 2.0

# Kalau beberapa pemutar sedang jalan sekaligus, yang khusus musik menang
# atas tab browser -- browser sering ketinggalan video yang dijeda.
PRIORITAS = ("spotify", "spotifyd", "mpd", "vlc", "mpv", "rhythmbox", "audacious", "elisa")


def _busctl(*argumen: str):
    try:
        hasil = subprocess.run(
            ["busctl", "--user", "--json=short", *argumen],
            capture_output=True, text=True, encoding="utf-8", timeout=_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if hasil.returncode != 0:
        return None
    try:
        return json.loads(hasil.stdout).get("data")
    except (ValueError, AttributeError):
        return None


def daftar_pemutar() -> list[str]:
    data = _busctl("call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                   "org.freedesktop.DBus", "ListNames")
    if not data:
        return []
    # ListNames membalas satu larik berisi larik nama.
    nama = data[0] if data and isinstance(data[0], list) else data
    return sorted({n for n in nama if isinstance(n, str) and n.startswith(AWALAN)})


def _peringkat(nama: str) -> int:
    pendek = nama.lower()
    for i, p in enumerate(PRIORITAS):
        if pendek.startswith(p):
            return i
    return len(PRIORITAS)


def _urutan(bus: str) -> tuple[int, str]:
    return (_peringkat(bus[len(AWALAN):]), bus)


def _properti(bus: str, nama: str):
    return _busctl("get-property", bus, _OBJ, _IFACE, nama)


def _teks(nilai) -> str:
    """Ratakan nilai MPRIS jadi teks; xesam:artist berupa larik."""
    if isinstance(nilai, dict):
        nilai = nilai.get("data")
    if isinstance(nilai, list):
        return ", ".join(str(x) for x in nilai if x)
    return str(nilai).strip() if nilai is not None else ""


def _cocok(nama: str, abaikan) -> bool:
    pendek = nama.lower()
    return any(pendek.startswith(str(a).lower()) for a in abaikan if str(a).strip())


def _diabaikan(bus: str, abaikan) -> bool:
    return _cocok(bus[len(AWALAN):], abaikan)


def lagu_sekarang(abaikan=()) -> dict | None:
    """Lagu dari pemutar pertama yang berstatus Playing, atau None.

    ``abaikan`` berisi awalan nama pemutar yang tidak boleh dibaca sama
    sekali, mis. ``("brave", "firefox")`` untuk menutup judul video browser.
    """
    for bus in sorted(daftar_pemutar(), key=_urutan):
        if _diabaikan(bus, abaikan):
            continue
        if _properti(bus, "PlaybackStatus") != "Playing":
            continue
        meta = _properti(bus, "Metadata")
        if not isinstance(meta, dict):
            continue
        judul = _teks(meta.get("xesam:title"))
        if not judul:
            continue  # tanpa judul tidak ada yang bisa ditampilkan
        return {
            "judul": judul,
            "artis": _teks(meta.get("xesam:artist")),
            "album": _teks(meta.get("xesam:album")),
            # Pemutar berbasis browser mengisi ini dengan berkas sementara di
            # /tmp; yang lain menyodorkan URL yang langsung bisa dipakai.
            "sampul_mentah": _teks(meta.get("mpris:artUrl")),
            "pemutar": bus[len(AWALAN):].split(".")[0],
        }
    return None


# -- macOS ------------------------------------------------------------------

# Nama proses -> skrip. Urutannya urutan prioritas. Satu skrip per pemutar,
# bukan satu skrip gabungan: AppleScript mengompilasi kamus tiap aplikasi
# yang disebut, jadi skrip yang menyebut Spotify gagal total di Mac yang
# tidak memasangnya.
_SKRIP_MAC = {
    "Spotify": ('tell application "Spotify" to if player state is playing then return '
                '(name of current track) & tab & (artist of current track) & tab & '
                '(album of current track) & tab & (artwork url of current track)'),
    "Music": ('tell application "Music" to if player state is playing then return '
              '(name of current track) & tab & (artist of current track) & tab & '
              '(album of current track) & tab & ""'),
}
_sudah_diperingatkan = False


def _jalan(proses: str) -> bool:
    """Apakah proses bernama persis itu sedang jalan.

    Wajib dicek dulu: ``tell application`` ke aplikasi yang mati justru
    menyalakannya. pgrep, bukan ps -- ps di sandbox bisa menyembunyikan
    proses milik sesi lain, pgrep tidak.
    """
    try:
        return subprocess.run(["pgrep", "-xq", proses], timeout=_TIMEOUT).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _osascript(skrip: str) -> str:
    global _sudah_diperingatkan
    try:
        hasil = subprocess.run(["osascript", "-e", skrip], capture_output=True, text=True,
                               encoding="utf-8", timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    if "-1743" in hasil.stderr and not _sudah_diperingatkan:
        # Di bawah launchd yang meminta izin adalah python3, bukan Terminal,
        # jadi izin yang sudah diberikan ke Terminal tidak berlaku.
        _sudah_diperingatkan = True
        print("musik: macOS menolak akses ke pemutar (-1743). Izinkan lewat System Settings"
              " > Privacy & Security > Automation, lalu muat ulang daemon.",
              file=sys.stderr, flush=True)
    # Cuma akhir baris yang dibuang: strip() biasa ikut memakan tab penutup
    # ruas sampul yang kosong.
    return hasil.stdout.rstrip("\r\n") if hasil.returncode == 0 else ""


def _urai_mac(pemutar: str, teks: str) -> dict | None:
    ruas = [r.strip() for r in teks.split("\t")] + ["", "", ""]
    if not ruas[0]:
        return None
    return {"judul": ruas[0], "artis": ruas[1], "album": ruas[2],
            "sampul_mentah": ruas[3], "pemutar": pemutar.lower()}


def lagu_mac(abaikan=()) -> dict | None:
    for proses, skrip in _SKRIP_MAC.items():
        if _cocok(proses, abaikan) or not _jalan(proses):
            continue
        lagu = _urai_mac(proses, _osascript(skrip))
        if lagu:
            return lagu
    return None


# -- Windows ----------------------------------------------------------------

# PowerShell 5.1 bawaan Windows bisa memanggil WinRT; AsTask dipakai untuk
# menunggu operasi async-nya. Keluarannya JSON dalam UTF-8.
_SKRIP_WINDOWS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Tunggu($op, $tipe) {
  $t = $asTask.MakeGenericMethod($tipe).Invoke($null, @($op))
  $t.Wait(-1) | Out-Null
  $t.Result
}
$M = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
$P = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties,Windows.Media.Control,ContentType=WindowsRuntime]
$sesi = @((Tunggu ($M::RequestAsync()) $M).GetSessions() | ForEach-Object {
  $p = Tunggu ($_.TryGetMediaPropertiesAsync()) $P
  @{ app = $_.SourceAppUserModelId; status = [string]$_.GetPlaybackInfo().PlaybackStatus
     judul = $p.Title; artis = $p.Artist; album = $p.AlbumTitle }
})
ConvertTo-Json -InputObject $sesi -Compress
"""


def _powershell() -> subprocess.CompletedProcess:
    # -EncodedCommand (base64 UTF-16LE) menghindari urusan kutip sama sekali.
    kode = base64.b64encode(_SKRIP_WINDOWS.encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", kode],
        capture_output=True, timeout=10,
        # Daemon jalan di bawah pythonw; tanpa ini tiap pembacaan memunculkan
        # jendela konsol sekejap.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _pemutar_windows(app) -> str:
    """AUMID -> nama pendek: ``Spotify.exe`` -> ``spotify``, ``Microsoft.ZuneMusic_8we…!App`` -> ``microsoft.zunemusic``."""
    nama = str(app or "").split("!")[0].lower()
    if nama.endswith(".exe"):
        nama = nama[:-4]
    return nama.split("_")[0]


def _urai_windows(teks: str, abaikan=()) -> dict | None:
    try:
        data = json.loads(teks or "[]")
    except ValueError:
        return None
    if isinstance(data, dict):  # ConvertTo-Json membuka larik satu elemen
        data = [data]
    if not isinstance(data, list):
        return None
    kandidat = []
    for s in data:
        if not isinstance(s, dict) or s.get("status") != "Playing":
            continue
        pemutar = _pemutar_windows(s.get("app"))
        judul = str(s.get("judul") or "").strip()
        if not judul or _cocok(pemutar, abaikan):
            continue
        kandidat.append({"judul": judul, "artis": str(s.get("artis") or "").strip(),
                         "album": str(s.get("album") or "").strip(),
                         # Sampulnya aliran data, bukan URL -- dicari lewat iTunes.
                         "sampul_mentah": "", "pemutar": pemutar})
    kandidat.sort(key=lambda lagu: _peringkat(lagu["pemutar"]))
    return kandidat[0] if kandidat else None


def lagu_windows(abaikan=()) -> dict | None:
    try:
        hasil = _powershell()
    except (OSError, subprocess.SubprocessError):
        return None
    if hasil.returncode != 0:
        return None
    return _urai_windows(hasil.stdout.decode("utf-8", "replace"), abaikan)


def sumber_bawaan():
    """Pembaca lagu untuk OS yang sedang jalan."""
    return {"darwin": lagu_mac, "win32": lagu_windows}.get(sys.platform, lagu_sekarang)


# PowerShell makan ~0,5 dtk CPU tiap dipanggil, dan penerbitan presence
# memang direm 15 dtk -- membacanya lebih sering tidak mempercepat apa pun.
JEDA_BAWAAN = 15.0 if sys.platform == "win32" else 5.0


class PembacaMusik:
    """Pembungkus ``lagu_sekarang`` dengan singgahan.

    Daemon berdenyut tiap detik, tapi lagu tidak berganti secepat itu dan
    tiap pembacaan memanggil beberapa proses ``busctl``.
    """

    def __init__(self, jeda: float = JEDA_BAWAAN, sumber=None, abaikan=()) -> None:
        self.jeda = jeda
        self._sumber = sumber or sumber_bawaan()
        self._abaikan = tuple(abaikan)
        self._nilai: dict | None = None
        self._kapan = float("-inf")

    def sekarang(self, waktu: float) -> dict | None:
        if waktu - self._kapan >= self.jeda:
            self._nilai = self._sumber(self._abaikan)
            self._kapan = waktu
        return self._nilai
