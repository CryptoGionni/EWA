#!/usr/bin/env python
"""Estrae dal Windows dell'utente le icone delle app originali in ewa/assets/icons/<chiave>.ico.

Le icone Microsoft NON sono nel repository (vincolo legale): si estraggono al momento della build.
Chiavi: shell, hub, calculator, clock, camera, notepad.

Uso:  python packaging/extract_icons.py [--out DIR]
Dipendenze (solo build): pefile, pillow.  La build non fallisce se un'icona non si trova.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "ewa" / "assets" / "icons"

RT_ICON = 3
RT_GROUP_ICON = 14
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)

# chiave -> descrizione della sorgente
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
PE_SOURCES = {
    "shell": SYSTEM32 / "cmd.exe",
    "hub": SYSTEM32 / "cmd.exe",
    "notepad": SYSTEM32 / "notepad.exe",
}
UWP_SOURCES = {
    "calculator": "Microsoft.WindowsCalculator",
    "clock": "Microsoft.WindowsAlarms",
    "camera": "Microsoft.WindowsCamera",
}
# se l'app UWP manca: file .exe alternativo (solo la calcolatrice ne ha uno)
UWP_FALLBACK_PE = {"calculator": SYSTEM32 / "calc.exe"}


# ---------------------------------------------------------------- ICO da PE (Win32)

def assemble_ico(group_bytes: bytes, icons: dict[int, bytes]) -> bytes:
    """Ricostruisce un file .ico da un RT_GROUP_ICON e dai dati RT_ICON ({id: bytes}).

    GRPICONDIR: reserved, type, count; ogni GRPICONDIRENTRY (14 byte) termina con l'id
    della risorsa, che nel file .ico diventa l'offset (4 byte) dei dati.
    """
    reserved, kind, count = struct.unpack_from("<HHH", group_bytes, 0)
    if kind != 1:
        raise ValueError("non è un gruppo di icone (type != 1)")
    entries = []
    for i in range(count):
        w, h, colors, res, planes, bits, size, rid = struct.unpack_from(
            "<BBBBHHIH", group_bytes, 6 + 14 * i)
        data = icons.get(rid)
        if data is None:
            continue  # risorsa mancante: salta la voce
        entries.append((w, h, colors, res, planes, bits, data))
    if not entries:
        raise ValueError("nessun dato RT_ICON trovato per il gruppo")
    out = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    offset = 6 + 16 * len(entries)
    for w, h, colors, res, planes, bits, data in entries:
        out += struct.pack("<BBBBHHII", w, h, colors, res, planes, bits, len(data), offset)
        offset += len(data)
    for *_, data in entries:
        out += data
    return bytes(out)


def ico_from_pe(path: str | Path) -> bytes:
    """Il primo RT_GROUP_ICON di un PE (è l'icona principale mostrata da Windows)."""
    import pefile

    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        root = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
        if root is None:
            raise ValueError("nessuna risorsa nel file")

        def leaf(entry) -> bytes:
            d = entry.directory.entries[0].data.struct
            return pe.get_data(d.OffsetToData, d.Size)

        groups, icons = [], {}
        for top in root.entries:
            if top.id == RT_GROUP_ICON:
                groups = [leaf(e) for e in top.directory.entries]
            elif top.id == RT_ICON:
                icons = {e.id: leaf(e) for e in top.directory.entries}
        if not groups:
            raise ValueError("nessun gruppo icone nel file")
        return assemble_ico(groups[0], icons)
    finally:
        pe.close()


# ---------------------------------------------------------------- ICO da PNG (UWP)

def parse_manifest(xml_text: str) -> tuple[str, str]:
    """(Square44x44Logo, BackgroundColor) della prima Application. Ignora i namespace."""
    root = ET.fromstring(xml_text)
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "VisualElements":
            logo = el.get("Square44x44Logo")
            if logo:
                return logo, el.get("BackgroundColor", "transparent")
    raise ValueError("Square44x44Logo non trovato nel manifest")


def _parse_color(value: str) -> tuple[int, int, int, int] | None:
    v = (value or "").strip().lower()
    if not v or v == "transparent":
        return None
    if re.fullmatch(r"#[0-9a-f]{6}", v):
        return (int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16), 255)
    return None  # nomi di colore: non li gestiamo, meglio trasparente che sbagliato


def find_uwp_images(folder: str | Path, logo_rel: str, background: str = "transparent"):
    """Ritorna ({dimensione: Image RGBA}, descrizione della variante usata).

    Priorità: targetsize-N_altform-unplated (icona della barra delle applicazioni di
    Windows 10); poi targetsize-N composte sul BackgroundColor; infine scale-*.
    Le varianti contrast-/theme-/lightunplated non combaciano con i pattern e sono ignorate.
    """
    from PIL import Image

    logo = Path(folder) / logo_rel.replace("\\", "/")
    base, stem = logo.parent, logo.stem
    files = sorted(base.iterdir()) if base.is_dir() else []
    esc = re.escape(stem)
    bg = _parse_color(background)

    def load(p: Path, plate: bool):
        img = Image.open(p).convert("RGBA")
        if plate and bg:
            sq = Image.new("RGBA", img.size, bg)
            sq.alpha_composite(img)
            img = sq
        return img

    unplated = {int(m.group(1)): p for p in files
                if (m := re.fullmatch(esc + r"\.targetsize-(\d+)_altform-unplated\.png", p.name, re.I))}
    if unplated:
        return {s: load(p, False) for s, p in unplated.items()}, "targetsize-N_altform-unplated"
    plated = {int(m.group(1)): p for p in files
              if (m := re.fullmatch(esc + r"\.targetsize-(\d+)\.png", p.name, re.I))}
    if plated:
        return {s: load(p, True) for s, p in plated.items()}, "targetsize-N su BackgroundColor"
    scaled = [p for p in files if re.fullmatch(esc + r"\.scale-\d+\.png", p.name, re.I)]
    if scaled:
        best = max(scaled, key=lambda p: int(re.search(r"scale-(\d+)", p.name).group(1)))
        img = load(best, True)
        return {img.width: img}, f"{best.name} (scale)"
    raise FileNotFoundError(f"nessuna immagine '{stem}' in {base}")


