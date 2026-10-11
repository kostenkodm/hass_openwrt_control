"""Provisioned RPC identity and TLS profile must not broaden router permissions."""
import json
import shutil
import ssl
import subprocess

import pytest

from tools.prepare_router_access import prepare
from tools import package_prototype


def test_rpc_profile_trust_permissions_and_no_overwrite(tmp_path, capsys):
    output = tmp_path / "access"
    prepare(output, "router.test", "10.20.0.1", shutil.which("openssl"))
    credentials = json.loads((output / "ha-connection.json").read_text())
    assert credentials["username"] == "hass-vpn"
    assert len(credentials["password"]) >= 32
    assert credentials["password"] not in capsys.readouterr().out
    rpc = (output / "rpcd.fragment").read_text()
    assert "hass-openwrt-vpn" in rpc and "'$6$" in rpc
    assert credentials["password"] not in rpc
    assert not any(word in rpc for word in ["root", "uci", "file", "network", "*"])
    uhttpd = (output / "uhttpd.fragment").read_text()
    assert "listen_https '10.20.0.1:8443'" in uhttpd
    assert "listen_http '" not in uhttpd and "0.0.0.0" not in uhttpd and "[::]" not in uhttpd
    context = ssl.create_default_context(cafile=str(output / "ca.pem"))
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    verification = [shutil.which("openssl"), "verify", "-x509_strict", "-CAfile", str(output / "ca.pem"),
                    "-verify_hostname", "router.test", str(output / "server.pem")]
    assert subprocess.run(verification, capture_output=True).returncode == 0
    verification[-2] = "wrong.test"
    assert subprocess.run(verification, capture_output=True).returncode != 0
    assert not (output / "ca.key").exists()
    before = (output / "server.key").read_bytes()
    with pytest.raises(ValueError, match="must be empty"):
        prepare(output, "router.test", "10.20.0.1", shutil.which("openssl"))
    assert (output / "server.key").read_bytes() == before


@pytest.mark.parametrize("address", ["8.8.8.8", "127.0.0.1", "0.0.0.0", "169.254.1.1", "240.0.0.1", "::1"])
def test_profile_rejects_non_lan_addresses(tmp_path, address):
    with pytest.raises(ValueError):
        prepare(tmp_path / "invalid", "router.test", address, shutil.which("openssl"))
    assert not (tmp_path / "invalid").exists()


def test_archives_exclude_retained_private_documents_and_keys(tmp_path, monkeypatch):
    import zipfile
    monkeypatch.setattr(package_prototype, "ROOT", tmp_path)
    monkeypatch.setattr(package_prototype, "OUT", tmp_path)
    paths = []
    for filename in ["technical-specification.ru.md", "environment.ru.md", "server.key", "ca.pem", ".env", "README.md", "credentials.json", "ha-connection.json",
                     "rpcd.fragment", "uhttpd.fragment", "controller.json", "config.local.json"]:
        path = tmp_path / filename
        path.write_text("private" if filename != "README.md" else "public")
        paths.append(path)
    target = package_prototype.archive("test.zip", paths)
    with zipfile.ZipFile(target) as result:
        assert result.namelist() == ["README.md"]
        assert result.read("README.md") == b"public"
