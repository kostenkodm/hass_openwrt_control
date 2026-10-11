"""Confine trusted OpenWrt rootfs links before modifying a chroot from Linux."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
root = (ROOT / "work/native-rootfs").resolve()
assert os.name == "posix", "Run from Linux: Windows cannot inspect LX_SYMLINK safely"
for path in root.rglob("*"):
    if path.is_symlink():
        target = os.readlink(path)
        if target.startswith("/"):
            path.unlink()
            path.symlink_to(os.path.relpath(root / target.lstrip("/"), path.parent))
        assert path.resolve().is_relative_to(root), "Escaping rootfs link"
assert (root / "etc/ssl/cert.pem").resolve().is_relative_to(root)
print("PASS rootfs symlinks remain inside the lab")
