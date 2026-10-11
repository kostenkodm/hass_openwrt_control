#!/bin/bash
# Small package build using the official SDK compiler and apk-tools.
# This path also works on DrvFS; the full SDK make requires a case-sensitive FS.
set -euo pipefail
cd "$(dirname "$0")/.."
sdk="${OPENWRT_SDK:-$PWD/work/openwrt-sdk}"
name=hass-openwrt-vpn-controller
version=0.2.2-r1
arch=aarch64_cortex-a53
out="$PWD/outputs/podkop-0.2.2"
apk="$sdk/staging_dir/host/bin/apk"
if [ "${1:-}" = --pack-root ]; then
    stage="$2"
    find "$stage" -type d -exec chmod 0755 {} +
    find "$stage" -type f -exec chmod 0644 {} +
    chmod 0700 "$stage/etc/vpn-controller"
    chmod 0600 "$stage/etc/vpn-controller/config.json"
    chmod 0755 "$stage/usr/sbin/vpn-controller.uc" "$stage/usr/libexec/"* \
        "$stage/usr/share/vpn-controller/vpn-controller.init"
    chown -R 0:0 "$stage"
    "$apk" mkpkg --info "name:$name" --info "version:$version" --info "arch:$arch" \
        --info 'license:MIT' --info "origin:$name" \
        --info 'url:https://github.com/kostenkodm/hass_openwrt_control' \
        --info 'description:Experimental autonomous Podkop controller with limited ubus API' \
        --info 'depends:libc ucode ucode-mod-fs ucode-mod-uci ucode-mod-ubus ucode-mod-uloop rpcd curl ca-bundle jq sing-box podkop ip-full nftables-json uhttpd uhttpd-mod-ubus libustream-mbedtls' \
        --files "$stage" --output "$out/${name}-${version}.${arch}.apk"
    exit
fi
compiler="$sdk/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.3.0_musl/bin/aarch64-openwrt-linux-musl-gcc"
[ -x "$compiler" ] && [ -x "$apk" ] || { echo 'Prepare the pinned OpenWrt 25.12.5 SDK first'; exit 1; }
archive=work/native-downloads/openwrt-sdk-25.12.5-mediatek-mt7622_gcc-14.3.0_musl.Linux-x86_64.tar.zst
printf '%s  %s\n' 0bd25a391256dbe9ad1f9c6f313364b1f9eddcc0e280c829d644034981ad8306 "$archive" | sha256sum -c -
mkdir -p "$out"
stage="$(mktemp -d "$PWD/work/package-root-XXXXXX")"
cp -a openwrt/files/. "$stage/"
mkdir -p "$stage/usr/share/rpcd/acl.d" "$stage/usr/share/licenses/$name" "$stage/lib/apk/packages"
cp openwrt/rpcd-acl/hass-openwrt-vpn.json "$stage/usr/share/rpcd/acl.d/"
cp openwrt/podkop-hashes.json "$stage/usr/share/vpn-controller/podkop-hashes.json"
cp LICENSE "$stage/usr/share/licenses/$name/LICENSE"
export STAGING_DIR="$sdk/staging_dir"
"$compiler" -Os -fPIE -pie -fstack-protector-strong -D_FORTIFY_SOURCE=2 -Wall -Wextra -Werror \
    -Wl,-z,relro,-z,now openwrt/src/io.c -o "$stage/usr/libexec/vpn-controller-io"
"${compiler%gcc}strip" "$stage/usr/libexec/vpn-controller-io"
printf '/etc/vpn-controller/config.json\n' > "$stage/lib/apk/packages/$name.conffiles"
printf '/etc/vpn-controller/config.json %s\n' "$(sha256sum "$stage/etc/vpn-controller/config.json" | cut -d ' ' -f1)" \
    > "$stage/lib/apk/packages/$name.conffiles_static"
(cd "$stage" && find . -type f -printf '/%P\n' | sort) > "$stage/lib/apk/packages/$name.list"
"$sdk/staging_dir/host/bin/fakeroot" -l "$sdk/staging_dir/host/lib/libfakeroot-0.so" -f "$sdk/staging_dir/host/bin/faked" -- bash "$PWD/tools/build_openwrt_package.sh" --pack-root "$stage"
"$apk" adbdump --allow-untrusted "$out/${name}-${version}.${arch}.apk" > "$out/APK-METADATA.txt"
"${compiler%gcc}readelf" -h -l "$stage/usr/libexec/vpn-controller-io" > "$out/ELF-INFO.txt"
echo 'Built unsigned ARM64 prototype APK; nothing installed or enabled.'
