"""Fetch pinned lab-only dependencies into ignored work; verify before use."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(folder, name, item):
    target = folder / name
    if target.exists():
        if sha256(target) != item["sha256"]:
            raise RuntimeError("Existing download checksum mismatch: " + name)
        return
    temporary = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(item["url"], timeout=60) as response, temporary.open("wb") as stream:
        while chunk := response.read(1024 * 1024):
            stream.write(chunk)
    if sha256(temporary) != item["sha256"]:
        raise RuntimeError("Downloaded checksum mismatch: " + name)
    temporary.replace(target)


def checkout(path, item, sparse=False):
    def git(*args):
        return subprocess.check_output(["git", "-c", "safe.directory=" + str(path), "-C", str(path), *args])
    if not (path / ".git").exists():
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        git("remote", "add", "origin", item["url"])
    head = subprocess.run(["git", "-c", "safe.directory=" + str(path), "-C", str(path),
                           "rev-parse", "--verify", "HEAD"], capture_output=True)
    if head.returncode:
        git("remote", "set-url", "origin", item["url"])
        git("fetch", "--depth=1", "origin", item["commit"])
        if sparse:
            git("sparse-checkout", "init", "--no-cone")
            git("sparse-checkout", "set", "/*", "!/tests/fuzz/corpus/")
        git("checkout", "--detach", item["commit"])
    if git("rev-parse", "HEAD").decode().strip() != item["commit"]:
        raise RuntimeError("Source revision mismatch: " + path.name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk", action="store_true")
    parser.add_argument("--sources", action="store_true")
    args = parser.parse_args()
    lock = json.loads((ROOT / "tools/native-dependencies.json").read_text())
    folder = ROOT / "work/native-downloads"
    folder.mkdir(parents=True, exist_ok=True)
    for name, item in lock["downloads"].items():
        if "sdk" not in name or args.sdk:
            download(folder, name, item)
    for version, item in lock["podkop_versions"].items():
        checkout(ROOT / f"work/references/podkop-{version}", item)
    if args.sources:
        for name, item in lock["sources"].items():
            checkout(ROOT / "work/native-locked-src" / name, item, name == "uci")
    print("Pinned lab dependencies verified; no router was accessed.")


if __name__ == "__main__":
    main()
