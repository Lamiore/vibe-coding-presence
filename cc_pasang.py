"""Pemasangan dan pencabutan hook lagi-ngapain di settings.json Claude Code.

Bagian ini dipisah supaya bisa diuji: menyunting ``~/.claude/settings.json``
yang sudah memuat hook lain (rtk, context-mode, plugin) adalah bagian paling
mudah merusak dari seluruh alat ini. Aturannya dua: jangan pernah menyentuh
entri milik orang lain, dan pemasangan ulang tidak boleh menggandakan apa pun.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from cc_state import PERISTIWA

# Penanda yang membedakan hook kita dari milik alat lain. Pencabutan
# mencocokkan substring ini, jadi jangan diubah tanpa alasan. Sengaja tanpa
# ekstensi: cocok dengan .sh (Linux) maupun .py (macOS, Windows).
PENANDA = "lagi-ngapain-hook"


def jalur_settings() -> Path:
    dasar = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(dasar) / "settings.json"


def _muat(jalur: Path) -> dict:
    try:
        isi = json.loads(jalur.read_text(encoding="utf-8"))
        return isi if isinstance(isi, dict) else {}
    except (OSError, ValueError):
        return {}


def _tulis(jalur: Path, data: dict) -> None:
    jalur.parent.mkdir(parents=True, exist_ok=True)
    sementara = jalur.with_suffix(".json.tmp")
    sementara.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sementara.replace(jalur)


def _punya_kita(entri: dict) -> bool:
    for h in entri.get("hooks", []):
        if not isinstance(h, dict):
            continue
        # Di exec form penandanya ada di args; command cuma jalur python.
        args = h.get("args") if isinstance(h.get("args"), list) else []
        if any(PENANDA in str(x) for x in [h.get("command", ""), *args]):
            return True
    return False


def pasang(perintah: str, jalur: Path | None = None, cadangkan: bool = True,
           args: list[str] | None = None) -> tuple[bool, str]:
    """Sisipkan hook ke tiap peristiwa yang dipakai. Idempoten.

    ``args`` memasang exec form: Claude Code menjalankan ``perintah`` langsung
    dengan argumen itu, tanpa shell -- bentuk yang dipakai di macOS dan Windows.
    """
    jalur = jalur or jalur_settings()
    data = _muat(jalur)
    if cadangkan and jalur.exists():
        shutil.copy2(jalur, jalur.with_suffix(".json.sebelum-lagi-ngapain"))

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return False, "kunci 'hooks' di settings.json bukan objek -- dibiarkan, perbaiki manual"

    ditambah = []
    for ev in PERISTIWA:
        daftar = hooks.setdefault(ev, [])
        if not isinstance(daftar, list):
            return False, f"hooks.{ev} bukan larik -- dibiarkan, perbaiki manual"
        if any(_punya_kita(e) for e in daftar if isinstance(e, dict)):
            continue  # sudah terpasang
        hook = {"type": "command", "command": perintah}
        if args is not None:
            hook["args"] = list(args)
        daftar.append({"hooks": [hook]})
        ditambah.append(ev)

    _tulis(jalur, data)
    if not ditambah:
        return True, "hook sudah terpasang sebelumnya, tidak ada yang diubah"
    return True, "hook dipasang di: " + ", ".join(ditambah)


def copot(jalur: Path | None = None) -> tuple[bool, str]:
    """Cabut hanya entri milik lagi-ngapain; entri lain tidak disentuh."""
    jalur = jalur or jalur_settings()
    if not jalur.exists():
        return True, "settings.json tidak ada, tidak ada yang dicabut"
    data = _muat(jalur)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return True, "tidak ada hook yang terpasang"

    dicabut = []
    for ev, daftar in list(hooks.items()):
        if not isinstance(daftar, list):
            continue
        sisa = [e for e in daftar if not (isinstance(e, dict) and _punya_kita(e))]
        if len(sisa) == len(daftar):
            continue
        # Kunci yang jadi kosong dibuang seluruhnya: larik kosong dan kunci
        # yang tidak ada artinya sama bagi Claude Code, dan membuangnya
        # membuat pasang-lalu-copot mengembalikan berkas ke bentuk semula.
        if sisa:
            hooks[ev] = sisa
        else:
            del hooks[ev]
        dicabut.append(ev)

    if not dicabut:
        return True, "hook lagi-ngapain tidak ditemukan, tidak ada yang diubah"
    _tulis(jalur, data)
    return True, "hook dicabut dari: " + ", ".join(dicabut)


def terpasang(jalur: Path | None = None) -> list[str]:
    """Daftar peristiwa yang hook-nya sudah terpasang."""
    hooks = _muat(jalur or jalur_settings()).get("hooks")
    if not isinstance(hooks, dict):
        return []
    return [
        ev for ev, daftar in hooks.items()
        if isinstance(daftar, list) and any(_punya_kita(e) for e in daftar if isinstance(e, dict))
    ]
