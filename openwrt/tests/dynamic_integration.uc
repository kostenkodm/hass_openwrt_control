import * as fs from 'fs';
import {connect} from 'ubus';
import {platform} from '../usr/share/vpn-controller/platform.uc';
import {engine,check,copy} from '../usr/share/vpn-controller/core.uc';
const bus=connect(), config=json(fs.readfile('/etc/vpn-controller/config.json'));
for (let vpn,policy in config.vpns) { policy.egress_mode='dynamic'; delete policy.egress_ips; }
for (let r in config.resources) r.path='/dynamic-ip';
const p=platform(config,bus);
let before={}; for (let name in ['network','firewall','dhcp']) before[name]=fs.readfile('/etc/config/'+name);
function mode(m) { fs.writefile('/tmp/egress-mode.json',sprintf('%J',m)); }
function probe() { let d=p.discover(); return p.probe(d.vpns,d.sections,{quorum:2}); }
mode({}); let a=probe();
check(a.vpn_a.egress && a.vpn_a.external_ip=='93.184.216.2','dynamic_probe_failed');
mode({generation:1}); let b=probe();
check(b.vpn_a.egress && b.vpn_a.external_ip=='93.184.216.22','dynamic_change_rejected');
print('PASS dynamic HTTPS device-bound egress accepts an actual echo address change\n');
for (let fault in [{mismatch:true},{private:true},{malformed:true}]) {
    mode(fault); let s=probe();
    check(!s.vpn_a.egress && s.vpn_a.external_ip==null,'bad_dynamic_response_accepted');
}
print('PASS mismatched, private and malformed echo responses cannot verify egress\n');
mode({});
check(system(['/sbin/ip','link','set','vpn_c','down'])==0);
check(system(['/usr/bin/curl','--disable','--silent','--fail','--max-time','4','--noproxy','*',
    '--interface','if!WAN','--resolve','alpha.test:443:203.0.113.10','https://alpha.test/dynamic-ip'])==0,'wan_positive_control_failed');
let failed=probe(); check(!failed.vpn_c.egress && failed.vpn_c.external_ip==null,'vpn_fell_back_to_wan');
check(system(['/sbin/ip','link','set','vpn_c','up'])==0);
print('\nPASS dynamic device-bound probe fails with VPN down while WAN HTTPS works\n');
let c=engine(p,null); c.sample_all(); let seq=0;
function command(method,args) {
    return c.mutate(method,{...args,request_id:'dynamic-test-'+sprintf('%08d',seq++),expected_revision:c.state.revision});
}
command('configure',{run_mode:'control',probe_interval:60,failure_cycles:3,quorum:2,min_hold:600});
let result=command('assign_vpn',{section_id:'main',vpn:'vpn_a'});
check(result.status=='completed' && c.status().sections.main.applied_vpn=='vpn_a','dynamic_apply_failed');
mode({generation:1}); c.sample_all();
result=command('assign_vpn',{section_id:'main',vpn:'vpn_b'});
check(result.status=='completed' && c.status().sections.main.applied_vpn=='vpn_b','dynamic_reapply_failed');
print('PASS dynamic Podkop apply verifies section SOCKS route against fresh bound HTTPS probes\n');
fs.writefile('/tmp/fault.verify','1');
result=command('assign_vpn',{section_id:'main',vpn:'vpn_a'});
check(result.status=='rolled_back' && c.status().sections.main.applied_vpn=='vpn_b','dynamic_rollback_failed');
check(system(['/sbin/ip','link','set','vpn_a','up'])==0);
for (let name,text in before) check(fs.readfile('/etc/config/'+name)==text,'protected_config_changed');
check(!fs.stat('/tmp/restart-inbound_vpn.json'),'protected_interface_restarted');
fs.unlink('/tmp/egress-mode.json');
print('PASS failed dynamic section verification rolls back without changing protected configurations\n');
