#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(id -u)" = 0 ] || { echo 'Run this isolated lab as root in disposable Linux/WSL'; exit 1; }
host_ca_before="$(sha256sum /etc/ssl/certs/ca-certificates.crt)"
/usr/bin/python3 tools/fetch_native_dependencies.py
bash openwrt/tests/prepare_rootfs.sh
mkdir -p work
chroot "$PWD/work/native-rootfs" /usr/bin/ucode /tests/core.uc | tee work/native-core-tests.log
/usr/bin/python3 openwrt/tests/test_io.py | tee work/native-io-tests.log
unshare -m -n bash openwrt/tests/run_in_namespace.sh | tee work/native-integration-tests.log

[ "$host_ca_before" = "$(sha256sum /etc/ssl/certs/ca-certificates.crt)" ]
echo "PASS host CA store unchanged by rootfs preparation"
