"""Build local review archives, excluding credentials, caches and reference clones."""
import hashlib
from pathlib import Path
import subprocess
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / "custom_components/openwrt_vpn/manifest.json").read_text())["version"]
OUT = ROOT / "outputs" / "prototype"
SOURCES = ["custom_components", "simulator", "tools", "tests", "docs", "openwrt", "examples", ".github"]
ROOT_FILES = ["LICENSE", "README.md", ".gitignore", ".gitattributes", "hacs.json", "pyproject.toml", "requirements-dev.txt", "requirements-lock.txt"]


def public_files():
    # Honor Git's ignore rules, including locally retained private documents.
    result = subprocess.check_output([
        "git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"
    ])
    return [ROOT / name for name in result.decode().split("\0") if name]


def permitted(path):
    return (path.name not in {"technical-specification.ru.md", "environment.ru.md"}
            and not any(p in {"__pycache__", ".pytest_cache", ".ruff_cache"} for p in path.parts)
            and path.suffix not in {".pyc", ".pem", ".key"}
            and not path.name.startswith(".env"))


def archive(name, paths):
    target = OUT / name
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(set(paths)):
            if path.is_file() and permitted(path):
                z.write(path, path.relative_to(ROOT))
    return target


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    files = public_files()
    integration = [p for p in files if p.relative_to(ROOT).parts[0] == "custom_components"]
    packages = [archive(f"openwrt-vpn-ha-{VERSION}.zip", integration + [ROOT / "hacs.json"])]
    source = [p for p in files if p.relative_to(ROOT).parts[0] in SOURCES]
    packages.append(archive(f"hass-openwrt-prototype-{VERSION}.zip",
                            source + [ROOT / f for f in ROOT_FILES]))
    manifest = "\n".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in packages) + "\n"
    (OUT / "SHA256SUMS.txt").write_text(manifest)
    print("Created two local archives; credentials and reference repositories excluded.")
