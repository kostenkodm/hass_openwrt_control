import * as fs from 'fs';
import {connect} from 'ubus';
import {platform} from '../usr/share/vpn-controller/platform.uc';
import {engine,check} from '../usr/share/vpn-controller/core.uc';
const bus=connect();
const p=platform(json(fs.readfile('/etc/vpn-controller/config.json')),bus);
check(p.ready(),'preflight_failed'); print('PASS real OpenWrt preflight\n');
const c=engine(p,null); c.sample_all();
let seq=0;
function command(method,args) {
    return c.mutate(method,{...args,request_id:'native-test-'+sprintf('%08d',seq++),expected_revision:c.state.revision});
}
check(c.status().vpns.vpn_a.http_test && c.status().vpns.vpn_b.http_test,'bound_probes_failed');
print('PASS actual device-bound HTTP probes\n');
command('configure',{run_mode:'control',probe_interval:60,failure_cycles:3,quorum:2,min_hold:600});
let result=command('assign_vpn',{section_id:'main',vpn:'vpn_b'});
print('First apply: ',sprintf('%J',result),'\n');
check(result.status=='completed','native_apply_failed');
check(c.status().sections.main.applied_vpn=='vpn_b' && c.status().sections.media.applied_vpn=='vpn_a');
print('PASS real UCI + native Podkop generation + sing-box egress verification\n');
fs.writefile('/tmp/fault.verify','1');
result=command('assign_vpn',{section_id:'main',vpn:'vpn_a'});
print('Failure outcome: ',sprintf('%J',result),'\n');
check(result.status=='rolled_back','rollback_failed');
check(c.status().sections.main.applied_vpn=='vpn_b','rollback_assignment_failed');
print('PASS failed egress rolls back only controller-owned fields\n');
system(['/sbin/ip','link','set','vpn_a','up']);
