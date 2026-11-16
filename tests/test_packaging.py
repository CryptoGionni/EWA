"""Test della logica pura del packaging (girano anche su Linux)."""
import importlib.util
import io
import struct
import sys
from pathlib import Path

import pytest
from PIL import Image

PKG = Path(__file__).resolve().parents[1] / "packaging"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, PKG / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ei = _load("extract_icons")
build = _load("build")


def _png(size, color):
    buf = io.BytesIO()
    Image.new("RGBA", (size, size), color).save(buf, "PNG")
    return buf.getvalue()


# ---------- ICO da gruppo + risorse RT_ICON

def test_assemble_ico_da_gruppo():
    d1, d2 = b"A" * 30, b"B" * 50
    group = struct.pack("<HHH", 0, 1, 3)
    group += struct.pack("<BBBBHHIH", 16, 16, 0, 0, 1, 32, 30, 7)
    group += struct.pack("<BBBBHHIH", 0, 0, 0, 0, 1, 32, 50, 9)
    group += struct.pack("<BBBBHHIH", 32, 32, 0, 0, 1, 32, 99, 11)  # dati assenti: saltata
    ico = ei.assemble_ico(group, {7: d1, 9: d2})
    assert struct.unpack_from("<HHH", ico) == (0, 1, 2)
    w, h, _, _, planes, bits, size, off = struct.unpack_from("<BBBBHHII", ico, 6)
    assert (w, h, planes, bits, size, off) == (16, 16, 1, 32, 30, 6 + 32)
    off2 = struct.unpack_from("<I", ico, 6 + 16 + 12)[0]
    assert ico[off:off + 30] == d1 and ico[off2:off2 + 50] == d2
    assert len(ico) == 6 + 32 + 80


def test_assemble_ico_errori():
    with pytest.raises(ValueError):
        ei.assemble_ico(struct.pack("<HHH", 0, 2, 0), {})
    with pytest.raises(ValueError):
        ei.assemble_ico(struct.pack("<HHH", 0, 1, 0), {})


# ---------- UWP

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10">
  <Applications><Application Id="App">
    <uap:VisualElements DisplayName="X" Square44x44Logo="Assets\\AppList.png"
        Square150x150Logo="Assets\\Big.png" BackgroundColor="#0078D7"/>
  </Application></Applications>
</Package>"""


def test_parse_manifest():
    assert ei.parse_manifest(MANIFEST) == ("Assets\\AppList.png", "#0078D7")
    with pytest.raises(ValueError):
        ei.parse_manifest("<Package/>")


def _fill(folder, names, color=(255, 0, 0, 255), size=None):
    (folder / "Assets").mkdir(parents=True, exist_ok=True)
    for n in names:
        s = size or int(n.split("targetsize-")[1].split(".")[0].split("_")[0]) if "targetsize" in n else 88
        Image.new("RGBA", (s, s), color).save(folder / "Assets" / n)


def test_preferisce_unplated_e_ignora_varianti(tmp_path):
    _fill(tmp_path, [
        "AppList.targetsize-32_altform-unplated.png",
        "AppList.targetsize-48_altform-unplated.png",
        "AppList.targetsize-32_altform-unplated_contrast-white.png",
        "AppList.targetsize-256_altform-lightunplated.png",
        "AppList.targetsize-24_altform-unplated_theme-light.png",
        "AppList.targetsize-32.png",
    ])
    imgs, how = ei.find_uwp_images(tmp_path, "Assets\\AppList.png", "#0078D7")
    assert sorted(imgs) == [32, 48] and "unplated" in how


def test_fallback_su_background(tmp_path):
    (tmp_path / "Assets").mkdir()
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(tmp_path / "Assets" / "AppList.targetsize-16.png")
    imgs, how = ei.find_uwp_images(tmp_path, "Assets\\AppList.png", "#0078D7")
    assert imgs[16].getpixel((0, 0)) == (0, 0x78, 0xD7, 255)
    imgs, _ = ei.find_uwp_images(tmp_path, "Assets\\AppList.png", "transparent")
    assert imgs[16].getpixel((0, 0))[3] == 0


def test_ultima_risorsa_scale(tmp_path):
    _fill(tmp_path, ["AppList.scale-100.png", "AppList.scale-200.png"])
    (tmp_path / "Assets" / "AppList.scale-200.png").unlink()
    Image.new("RGBA", (88, 88), "red").save(tmp_path / "Assets" / "AppList.scale-200.png")
    imgs, how = ei.find_uwp_images(tmp_path, "Assets\\AppList.png", "transparent")
    assert list(imgs) == [88] and "scale-200" in how
    with pytest.raises(FileNotFoundError):
        ei.find_uwp_images(tmp_path, "Assets\\Altro.png")


def test_ico_multirisoluzione(tmp_path):
    _fill(tmp_path, ["AppList.targetsize-32_altform-unplated.png",
                     "AppList.targetsize-48_altform-unplated.png"])
    (tmp_path / "AppxManifest.xml").write_text(MANIFEST, encoding="utf-8")
    data, how = ei.ico_from_uwp(tmp_path)
    count = struct.unpack_from("<HHH", data)[2]
    assert count == len(ei.ICO_SIZES)
    path = tmp_path / "x.ico"
    path.write_bytes(data)
    with Image.open(path) as ico:
        assert set(ico.info["sizes"]) == {(s, s) for s in ei.ICO_SIZES}
        ico.size = (48, 48)
        assert ico.convert("RGBA").getpixel((5, 5)) == (255, 0, 0, 255)


# ---------- build.py

def test_find_iscc(tmp_path):
    assert build.find_iscc({}, which=lambda n: "C:/x/ISCC.exe" if n == "ISCC" else None) == "C:/x/ISCC.exe"
    exe = tmp_path / "Inno Setup 6" / "ISCC.exe"
    exe.parent.mkdir()
    exe.write_text("")
    env = {"ProgramFiles(x86)": str(tmp_path)}
    assert build.find_iscc(env, which=lambda n: None) == str(exe)
    assert build.find_iscc({}, which=lambda n: None) is None


def test_comandi_build():
    cmd = build.iscc_command("ISCC.exe", "2.0.1")
    assert cmd[0] == "ISCC.exe" and "/DMyAppVersion=2.0.1" in cmd and cmd[-1].endswith("installer.iss")
    assert build.pyinstaller_command()[-3:] == [str(PKG / "ewa.spec"), "--noconfirm", "--clean"][-3:]


def test_rifiuta_non_windows(capsys, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert build.main([]) == 1
    assert "Windows" in capsys.readouterr().out


# ---------- installer.iss e spec

def test_installer_iss():
    iss = (PKG / "installer.iss").read_text(encoding="utf-8-sig")
    for s in ("PrivilegesRequired=lowest", "{localappdata}\\Programs\\EWA", "Italian.isl",
              "..\\dist\\EWA\\*", "OutputBaseFilename=EWA-Setup", "taskkill /IM MarvHub.exe /F",
              "winget", "Ollama.Ollama --accept-source-agreements --accept-package-agreements",
              "gemma4:e2b", "--setup", "Terminale EWA"):
        assert s in iss, s


def test_spec_nomi_exe():
    from ewa.core.launcher import EXE_NAMES
    spec = (PKG / "ewa.spec").read_text(encoding="utf-8")
    for name in EXE_NAMES.values():
        assert f'"{name}"' in spec
    for entry in (PKG / "entries").glob("*.py"):
        assert "sys.exit(main())" in entry.read_text(encoding="utf-8")
