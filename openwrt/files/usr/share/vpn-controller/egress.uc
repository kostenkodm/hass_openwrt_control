// SPDX-License-Identifier: MIT
// Only public IPv4 and agreement between distinct HTTPS echo hosts.
export function public_ipv4(value) {
    if (type(value) != 'string' || !match(value,/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/)) return false;
    let p = split(value,'.');
    for (let n in p) if (+n > 255 || (length(n) > 1 && substr(n,0,1) == '0')) return false;
    let a=+p[0], b=+p[1], c=+p[2];
    if (a == 0 || a == 10 || a == 127 || a >= 224) return false;
    if (a == 100 && b >= 64 && b <= 127) return false;
    if (a == 169 && b == 254 || a == 172 && b >= 16 && b <= 31) return false;
    if (a == 192 && (b == 168 || b == 0 && c in [0,2] || b == 88 && c == 99)) return false;
    if (a == 198 && (b in [18,19] || b == 51 && c == 100)) return false;
    if (a == 203 && b == 0 && c == 113) return false;
    return true;
};
export function agreed_ip(results, dynamic) {
    let ip = null, hosts = {};
    for (let r in results) {
        if (!r.ip) continue;
        if (!dynamic) return r.ip;
        if (!public_ipv4(r.ip)) return null;
        if (ip != null && ip != r.ip) return null;
        ip = r.ip; hosts[lc(r.host)] = true;
    }
    return length(keys(hosts)) >= 2 ? ip : null;
};
