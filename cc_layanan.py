"""Autostart daemon per OS.

* Linux: systemd user, dipasang ``pasang.sh``; di sini cuma dimuat ulang.
* macOS: LaunchAgent -- launchd yang menyalakan saat login dan menyalakan
  ulang kalau daemon jatuh.
* Windows: nilai ``Run`` di HKCU plus ``pythonw``, tanpa hak admin dan
  tanpa jendela konsol.

Windows tidak punya pengawas proses yang bisa diminta berhenti dengan
sopan, dan ``os.kill`` di sana selalu berarti TerminateProcess -- presence
dan spool tidak sempat dibereskan. Jadi daemon diminta berhenti lewat berkas
tanda yang ia periksa tiap denyut.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cc_daemon

LABEL = "io.github.lamiore.lagi-ngapain"
NAMA_RUN = "lagi-ngapain"
KUNCI_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
DAEMON = Path(__file__).resolve().with_name("cc_daemon.py")


def _jalankan(*argumen: str) -> bool:
    try:
        return subprocess.run(list(argumen), capture_output=True).returncode == 0
    except OSError:
        return False


# -- macOS ------------------------------------------------------------------

def jalur_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def jalur_log_mac() -> Path:
    return Path.home() / "Library" / "Logs" / "lagi-ngapain.log"


def python_mac() -> str:
    """python3 dari PATH, bukan sys.executable.

    Di Homebrew sys.executable menunjuk ke Cellar yang berversi
    (``…/python@3.14/…``) dan putus diam-diam saat brew naik versi mayor;
    ``/opt/homebrew/bin/python3`` ikut pindah sendiri.
    """
    return shutil.which("python3") or sys.executable


def isi_plist(python: str, daemon: Path) -> dict:
    log = str(jalur_log_mac())
    return {
        "Label": LABEL,
        "ProgramArguments": [python, str(daemon)],
        "RunAtLoad": True,
        # Nyalakan ulang kalau jatuh, tapi tidak kalau keluar dengan sengaja:
        # client_id yang ditolak keluar dengan kode 0.
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


# -- Windows ----------------------------------------------------------------

def pythonw() -> str:
    w = Path(sys.executable).with_name("pythonw.exe")
    return str(w) if w.exists() else sys.executable


def perintah_run(daemon: Path) -> str:
    return f'"{pythonw()}" "{daemon}"'


def hentikan(tenggat: float = 15.0) -> bool:
    """Minta daemon berhenti lewat berkas tanda. True kalau ia sempat beres.

    Tenggatnya melebihi batas waktu PowerShell di cc_musik (10 dtk): daemon
    yang sedang menunggu pembacaan lagu baru melihat tandanya sesudah itu.
    Kalau tidak ada yang menjawab, daemonnya sudah mati tanpa membereskan
    spool -- sisanya dibuang di sini.
    """
    spool = cc_daemon.dir_spool()
    if not spool.exists():
        return True
    tanda = spool.parent / cc_daemon.BERHENTI
    tanda.touch()
    batas = time.monotonic() + tenggat
    while time.monotonic() < batas:
        if not spool.exists():
            return True
        time.sleep(0.1)
    tanda.unlink(missing_ok=True)
    (spool.parent / cc_daemon.DETAK).unlink(missing_ok=True)
    shutil.rmtree(spool, ignore_errors=True)
    return False


def _nyalakan_windows() -> None:
    # Sengaja tanpa stdin/stdout/stderr: dengan salah satunya diisi, anak
    # mewarisi konsol pemasang dan mati saat jendela itu ditutup. Tanpa
    # ketiganya sys.stdout di pythonw bernilai None dan daemon menulis log
    # ke berkasnya sendiri.
    subprocess.Popen([pythonw(), str(DAEMON)], close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS
                     | subprocess.CREATE_NEW_PROCESS_GROUP)


def _terpasang_windows() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KUNCI_RUN) as k:
            winreg.QueryValueEx(k, NAMA_RUN)
        return True
    except OSError:
        return False


# -- antarmuka --------------------------------------------------------------

def pasang() -> str:
    if sys.platform == "darwin":
        jalur = jalur_plist()
        jalur.parent.mkdir(parents=True, exist_ok=True)
        jalur_log_mac().parent.mkdir(parents=True, exist_ok=True)
        with open(jalur, "wb") as f:
            plistlib.dump(isi_plist(python_mac(), DAEMON), f)
        _jalankan("launchctl", "bootout", f"{_domain()}/{LABEL}")  # versi lama, kalau ada
        # bootout selesai secara asinkron; bootstrap yang terlalu cepat
        # ditolak dengan "Input/output error".
        for _ in range(10):
            if _jalankan("launchctl", "bootstrap", _domain(), str(jalur)):
                return f"LaunchAgent jalan -- log: {jalur_log_mac()}"
            time.sleep(0.5)
        return f"LaunchAgent GAGAL dimuat: launchctl bootstrap {_domain()} {jalur}"
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KUNCI_RUN, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, NAMA_RUN, 0, winreg.REG_SZ, perintah_run(DAEMON))
        hentikan()
        _nyalakan_windows()
        return f"autostart dipasang, daemon jalan -- log: {cc_daemon.jalur_log()}"
    raise RuntimeError("di Linux pakai ./pasang.sh")


def copot() -> str:
    if sys.platform == "darwin":
        _jalankan("launchctl", "bootout", f"{_domain()}/{LABEL}")
        jalur_plist().unlink(missing_ok=True)
        return "LaunchAgent dicabut"
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KUNCI_RUN, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, NAMA_RUN)
        except OSError:
            pass
        hentikan()
        return "autostart dicabut, daemon dihentikan"
    raise RuntimeError("di Linux pakai ./copot.sh")


def terpasang() -> bool:
    """Apakah autostart daemon sudah dipasang di OS ini."""
    if sys.platform == "darwin":
        return jalur_plist().exists()
    if sys.platform == "win32":
        return _terpasang_windows()
    return (Path.home() / ".config" / "systemd" / "user" / "lagi-ngapain.service").exists()


def muat_ulang() -> bool:
    """Nyalakan ulang daemon supaya konfig baru terbaca. False kalau belum terpasang."""
    if sys.platform == "darwin":
        return _jalankan("launchctl", "kickstart", "-k", f"{_domain()}/{LABEL}")
    if sys.platform == "win32":
        if not _terpasang_windows():
            return False
        hentikan()
        _nyalakan_windows()
        return True
    return _jalankan("systemctl", "--user", "restart", "lagi-ngapain.service")
