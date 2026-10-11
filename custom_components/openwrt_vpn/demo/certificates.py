"""Create an isolated localhost CA, server certificate and random lab credentials."""
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def create_lab(folder, include_ip=True):
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    if all((folder / name).exists() for name in ("credentials.json", "ca.pem", "server.pem", "server.key")):
        try:
            cert = x509.load_pem_x509_certificate((folder / "server.pem").read_bytes())
            if cert.not_valid_after_utc > now + timedelta(days=1):
                return
        except ValueError:
            pass
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OpenWrt VPN local lab CA")])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
          .not_valid_after(now + timedelta(days=30))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
          .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
              key_encipherment=False, data_encipherment=False, key_agreement=False,
              key_cert_sign=True, crl_sign=True, encipher_only=None, decipher_only=None), critical=True)
          .sign(ca_key, hashes.SHA256()))
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server = (x509.CertificateBuilder()
              .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
              .issuer_name(name).public_key(server_key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
              .not_valid_after(now + timedelta(days=14))
              .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
              .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
              .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                  key_encipherment=True, data_encipherment=False, key_agreement=False,
                  key_cert_sign=False, crl_sign=False, encipher_only=None, decipher_only=None), critical=True)
              .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")] +
                  ([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))] if include_ip else [])), critical=False)
              .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
              .sign(ca_key, hashes.SHA256()))
    # No CA private key is saved. These certificates are exclusively for this local test.
    for filename, content in {
        "ca.pem": ca.public_bytes(serialization.Encoding.PEM),
        "server.pem": server.public_bytes(serialization.Encoding.PEM),
        "server.key": server_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        "credentials.json": json.dumps({"username": "hass", "password": secrets.token_urlsafe(24),
                                       "lab_token": secrets.token_urlsafe(24)}).encode(),
    }.items():
        target = folder / filename
        target.write_bytes(content)
        if os.name != "nt":
            target.chmod(0o600)