def _dib_entry(img) -> bytes:
    """Voce ICO classica (BMP 32 bit + maschera AND) per dimensioni < 256."""
    w, h = img.size
    px = img.convert("RGBA").tobytes()
    rows = []
    for y in range(h - 1, -1, -1):  # dal basso verso l'alto, BGRA
        row = px[y * w * 4:(y + 1) * w * 4]
        rows.append(b"".join(bytes((row[i + 2], row[i + 1], row[i], row[i + 3]))
                             for i in range(0, len(row), 4)))
    mask = b"\x00" * (((w + 31) // 32) * 4 * h)
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, w * h * 4, 0, 0, 0, 0)
    return header + b"".join(rows) + mask


def compose_ico(images: dict, sizes=ICO_SIZES) -> bytes:
    """.ico multi-risoluzione: usa l'immagine esatta se c'è, altrimenti ridimensiona la più grande."""
    from PIL import Image

    if not images:
        raise ValueError("nessuna immagine")
    biggest = images[max(images)]
    entries = []
    for s in sizes:
        img = images.get(s)
        if img is None:
            img = biggest.resize((s, s), Image.LANCZOS)
        if img.size != (s, s):
            img = img.resize((s, s), Image.LANCZOS)
        if s >= 256:
            buf = io.BytesIO()
            img.save(buf, "PNG")
            data = buf.getvalue()
        else:
            data = _dib_entry(img)
        entries.append((s, data))
    out = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    offset = 6 + 16 * len(entries)
    for s, data in entries:
        d = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", d, d, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in entries:
        out += data
    return bytes(out)


def ico_from_uwp(install_dir: str | Path) -> tuple[bytes, str]:
    install_dir = Path(install_dir)
    logo, bg = parse_manifest((install_dir / "AppxManifest.xml").read_text(encoding="utf-8"))
    images, how = find_uwp_images(install_dir, logo, bg)
    return compose_ico(images), how


def uwp_install_location(package: str) -> Path | None:
    """InstallLocation del pacchetto UWP, via PowerShell (None se non installato)."""
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
           f"(Get-AppxPackage -Name {package} | Select -First 1).InstallLocation"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    loc = r.stdout.strip()
    return Path(loc) if loc and Path(loc).is_dir() else None


# ---------------------------------------------------------------- orchestrazione

def extract_all(out_dir: Path = DEFAULT_OUT, log=print) -> dict[str, str]:
    """Estrae tutte le icone possibili; ritorna {chiave: descrizione sorgente}. Non solleva."""
    out_dir.mkdir(parents=True, exist_ok=True)
    done: dict[str, str] = {}

    def save(key: str, data: bytes, source: str):
        (out_dir / f"{key}.ico").write_bytes(data)
        done[key] = source
        log(f"[ok]  {key}.ico  <-  {source}")

    def from_pe(key: str, exe: Path) -> bool:
        try:
            save(key, ico_from_pe(exe), str(exe))
            return True
        except Exception as e:  # noqa: BLE001 - la build non deve fallire
            log(f"[!!]  {key}: impossibile estrarre l'icona da {exe}: {e}")
            return False

    for key, exe in PE_SOURCES.items():
        from_pe(key, exe)
    for key, pkg in UWP_SOURCES.items():
        loc = uwp_install_location(pkg)
        if loc:
            try:
                data, how = ico_from_uwp(loc)
                save(key, data, f"{pkg} ({how}) in {loc}")
                continue
            except Exception as e:  # noqa: BLE001
                log(f"[!!]  {key}: lettura di {pkg} fallita: {e}")
        else:
            log(f"[!!]  {key}: app {pkg} non trovata (Get-AppxPackage)")
        fb = UWP_FALLBACK_PE.get(key)
        if fb and fb.exists() and from_pe(key, fb):
            continue
        log(f"[!!]  AVVISO: nessuna icona per '{key}': l'exe userà l'icona predefinita")
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Estrae le icone delle app Windows originali.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"cartella di uscita (default: {DEFAULT_OUT})")
    args = ap.parse_args(argv)
    if sys.platform != "win32":
        print("[!!]  Non sei su Windows: le icone non possono essere estratte.")
        return 0
    done = extract_all(args.out)
    print(f"Estratte {len(done)}/{len(PE_SOURCES) + len(UWP_SOURCES)} icone in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
