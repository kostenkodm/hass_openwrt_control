"""Prepare a dedicated RPC login and verified LAN HTTPS profile, without deploying."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import re
from pathlib import Path
import secrets
import shutil
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def prepare(folder: Path, hostname: str, address: str, openssl: str):
    ip = ipaddress.ip_address(address)
    if ip.version != 4 or not any(ip in ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")) or ip.is_loopback or ip.is_unspecified or ip.is_link_local:
        raise ValueError("Use the router's private LAN IPv4 address")
    if (not hostname or len(hostname) > 253
            or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                   for label in hostname.split("."))):
        raise ValueError("Invalid DNS name")
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("Output directory must be empty; credentials are never overwritten")
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    password = secrets.token_urlsafe(32)
    proc = subprocess.run([openssl, "passwd", "-6", "-stdin"], input=password + "\n",
                          text=True, capture_output=True, check=True)
    password_hash = proc.stdout.strip()
    if not password_hash.startswith("$6$"):
        raise ValueError("SHA-512 crypt password generation failed")
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OpenWrt VPN RPC private CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
              key_encipherment=False, data_encipherment=False, key_agreement=False,
              key_cert_sign=True, crl_sign=True, encipher_only=None, decipher_only=None), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname), x509.IPAddress(ip)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256()))
    payload = {
        "ca.pem": ca.public_bytes(serialization.Encoding.PEM),
        "server.pem": cert.public_bytes(serialization.Encoding.PEM),
        "server.key": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()),
        "ha-connection.json": json.dumps({"endpoint": f"https://{hostname}:8443/ubus", "username": "hass-vpn",
                                         "password": password}, indent=2).encode(),
        "rpcd.fragment": ("config login 'hass_vpn'\n option username 'hass-vpn'\n"
                          f" option password '{password_hash}'\n list read 'hass-openwrt-vpn'\n"
                          " list write 'hass-openwrt-vpn'\n").encode(),
        "uhttpd.fragment": ("config uhttpd 'vpn_controller'\n"
                            f" list listen_https '{address}:8443'\n"
                            " option home '/var/empty'\n option cert '/etc/vpn-controller/tls/server.pem'\n"
                            " option key '/etc/vpn-controller/tls/server.key'\n option ubus_prefix '/ubus'\n"
                            " option ubus_socket '/var/run/ubus/ubus.sock'\n option ubus_noauth '0'\n"
                            " option rfc1918_filter '1'\n option max_requests '4'\n"
                            " option max_connections '8'\n option script_timeout '30'\n"
                            " option network_timeout '30'\n").encode(),
    }
    for name, content in payload.items():
        target = folder / name
        target.write_bytes(content)
        target.chmod(0o600)
    # Do not save the CA private key or print credentials. Renewal of this
    # prototype profile generates a new CA; update the HA trust setting too.
    print(f"Prepared RPC and LAN HTTPS files in {folder}; no router was contacted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--lan-ip", required=True)
    parser.add_argument("--output", type=Path, default=Path("work/router-access"))
    parser.add_argument("--openssl", default=shutil.which("openssl"))
    args = parser.parse_args()
    if not args.openssl:
        parser.error("OpenSSL is required; pass --openssl with the executable path")
    prepare(args.output, args.hostname, args.lan_ip, args.openssl)


if __name__ == "__main__":
    main()
