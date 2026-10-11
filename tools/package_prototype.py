"""Build local review archives, excluding credentials, caches and reference clones."""
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "prototype"
SOURCES = ["custom_components", "simulator", "tools", "tests", "docs", "openwrt", "examples", ".github"]
ROOT_FILES = ["README.md", ".gitignore", ".gitattributes", "hacs.json", "pyproject.toml", "requirements-dev.txt", "requirements-lock.txt"]


def permitted(path):
    return (not any(p in {"__pycache__", ".pytest_cache", ".ruff_cache"} for p in path.parts)
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
    integration = list((ROOT / "custom_components").rglob("*"))
    packages = [archive("openwrt-vpn-ha-0.1.0.zip", integration + [ROOT / "hacs.json"])]
    source = [p for folder in SOURCES for p in (ROOT / folder).rglob("*")]
    packages.append(archive("hass-openwrt-prototype-0.1.0.zip",
                            source + [ROOT / f for f in ROOT_FILES]))
    manifest = "\n".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in packages) + "\n"
    (OUT / "SHA256SUMS.txt").write_text(manifest)
    print("Created two local archives; credentials and reference repositories excluded.")
