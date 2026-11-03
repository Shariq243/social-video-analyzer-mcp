"""Build a source-only Windows release using an explicit, secret-checked allowlist."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def selected_files():
    files = {
        "Setup.cmd": ROOT / "Setup.cmd",
        "video_platforms.py": ROOT / "video_platforms.py",
        "README.md": ROOT / "windows" / "README.md",
        "LICENSE": ROOT / "LICENSE",
        "SECURITY.md": ROOT / "SECURITY.md",
        ".gitignore": ROOT / ".gitignore",
        "requirements-windows.txt": ROOT / "requirements-windows.txt",
        "requirements-dev.txt": ROOT / "requirements-dev.txt",
    }
    for folder in ["backend/app", "mcp-server", "windows"]:
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".ps1", ".cmd", ".toml"}:
                files[path.relative_to(ROOT).as_posix()] = path
    for name in ["Start-Backend.ps1", "Start-MCP.ps1", "Start-Tunnel.ps1",
                 "Connect-Insta-Analyzer.ps1", "smoke_test.py", "build_release.py"]:
        files["scripts/" + name] = ROOT / "scripts" / name
    files["windows/README.md"] = ROOT / "windows/README.md"
    for path in (ROOT / 'docs' / 'clients').glob('*.md'):
        files[path.relative_to(ROOT).as_posix()] = path
    return files


def private_literals():
    """Read known local secrets only for comparison; never emit their values."""
    from dotenv import dotenv_values
    values = []
    for path in [ROOT / "backend/.env", ROOT / ".env.local", ROOT / "mcp-server/.env.sse"]:
        if path.exists():
            for key, value in dotenv_values(path).items():
                if value and len(value) >= 12 and any(x in key.upper() for x in ["KEY", "TOKEN", "PASSWORD", "SECRET"]):
                    values.append(value.encode("utf-8"))
    for profile in (ROOT / ".tools").glob("tunnel-profiles/*.yaml"):
        values.extend(x.encode() for x in re.findall(r'tunnel_id:\s*"?(tunnel_[A-Za-z0-9]+)', profile.read_text(encoding="utf-8")))
    return values


def build(destination):
    files = selected_files()
    forbidden = private_literals()
    contents = {}
    for name, path in files.items():
        data = path.read_bytes()
        if any(secret in data for secret in forbidden):
            raise RuntimeError("Release blocked: a private local credential or tunnel ID occurs in " + name)
        if any(part in {".env", ".env.local", ".insta-analyzer", ".tools", ".venv", "__pycache__"} for part in Path(name).parts):
            raise RuntimeError("Release blocked: private/runtime file selected")
        contents[name] = data
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())}
    contents["SOURCE-SHA256.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            archive.writestr("insta-analyzer/" + name, data)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(contents)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(digest + "  " + destination.name + "\n", encoding="utf-8")
    print(f"Source release built and inspected: {len(contents)} files; no known local credentials or tunnel IDs included.")
    print(str(destination.resolve()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "Social-Video-Analyzer-Windows.zip")
    build(parser.parse_args().output)
