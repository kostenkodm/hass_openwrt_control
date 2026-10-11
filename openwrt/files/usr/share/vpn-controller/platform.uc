// SPDX-License-Identifier: MIT
import * as fs from 'fs';
import { cursor } from 'uci';
import { check, copy, ident } from './core.uc';

export function platform(config, bus) {
    // Paths and resources come only from a root-owned local file, never RPC.
    let base = '/etc/vpn-controller', volatile = '/var/run/vpn-controller';
    let helper = '/usr/libexec/vpn-controller-io';
    let confdir = '/etc/config', txn = base + '/transaction';
    for (let dir in [base,volatile,txn]) { fs.mkdir(dir,0700); fs.chmod(dir,0700); }
    const run = (argv, timeout) => {
        timeout ||= 10000;
        let out = volatile + '/command.out';
        let rc = system([helper,'run',''+timeout,out,...argv],timeout + 2000);
        let text = fs.readfile(out) || ''; fs.unlink(out);
        return {rc, text};
    };
    const sync = path => check(system([helper,'sync',path]) == 0,'storage_error');
    const write = (path, text) => {
        check(fs.writefile(path,text) != null,'storage_error'); fs.chmod(path,0600); sync(path);
    };
    function save(state) {
        let path = base + '/state.json', text = sprintf('%J',state);
        if (fs.readfile(path) == text) return;
        write(path + '.next', text); check(fs.rename(path + '.next',path),'storage_error'); sync(base);
    }
    const uci = (directory) => cursor(directory || confdir,volatile + '/delta','');
    const load = directory => {
        let c = uci(directory); check(c.load('podkop'),'uci_error'); return c;
    };
    const protected_names = config.protected_interfaces || [];
    const source_names = config.source_interfaces || [];
    function protected_name(name) {
        return name in protected_names || name in source_names || name in ['lan','wan','wan6','loopback'];
    }
    function local_policy(vpn) {
        let item = config.vpns?.[vpn];
        return item && item.approved == true && ident(vpn) && !protected_name(vpn) ? item : null;
    }
    function discover() {
        let c = load(), n = uci(), sections = {}, vpns = {};
        n.foreach('network','interface', item => {
            let name = item['.name'];
            if (!ident(name) || protected_name(name) || !(item.proto in ['wireguard','amneziawg'])) return;
            let status = bus.call('network.interface.' + name,'status',{}) || {};
            let policy = local_policy(name);
            vpns[name] = {id:name,name,protocol:item.proto,approved:policy != null,
                device:status.l3_device || status.device, up:status.up == true,
                restart_allowed:policy != null && config.restart_enabled == true &&
                    name in (config.restartable_interfaces || [])};
        });
        c.foreach('podkop','section',item => {
            let sid = item['.name'];
            if (item.connection_type != 'vpn' || !ident(sid) || protected_name(item.interface)) return;
            sections[sid] = {id:sid,name:item.name || sid,connection_type:'vpn',applied_vpn:item.interface};
        });
        return {sections,vpns};
    }
    function resources(sid) {
        return config.sections?.[sid]?.resources || config.resources || [];
    }
    function validate_resources(list) {
        check(type(list) == 'array' && length(list) >= 3 && length(list) <= 8,'local_config_error');
        let hosts = {};
        for (let r in list) {
            // Resolve locally with fixed --resolve addresses. No DNS leak,
            // redirect, userinfo, proxy environment, insecure TLS or RPC URL.
            check(type(r.host) == 'string' && match(r.host,/^[a-zA-Z0-9.-]+$/),'local_config_error');
            check(type(r.ip) == 'string' && match(r.ip,/^\d{1,3}(\.\d{1,3}){3}$/),'local_config_error');
            let octets = split(r.ip,'.'); for (let part in octets) check(+part <= 255,'local_config_error');
            check(!(+octets[0] in [0,10,127,169,172,192,224,255]),'local_config_error');
            check(type(r.path) == 'string' && match(r.path,/^\/[A-Za-z0-9_.\/?=&%-]*$/),'local_config_error');
            check(r.scheme in ['http','https'] && r.port in [80,443],'local_config_error');
            check(!r.egress || r.scheme == 'https','local_config_error');
            hosts[r.host] = true;
        }
        check(length(keys(hosts)) >= 3,'local_config_error');
    }
    function request(resource, binding, expected) {
        let body = volatile + '/probe.body'; fs.unlink(body);
        let args = ['/usr/bin/curl','--disable','--silent','--show-error','--fail','--ipv4',
            '--noproxy','*','--proto','=http,https','--max-time','4','--connect-timeout','2',
            '--max-filesize','4096','--output',body,'--write-out','%{http_code} %{time_total}',
            '--resolve',resource.host + ':' + resource.port + ':' + resource.ip];
        if (binding.device) push(args,'--interface','if!' + binding.device);
        else push(args,'--proxy','socks5://127.0.0.1:' + binding.port,'--noproxy','');
        if (resource.scheme == 'https') push(args,'--proto','=https');
        push(args,resource.scheme + '://' + resource.host + ':' + resource.port + resource.path);
        let response = run(args,5000), content = trim(fs.readfile(body) || ''); fs.unlink(body);
        let metrics = match(trim(response.text),/([0-9]{3}) ([0-9.]+)$/);
        let ok = response.rc == 0 && metrics && +metrics[1] >= 200 && +metrics[1] < 300;
        let ip = resource.egress == true && ok && content in expected ? content : null;
        return {ok, ip, latency_ms:ok ? +metrics[2] * 1000 : null};
    }
    function probe(vpns, sections, settings) {
        let samples = {};
        for (let vpn, meta in vpns) {
            if (!meta.approved) continue;
            let policy = local_policy(vpn), checks = {}, sum = 0, count = 0, external_ip = null, section_checks = {};
            let lists = {global:config.resources}, responses = {};
            for (let sid, s in sections) lists[sid] = resources(sid);
            for (let sid, list in lists) {
                validate_resources(list); let pass = 0, ip = null;
                for (let i = 0; i < length(list); i++) {
                    let key = sprintf('%J',list[i]);
                    if (!exists(responses,key)) responses[key] = meta.up && meta.device == vpn ?
                        request(list[i],{device:meta.device},policy.egress_ips) : {ok:false};
                    let result = responses[key];
                    if (sid == 'global') {
                        checks['resource_' + i] = result.ok;
                        if (result.ok) { sum += result.latency_ms; count++; }
                        if (result.ip) external_ip = result.ip;
                    }
                    if (result.ok) pass++;
                    if (result.ip) ip = result.ip;
                }
                if (sid != 'global') section_checks[sid] = pass >= (settings?.quorum || 2) && ip != null;
            }
            samples[vpn] = {checks,egress:external_ip != null,external_ip,
                latency_ms:count ? sum/count : null, section_checks,
                rx_bytes:fs.readfile('/sys/class/net/' + vpn + '/statistics/rx_bytes') ?
                    +fs.readfile('/sys/class/net/' + vpn + '/statistics/rx_bytes') : null,
                tx_bytes:fs.readfile('/sys/class/net/' + vpn + '/statistics/tx_bytes') ?
                    +fs.readfile('/sys/class/net/' + vpn + '/statistics/tx_bytes') : null,
                last_handshake:null};
        }
        return samples;
    }
    function version_ok() {
        let hashes = json(fs.readfile('/usr/share/vpn-controller/podkop-hashes.json') || '{}');
        if (!length(keys(hashes))) return false;
        for (let path, expected in hashes) {
            let result = run(['/usr/bin/sha256sum','/' + path]);
            if (result.rc || substr(result.text,0,64) != expected) return false;
        }
        let v = run(['/usr/bin/podkop','show_version']);
        return v.rc == 0 && trim(v.text) == '0.7.23';
    }
    function guard() {
        // No network/firewall mutation. Require existing interception intact.
        if (trim(fs.readfile('/proc/sys/net/ipv6/conf/all/disable_ipv6') || '') != '1') return false;
        if (trim(fs.readfile('/proc/sys/net/ipv6/conf/default/disable_ipv6') || '') != '1') return false;
        let nft = run(['/usr/sbin/nft','-j','list','table','inet','PodkopTable']);
        let rules = run(['/sbin/ip','-j','-4','rule','show']);
        let routes = run(['/sbin/ip','-j','-4','route','show','table','podkop']);
        if (nft.rc || rules.rc || routes.rc) return false;
        // Require concrete TPROXY target and source set, not merely table name.
        let table; try { table = json(nft.text); } catch(e) { return false; }
        let tproxy = false, sources = false, mangle = false, proxy = false, mark = false;
        for (let entry in table.nftables) {
            if (entry.chain?.name == 'mangle' && entry.chain.hook == 'prerouting' && entry.chain.prio == -150) mangle = true;
            if (entry.chain?.name == 'proxy' && entry.chain.hook == 'prerouting' && entry.chain.prio == -100) proxy = true;
            for (let expr in entry.rule?.expr || [])
                if (expr.mangle?.key?.meta?.key == 'mark' && expr.mangle.value in [1048576,'0x100000']) mark = true;
            if (entry.set?.name == 'interfaces') {
                let elem = entry.set.elem || [];
                sources = length(source_names) > 0 && !length(filter(source_names,n => !(n in elem)));
            }
            for (let expr in entry.rule?.expr || [])
                if (expr.tproxy?.port == 1602 && expr.tproxy?.addr == '127.0.0.1') tproxy = true;
        }
        let policy, route;
        try { policy=json(rules.text); route=json(routes.text); } catch(e) { return false; }
        return tproxy && sources && mangle && proxy && mark &&
            length(filter(policy,r => r.priority == 105 && (r.table == 'podkop' || r.table == 105) &&
                (r.fwmark == '0x100000' || r.fwmark == 1048576))) > 0 &&
            length(filter(route,r => r.type == 'local' && r.dev == 'lo' && r.dst == 'default')) > 0;
    }
    function ready() {
        return type(protected_names) == 'array' && length(protected_names) > 0 &&
            !length(filter(protected_names,n => !ident(n))) &&
            type(source_names) == 'array' && length(source_names) > 0 &&
            !length(filter(source_names,n => !ident(n))) &&
            config.control_enabled == true && config.exclusive_podkop_writer == true &&
            config.lab_acceptance == 'podkop-0.7.23-ipv4' && version_ok() && guard();
    }
    function stage(targets, directory) {
        fs.mkdir(directory,0700); fs.mkdir(directory + '/delta',0700);
        write(directory + '/podkop',fs.readfile(confdir + '/podkop'));
        let c = cursor(directory,directory + '/delta',''); check(c.load('podkop'),'uci_error');
        for (let sid, vpn in targets) {
            check(ident(sid) && ident(vpn) && local_policy(vpn),'invalid_argument');
            check(c.get('podkop',sid,'connection_type') == 'vpn','conflict');
            check(c.set('podkop',sid,'interface',vpn),'uci_error');
        }
        check(c.commit('podkop'),'uci_error'); sync(directory + '/podkop');
    }
    function runtime_path() {
        let path = load().get('podkop','settings','config_path');
        check(type(path) == 'string' && match(path,/^\/etc\/sing-box\/[A-Za-z0-9_.-]+\.json$/),'unsupported_config_path');
        return path;
    }
    function projection(data) {
        let result = copy(data);
        result.inbounds = filter(result.inbounds,i => !match(i.tag || '',/^vpn-controller-/));
        result.route.rules = filter(result.route.rules,r =>
            !length(filter(type(r.inbound) == 'array' ? r.inbound : [r.inbound || ''],i => match(i,/^vpn-controller-/))));
        for (let out in result.outbounds)
            if (match(out.tag || '',/-out$/) && out.type == 'direct' && out.bind_interface)
                out.bind_interface = '<vpn-binding>';
        return result;
    }
    function equal(a,b) {
        if (type(a) != type(b)) return false;
        if (type(a) == 'array') {
            if (length(a) != length(b)) return false;
            for (let i=0;i<length(a);i++) if (!equal(a[i],b[i])) return false;
            return true;
        }
        if (type(a) == 'object') {
            if (length(keys(a)) != length(keys(b))) return false;
            for (let k,v in a) if (!exists(b,k) || !equal(v,b[k])) return false;
            return true;
        }
        return a == b;
    }
    function render(targets, directory, current) {
        let info = discover(), ports = {}, rows = '', port = 23000;
        for (let sid in sort(keys(info.sections))) { ports[sid] = port++; rows += sid + ' ' + ports[sid] + '\n'; }
        write(directory + '/probes',rows);
        let result = run(['/usr/libexec/vpn-controller-podkop-render',directory,
            directory + '/render.json',directory + '/probes'],90000);
        check(result.rc == 0,'render_error');
        let before = json(fs.readfile(current)), after = json(fs.readfile(directory + '/render.json'));
        check(equal(projection(before),projection(after)),'runtime_config_conflict');
        // Projection permits binding comparisons, so validate EVERY binding,
        // including unmanaged outbounds, explicitly against the current config.
        for (let old in before.outbounds) {
            let matches = filter(after.outbounds,o => o.tag == old.tag);
            check(length(matches) == 1,'render_error');
            let sid = replace(old.tag || '',/-out$/,'');
            check(matches[0].bind_interface == (targets[sid] || old.bind_interface),'render_error');
        }
        check(run(['/usr/bin/sing-box','check','-c',directory + '/render.json'],15000).rc == 0,'render_error');
        return ports;
    }
    function verify(targets, ports, path) {
        if (!guard()) return false;
        let running = bus.call('service','list',{name:'sing-box'})?.['sing-box']?.instances;
        if (!running || !length(filter(values(running),i => i.running == true && path in (i.command || [])))) return false;
        let actual = json(fs.readfile(path));
        for (let sid,vpn in targets) {
            if (load().get('podkop',sid,'interface') != vpn) return false;
            let outbound = filter(actual.outbounds,o => o.tag == sid + '-out');
            if (length(outbound) != 1 || outbound[0].bind_interface != vpn) return false;
            let pass=0, ip=null;
            for (let r in resources(sid)) {
                let result = request(r,{port:ports[sid]},local_policy(vpn).egress_ips);
                if (result.ok) pass++; if (result.ip) ip=result.ip;
            }
            let quorum = json(fs.readfile(base + '/state.json') || '{}').settings?.quorum || 2;
            if (pass < quorum || !ip) return false;
        }
        return true;
    }
    function replace_file(path, expected, next) {
        // next MUST be on the same filesystem as path.
        write(path + '.vpn-controller-next',fs.readfile(next));
        let rc = system([helper,'replace',path,expected,path + '.vpn-controller-next']);
        fs.unlink(path + '.vpn-controller-next'); check(rc == 0,rc == 3 ? 'conflict' : 'storage_error');
    }
    function protected_copy() {
        let files = {};
        for (let name in ['network','firewall','dhcp']) files[name] = fs.readfile(confdir + '/' + name);
        return files;
    }
    function protected_equal(files) {
        for (let name,text in files) if (fs.readfile(confdir + '/' + name) != text) return false;
        return true;
    }
    function rollback(journal) {
        try {
            let saved = json(fs.readfile(txn + '/metadata.json'));
            if (saved.request_id != journal.request_id || !protected_equal(saved.protected)) return 'recovery_required';
            let c = load(), targets = {}, any = false;
            for (let sid,old in journal.before) {
                let actual = c.get('podkop',sid,'interface');
                if (actual != old && actual != journal.targets[sid]) return 'recovery_required';
                if (c.get('podkop',sid,'connection_type') != 'vpn') return 'recovery_required';
                targets[sid] = old; if (actual != old) any = true;
            }
            let path = saved.runtime_path, current = fs.readfile(path);
            if (current != fs.readfile(txn + '/runtime.before') && current != fs.readfile(txn + '/render.json'))
                return 'recovery_required';
            if (any) {
                // Preserve unrelated LuCI fields. Never restore the full old UCI.
                write(txn + '/rollback.expected',fs.readfile(confdir + '/podkop'));
                stage(targets,txn + '/rollback');
                replace_file(confdir + '/podkop',txn + '/rollback.expected',txn + '/rollback/podkop');
            }
            if (current != fs.readfile(txn + '/runtime.before')) {
                replace_file(path,txn + '/render.json',txn + '/runtime.before');
                check(run(['/etc/init.d/sing-box','reload'],15000).rc == 0,'rollback_error');
            }
            let ports = {}, original = json(fs.readfile(path));
            for (let sid,old in journal.before) {
                let inbound = filter(original.inbounds,i => i.tag == 'vpn-controller-' + sid && i.listen == '127.0.0.1');
                if (length(inbound) != 1) return 'recovery_required';
                ports[sid] = inbound[0].listen_port;
            }
            if (!verify(journal.before,ports,path)) return 'recovery_required';
            return 'rolled_back';
        } catch(e) { return 'recovery_required'; }
    }
    function apply(targets, journal) {
        try {
            check(ready(),'control_disabled');
            write(txn + '/podkop.before',fs.readfile(confdir + '/podkop'));
            let path = runtime_path(), protected = protected_copy();
            write(txn + '/runtime.before',fs.readfile(path));
            write(txn + '/metadata.json',sprintf('%J',{request_id:journal.request_id,runtime_path:path,protected}));
            stage(targets,txn + '/staged');
            let ports = render(targets,txn + '/staged',path);
            write(txn + '/render.json',fs.readfile(txn + '/staged/render.json'));
            check(protected_equal(protected) && guard(),'conflict');
            replace_file(confdir + '/podkop',txn + '/podkop.before',txn + '/staged/podkop');
            check(protected_equal(protected),'conflict');
            replace_file(path,txn + '/runtime.before',txn + '/render.json');
            check(run(['/etc/init.d/sing-box','reload'],15000).rc == 0,'apply_error');
            check(verify(targets,ports,path),'verify_error');
            check(fs.readfile(confdir + '/podkop') == fs.readfile(txn + '/staged/podkop'),'conflict');
            check(protected_equal(protected),'conflict');
            return 'completed';
        } catch(e) { fs.writefile(txn + '/last-error.txt', '' + e); return rollback(journal); }
    }
    function restart_allowed(vpn) {
        let meta = discover().vpns[vpn];
        return ident(vpn) && !protected_name(vpn) && config.restart_enabled == true &&
            vpn in (config.restartable_interfaces || []) && meta?.approved == true &&
            (meta.device == vpn || (!meta.up && !meta.device));
    }
    function wait_up(vpn, verify_egress) {
        for (let i=0; i<20; i++) {
            let meta = discover().vpns[vpn];
            if (meta?.up == true && meta.device == vpn) {
                if (!verify_egress) return true;
                let sample = probe({[vpn]:meta},{},{quorum:2})[vpn];
                let quorum = json(fs.readfile(base + '/state.json') || '{}').settings?.quorum || 2;
                return sample.egress && length(filter(values(sample.checks),ok => ok)) >= quorum;
            }
            system(['/bin/sleep','1']);
        }
        return false;
    }
    function recover(journal) {
        if (journal.kind != 'restart_vpn') return rollback(journal);
        // Never replay down after a lost response or a crash.
        if (!restart_allowed(journal.vpn)) return 'recovery_required';
        try {
            bus.call('network.interface.' + journal.vpn,'up',{});
            return wait_up(journal.vpn,false) ? 'interrupted' : 'recovery_required';
        } catch(e) { return 'recovery_required'; }
    }
    function restart(vpn) {
        let files = protected_copy(), podkop = fs.readfile(confdir + '/podkop');
        try {
            check(ready() && restart_allowed(vpn),'restart_forbidden');
            // Root-local allowlist checked immediately before each narrow netifd call.
            check(bus.call('network.interface.' + vpn,'down',{}) != null,'restart_failed');
            check(restart_allowed(vpn),'restart_forbidden');
            check(bus.call('network.interface.' + vpn,'up',{}) != null,'restart_failed');
            check(wait_up(vpn,true),'restart_failed');
            check(protected_equal(files) && fs.readfile(confdir + '/podkop') == podkop && guard(),'conflict');
            return 'completed';
        } catch(e) {
            try {
                if (restart_allowed(vpn)) bus.call('network.interface.' + vpn,'up',{});
                else return 'recovery_required';
            } catch(ignored) { return 'recovery_required'; }
            return wait_up(vpn,false) && protected_equal(files) &&
                fs.readfile(confdir + '/podkop') == podkop ? 'restart_failed' : 'recovery_required';
        }
    }
    let boot_id = trim(fs.readfile('/proc/sys/kernel/random/boot_id') || 'unknown');
    return {save,discover,probe,apply,recover,restart,ready,boot_id,
        uuid:() => trim(fs.readfile('/proc/sys/kernel/random/uuid')),
        now:() => +split(fs.readfile('/proc/uptime'),' ')[0],
        date:() => trim(run(['/bin/date','-u','+%Y-%m-%dT%H:%M:%SZ']).text),
        service_status:() => ({podkop_status:guard() ? 'active' : 'unverified',
            sing_box_status:bus.call('service','list',{name:'sing-box'})?.['sing-box'] ? 'running' : 'unknown'}),
        capabilities:() => ({experimental:true, protected_interfaces:protected_names,
            vpn_restart:config.restart_enabled == true && ready(), last_handshake:false, control_disabled_reason:
            config.control_enabled ? 'local_preflight_required' : 'disabled_in_local_config',
            supported_podkop:'0.7.23', ipv4_only:true})};
};
