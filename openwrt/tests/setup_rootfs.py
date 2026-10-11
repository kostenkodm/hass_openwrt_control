from pathlib import Path
import json
import shutil
import secrets
import subprocess
import os

root = Path("work/native-rootfs").resolve()
assert (root / "etc/ssl/cert.pem").resolve().is_relative_to(root), "Rootfs must be confined first"
for p in Path("openwrt/files").rglob("*"):
    if p.is_file():
        dest = root / p.relative_to("openwrt/files")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
(root / "tests").mkdir(exist_ok=True)
for p in Path("openwrt/tests").glob("*.uc"):
    shutil.copyfile(p, root / "tests" / p.name)
(root / "files/usr/share/vpn-controller").mkdir(parents=True, exist_ok=True)
for name in ["core.uc", "platform.uc", "egress.uc"]:
    shutil.copyfile(root / "usr/share/vpn-controller" / name, root / "files/usr/share/vpn-controller" / name)
initial = root / "tmp/initial"
initial.mkdir(exist_ok=True)
(initial / "probes").write_text("")
config = """config settings 'settings'
 option service_listen_address '127.0.0.1'
 option dns_type 'udp'
 option dns_server '203.0.113.10'
 option bootstrap_dns_server '203.0.113.10'
 option config_path '/etc/sing-box/config.json'
 option cache_path '/tmp/sing-box/cache.db'
 option log_level 'error'
 option enable_yacd '0'
 option disable_quic '0'
 option download_lists_via_proxy '0'
 list source_network_interfaces 'br-lan'
 list source_network_interfaces 'inbound_vpn'

"""
for sid in ["main", "media"]:
    config += f"""config section '{sid}'
 option connection_type 'vpn'
 option interface 'vpn_a'
 option domain_resolver_enabled '0'
 option user_domain_list_type 'disabled'
 option user_subnet_list_type 'disabled'
 option resolve_real_ip_for_routing '0'
 option mixed_proxy_enabled '0'
 list fully_routed_ips '10.20.0.2'

"""
(root / "etc/config/podkop").write_text(config)
(initial / "podkop").write_text(config)
(root / "etc/config/network").write_text(
    "\n".join(
        f"config interface '{v}'\n option proto 'amneziawg'\n"
        for v in ["vpn_a", "vpn_b", "vpn_c", "inbound_vpn"]
    )
)
resources = [
    {"host": h + ".test", "ip": "203.0.113.10", "scheme": "https", "port": 443, "path": "/ip", "egress": True}
    for h in ["alpha", "beta", "gamma"]
]
(root / "etc/vpn-controller/config.json").write_text(
    json.dumps(
        {
            "protected_interfaces": ["inbound_vpn"],
            "source_interfaces": ["br-lan", "inbound_vpn"],
            "restart_enabled": True,
            "restartable_interfaces": ["vpn_a"],
            "control_enabled": True,
            "exclusive_podkop_writer": True,
            "lab_acceptance": "podkop-" + os.environ.get("PODKOP_TEST_VERSION", "0.7.24") + "-ipv4",
            "resources": resources,
            "vpns": {
                v: {"approved": True, "egress_ips": [f"198.51.100.{2 + 4 * i}"]}
                for i, v in enumerate(["vpn_a", "vpn_b", "vpn_c"])
            },
        }
    )
)
(root / "etc/init.d/sing-box").write_text("""#!/bin/ash
if [ -s /tmp/sing-box.pid ]; then
 kill "$(cat /tmp/sing-box.pid)" 2>/dev/null || :
 sleep 1
fi
if [ -f /tmp/fault.verify ]; then
 rm /tmp/fault.verify
 /sbin/ip link set vpn_a down
fi
/usr/bin/sing-box run -c /etc/sing-box/config.json > /tmp/sing-box.log 2>&1 &
echo $! > /tmp/sing-box.pid
sleep 1
""")

(root / "etc/iproute2/rt_tables").write_text("255 local\n254 main\n253 default\n0 unspec\n105 podkop\n")

(root / "etc/ssl/certs").mkdir(exist_ok=True)
shutil.copyfile("work/native-tls/server.pem", root / "etc/ssl/certs/ca-certificates.crt")
# cert.pem is a confined relative symlink to this rootfs CA bundle.
(root / "etc/vpn-controller/tls").mkdir(exist_ok=True)
for name in ["server.pem", "server.key"]:
    shutil.copyfile("work/native-tls/" + name, root / "etc/vpn-controller/tls" / name)
(root / "usr/share/rpcd/acl.d").mkdir(parents=True, exist_ok=True)
shutil.copyfile("openwrt/rpcd-acl/hass-openwrt-vpn.json", root / "usr/share/rpcd/acl.d/hass-openwrt-vpn.json")
(root / "var/empty").mkdir(exist_ok=True)

password = secrets.token_urlsafe(32)
password_hash = subprocess.run(
    ["openssl", "passwd", "-6", "-stdin"], input=password + "\n", text=True, capture_output=True, check=True
).stdout.strip()
Path("work/native-tls/credentials.json").write_text(
    json.dumps({"username": "hass-vpn", "password": password})
)
(root / "etc/config/rpcd").write_text(
    "config rpcd\n option timeout '300'\n\nconfig login 'hass_vpn'\n option username 'hass-vpn'\n option password '"
    + password_hash
    + "'\n list read 'hass-openwrt-vpn'\n list write 'hass-openwrt-vpn'\n"
)

os.chmod("work/native-tls/credentials.json", 0o600)
os.chmod(root / "etc/vpn-controller/tls/server.key", 0o600)
