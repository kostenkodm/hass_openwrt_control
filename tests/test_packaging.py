"""The HACS directory must run without the repository's developer helpers."""
import json
import shutil
import subprocess
import sys


def test_hacs_runtime_isolated_from_repository(root, tmp_path):
    install = tmp_path / "install"
    shutil.copytree(root / "custom_components", install / "custom_components",
                    ignore=shutil.ignore_patterns("__pycache__"))
    assert [p.name for p in (install / "custom_components").iterdir() if p.is_dir()] == ["openwrt_vpn"]
    manifest = json.loads((install / "custom_components/openwrt_vpn/manifest.json").read_text())
    assert {"domain", "name", "version", "codeowners", "documentation", "issue_tracker"} <= manifest.keys()
    assert manifest["domain"] == "openwrt_vpn"
    assert (install / "custom_components/openwrt_vpn/brand/icon.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from custom_components.openwrt_vpn import config_flow, sensor, select, switch, button, binary_sensor
from custom_components.openwrt_vpn.demo.runtime import prepare
controller, credentials, server_context, client_context = prepare(Path(sys.argv[2]), "hacs-isolated-demo")
assert controller.data["controller_id"] == "hacs-isolated-demo"
assert client_context.check_hostname
assert len(controller.data["sections"]) == 3
assert not any(name in sys.modules for name in ("simulator", "tools"))
print("isolated HACS runtime OK")
"""
    result = subprocess.run([sys.executable, "-I", "-c", script, str(install), str(tmp_path / "demo")],
                            cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "isolated HACS runtime OK"
