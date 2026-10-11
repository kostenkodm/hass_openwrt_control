#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
root="$PWD/work/native-rootfs"
mkdir -p "$root"
if [ ! -f "$root/bin/busybox" ]; then
    [ -z "$(find "$root" -mindepth 1 -maxdepth 1 -print -quit)" ] || { echo 'Existing lab rootfs is incomplete'; exit 1; }
    tar -xzf work/native-downloads/rootfs.tar.gz -C "$root"
fi
/usr/bin/python3 openwrt/tests/confine_rootfs.py
mkdir -p "$root/etc/vpn-controller" "$root/usr/share/vpn-controller" "$root/usr/libexec" "$root/usr/lib/podkop" "$root/etc/sing-box" "$root/tmp/sing-box/rulesets" "$root/var/run/vpn-controller"
cp -a openwrt/files/. "$root/"
cp openwrt/podkop-0.7.23.sha256.json "$root/usr/share/vpn-controller/podkop-hashes.json"
cp work/references/podkop-0.7.23/podkop/files/usr/bin/podkop "$root/usr/bin/podkop"
cp work/references/podkop-0.7.23/podkop/files/usr/lib/* "$root/usr/lib/podkop/"
sed -i 's/__COMPILED_VERSION_VARIABLE__/0.7.23/' "$root/usr/lib/podkop/constants.sh"
tar -xzf work/native-downloads/sing-box.tar.gz -C work/native-downloads
cp work/native-downloads/sing-box-1.12.17-linux-amd64/sing-box "$root/usr/bin/sing-box"
gcc -static -O2 -Wall -Wextra -Werror openwrt/src/io.c -o "$root/usr/libexec/vpn-controller-io"
# jq and its glibc dependencies are local lab tools only.
copy_binary() {
    cp "$1" "$root$1"
    ldd "$1" | awk '/=> \// {print $3} /^\s*\// {print $1}' | while read -r lib; do
        mkdir -p "$root$(dirname "$lib")"; cp -L "$lib" "$root$lib"
    done
}
copy_binary /usr/bin/jq
copy_binary /usr/bin/curl
copy_binary /usr/sbin/ip
# OpenWrt /sbin/ip initially links to busybox. Never copy through that symlink.
if [ -L "$root/sbin/ip" ]; then unlink "$root/sbin/ip"; fi
cp "$root/usr/sbin/ip" "$root/sbin/ip"
mkdir -p "$root/lib64"; cp -L /lib64/ld-linux-x86-64.so.2 "$root/lib64/"
chmod +x "$root/usr/bin/podkop" "$root/usr/libexec/"* "$root/usr/sbin/vpn-controller.uc"
chroot "$root" /bin/sh -c 'sing-box version | head -n1; jq --version'

mkdir -p work/native-tls
openssl req -x509 -newkey rsa:2048 -nodes -keyout work/native-tls/server.key -out work/native-tls/server.pem -days 2 -subj /CN=localhost -addext subjectAltName=DNS:localhost,DNS:alpha.test,DNS:beta.test,DNS:gamma.test,IP:127.0.0.1,IP:203.0.113.10 > work/native-cert.log 2>&1
chmod 0600 work/native-tls/server.key
/usr/bin/python3 openwrt/tests/setup_rootfs.py
chmod +x "$root/etc/init.d/sing-box"
# Compile with the official rootfs interpreter as well as the newer unit runtime.
chroot "$root" /usr/bin/ucode -c -o /tmp/controller.uc /usr/sbin/vpn-controller.uc
