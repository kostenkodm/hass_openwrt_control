#!/bin/bash
# Only inside unshare --mount --net. No production network is used.
set -euo pipefail
cd "$(dirname "$0")/../.."
root="$PWD/work/native-rootfs"
mount --make-rprivate /
mount -t proc proc "$root/proc"
mount --bind /dev "$root/dev"
mount -t tmpfs tmpfs "$root/tmp"
mkdir -p "$root/tmp/initial" "$root/tmp/sing-box/rulesets" "$root/tmp/empty"
cp "$root/etc/config/podkop" "$root/tmp/initial/podkop"
: > "$root/tmp/initial/probes"
mkdir -p "$root/tmp/run/ubus" "$root/tmp/state" "$root/tmp/sing-box/rulesets" "$root/tmp/empty"
ip link set lo up
sysctl -qw net.ipv6.conf.all.disable_ipv6=1
sysctl -qw net.ipv6.conf.default.disable_ipv6=1
sysctl -qw net.ipv4.ip_forward=1
unshare -n sleep infinity & endpoint=$!
cleanup() {
  if [ -s "$root/tmp/sing-box.pid" ]; then
    test_pid="$(cat "$root/tmp/sing-box.pid")"
    if [ "$(readlink -f "/proc/$test_pid/root" 2>/dev/null || true)" = "$root" ]; then
      kill "$test_pid" 2>/dev/null || true
    fi
  fi
  kill $(jobs -pr) 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT
sleep .1
nsenter -t "$endpoint" -n ip link set lo up
nsenter -t "$endpoint" -n ip addr add 203.0.113.10/32 dev lo
idx=0
for vpn in vpn_a vpn_b vpn_c WAN; do
  ip link add "$vpn" type veth peer name "peer$idx"
  ip link set "peer$idx" netns "$endpoint"
  localip=$((idx*4+2)); peerip=$((idx*4+1))
  ip addr add "198.51.100.$localip/30" dev "$vpn"; ip link set "$vpn" up
  nsenter -t "$endpoint" -n ip addr add "198.51.100.$peerip/30" dev "peer$idx"
  nsenter -t "$endpoint" -n ip link set "peer$idx" up
  ip route add 203.0.113.10/32 via "198.51.100.$peerip" dev "$vpn" metric "$((10+idx))"
  idx=$((idx+1))
done
ip route add default via 198.51.100.13 dev WAN
ip link add inbound_vpn type dummy; ip link set inbound_vpn up
unshare -n sleep infinity & client=$!
sleep .1
ip link add br-lan type veth peer name client0
ip link set client0 netns "$client"
ip addr add 10.20.0.1/24 dev br-lan; ip link set br-lan up
nsenter -t "$client" -n ip link set lo up
nsenter -t "$client" -n ip addr add 10.20.0.2/24 dev client0
nsenter -t "$client" -n ip link set client0 up
nsenter -t "$client" -n ip route add default via 10.20.0.1
nsenter -t "$endpoint" -n ip route add 10.20.0.0/24 via 198.51.100.14 dev peer3
ip rule add fwmark 0x100000 table 105 priority 105
ip route add local default dev lo table 105
nft add table inet PodkopTable
nft 'add set inet PodkopTable interfaces { type ifname; elements = { "br-lan", "inbound_vpn" }; }'
nft 'add chain inet PodkopTable mangle { type filter hook prerouting priority -150; }'
nft 'add rule inet PodkopTable mangle iifname "br-lan" ip daddr 203.0.113.10 meta mark set 0x100000'
nft 'add chain inet PodkopTable leak { type filter hook forward priority 0; }'
nft 'add rule inet PodkopTable leak oifname "WAN" ip daddr 203.0.113.10 counter'
nft 'add chain inet PodkopTable proxy { type filter hook prerouting priority -100; }'
nft 'add rule inet PodkopTable proxy meta mark 0x100000 meta l4proto tcp tproxy ip to 127.0.0.1:1602'
nsenter -t "$endpoint" -n /usr/bin/python3 openwrt/tests/http_endpoint.py > work/native-http.log 2>&1 &
chroot "$root" /sbin/ubusd > work/native-ubusd.log 2>&1 &
sleep .2
chroot "$root" /sbin/rpcd > work/native-rpcd.log 2>&1 &
chroot "$root" /usr/bin/ucode /tests/fixture.uc > work/native-fixture.log 2>&1 &
sleep .3
chroot "$root" /usr/libexec/vpn-controller-podkop-render /tmp/initial /etc/sing-box/config.json /tmp/initial/probes > work/native-render.log 2>&1
chroot "$root" /usr/bin/sing-box check -c /etc/sing-box/config.json
chroot "$root" /etc/init.d/sing-box reload
chroot "$root" /usr/bin/ucode /tests/integration.uc
chroot "$root" /usr/bin/ucode /tests/dynamic_integration.uc

chroot "$root" /usr/bin/ucode /usr/sbin/vpn-controller.uc > work/native-daemon.log 2>&1 &
chroot "$root" /usr/sbin/uhttpd -f -s 127.0.0.1:18443 -C /etc/vpn-controller/tls/server.pem -K /etc/vpn-controller/tls/server.key -h /tmp/empty -u /ubus > work/native-uhttpd.log 2>&1 &
sleep 3
PYTHONPATH="$PWD" work/venv-linux/bin/python openwrt/tests/rpc_client.py
client_request() {
  nsenter -t "$client" -n curl --silent --fail --noproxy '*' --max-time 3 --cacert work/native-tls/server.pem --resolve alpha.test:443:203.0.113.10 https://alpha.test/ip
}
actual="$(client_request)"
[ "$actual" = '198.51.100.2' ]
echo 'PASS real Podkop section route from a separate LAN client'
kill "$(cat "$root/tmp/sing-box.pid")"
sleep .2
if client_request; then echo 'FAIL: request passed with sing-box stopped'; exit 1; fi
nft -j list chain inet PodkopTable leak > work/native-leak-counter.json
/usr/bin/python3 -c 'import json; d=json.load(open("work/native-leak-counter.json")); assert sum(e.get("counter",{}).get("packets",0) for r in d["nftables"] for e in r.get("rule",{}).get("expr",[])) == 0'
echo 'PASS stopped sing-box does not forward the tested IPv4 flow to WAN'
chroot "$root" /etc/init.d/sing-box reload
ip link set vpn_a down
if client_request; then echo 'FAIL: request passed with assigned VPN down'; exit 1; fi
nft -j list chain inet PodkopTable leak > work/native-leak-counter.json
/usr/bin/python3 -c 'import json; d=json.load(open("work/native-leak-counter.json")); assert sum(e.get("counter",{}).get("packets",0) for r in d["nftables"] for e in r.get("rule",{}).get("expr",[])) == 0'
echo 'PASS failed assigned VPN does not fall back to WAN'
# Positive control: demonstrate WAN is reachable and the leak counter works.
ip link set vpn_b down; ip link set vpn_c down
nft flush chain inet PodkopTable mangle
actual="$(client_request)"
[ "$actual" = '10.20.0.2' ]
echo 'PASS positive control detects a direct WAN route when interception is removed'
