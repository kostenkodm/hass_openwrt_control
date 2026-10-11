import {engine,check,copy} from '../files/usr/share/vpn-controller/core.uc';
let count = 0;
function test(name, fn) { fn(); count++; print('PASS ',name,'\n'); }
function fixture(saved) {
    let now = 1000, calls = [], fail = null, disk = null;
    let actual = {main:'vpn_a',media:'vpn_b'}, samples = {}, metadata = {};
    for (let v in ['vpn_a','vpn_b','vpn_c']) {
        metadata[v] = {id:v,name:v,approved:true,restart_allowed:true};
        samples[v] = {checks:{a:true,b:true,c:true},egress:true,latency_ms:50,external_ip:'203.0.113.1'};
    }
    let p = {uuid:()=>'test-controller-0001',boot_id:'test-boot',now:()=>now,date:()=>'2026-10-11T12:00:00Z',
        save:s=>disk=copy(s),ready:()=>true,capabilities:()=>({protected_interfaces:['inbound_vpn'],vpn_restart:true}),service_status:()=>({}),
        probe:()=>copy(samples),
        discover:()=>{
            let sections={}; for (let sid,v in actual) sections[sid]={id:sid,connection_type:'vpn',applied_vpn:v};
            return {sections,vpns:copy(metadata)};
        },
        apply:(targets,j)=>{
            push(calls,copy(targets));
            if (fail) return fail;
            for (let sid,v in targets) actual[sid]=v;
            return 'completed';
        }, restart:v=>{push(calls,{restart:v});return fail || 'completed';},
        recover:j=>j.kind == 'restart_vpn' ? 'interrupted' : 'rolled_back'};
    let c = engine(p,saved);
    function cmd(method, args) { return c.mutate(method,{...args,request_id:'request-'+sprintf('%08d',c.state.revision),expected_revision:c.state.revision}); }
    let policy = {mode:'auto',vpn:'vpn_a',candidates:['vpn_a','vpn_b','vpn_c'],algorithm:'priority',return_policy:'after_hold',quality_margin:5,preferences:{}};
    function control() { cmd('configure',{run_mode:'control',probe_interval:60,failure_cycles:3,quorum:2,min_hold:600}); }
    function down(v) { samples[v]={checks:{a:false,b:false,c:false},egress:false}; }
    return {c,p,cmd,policy,control,down,samples,actual,calls,advance:n=>now+=n,fail:s=>fail=s,disk:()=>copy(disk)};
}
test('safe defaults and dynamic sections',()=>{
    let f=fixture(); check(f.c.state.run_mode=='observe' && !f.c.state.automation);
    check(length(keys(f.c.status().sections))==2 && !f.c.status().vpns.inbound_vpn);
});
test('manual assignment changes one section',()=>{
    let f=fixture(); f.c.sample_all(); f.control(); f.cmd('assign_vpn',{section_id:'main',vpn:'vpn_b'});
    check(f.actual.main=='vpn_b' && f.actual.media=='vpn_b' && length(keys(f.calls[0]))==1);
});
test('observe only proposes',()=>{
    let f=fixture();f.c.sample_all();f.cmd('assign_vpn',{section_id:'main',vpn:'vpn_b'});
    check(f.actual.main=='vpn_a' && f.c.status().sections.main.proposed_vpn=='vpn_b' && !length(f.calls));
});
test('protected interface rejected',()=>{
    let f=fixture(), rejected=false;
    try { f.cmd('assign_vpn',{section_id:'main',vpn:'inbound_vpn'}); } catch(e) {rejected=true;}
    check(rejected && !length(f.calls));
});
test('failure quorum does not switch on one failed cycle',()=>{
    let f=fixture();f.c.sample_all();f.control();f.cmd('set_policy',{section_id:'main',policy:f.policy});
    f.cmd('set_automation',{enabled:true});f.down('vpn_a');f.c.sample_all();f.c.tick();
    check(f.actual.main=='vpn_a');f.c.sample_all();f.c.sample_all();f.c.tick();
    check(f.actual.main=='vpn_b' && f.actual.media=='vpn_b');
});
test('HA offline worker tick continues and holds recovery',()=>{
    let f=fixture();f.c.sample_all();f.control();f.cmd('set_policy',{section_id:'main',policy:f.policy});f.cmd('set_automation',{enabled:true});
    f.down('vpn_a');for(let i=0;i<3;i++)f.c.sample_all();f.c.tick();
    f.samples.vpn_a={checks:{a:true,b:true,c:true},egress:true,latency_ms:5};f.c.sample_all();f.c.tick();check(f.actual.main=='vpn_b');
    f.advance(601);f.c.sample_all();f.c.tick();check(f.actual.main=='vpn_a');
});
test('all unavailable retains assignment, one event',()=>{
    let f=fixture();f.c.sample_all();f.control();f.cmd('set_policy',{section_id:'main',policy:f.policy});f.cmd('set_automation',{enabled:true});
    for(let v in keys(f.samples))f.down(v);for(let i=0;i<3;i++)f.c.sample_all();f.c.tick();f.c.tick();
    check(f.actual.main=='vpn_a');check(length(filter(f.c.state.events,e=>e.type=='all_unavailable'))==1);
});
test('stale health cannot select a VPN',()=>{
    let f=fixture();f.c.sample_all();f.advance(200);let rejected=false;
    try{f.cmd('assign_vpn',{section_id:'main',vpn:'vpn_b'});}catch(e){rejected=true;}check(rejected);
});
test('UCI external assignment pauses automatic ownership',()=>{
    let f=fixture();f.c.sample_all();f.control();f.actual.main='vpn_c';f.c.tick();
    check(f.c.state.policies.main.mode=='manual' && f.c.state.policies.main.vpn=='vpn_c' && !length(f.calls));
});
test('request replay is idempotent and revision guarded',()=>{
    let f=fixture();let args={enabled:true,request_id:'request-repeat001',expected_revision:0};
    let a=f.c.mutate('set_automation',args), b=f.c.mutate('set_automation',args);check(a.revision==b.revision);
    let rejected=false;try{f.c.mutate('set_automation',{...args,enabled:false});}catch(e){rejected=true;}check(rejected);
});
test('rollback stops repeated application',()=>{
    let f=fixture();f.c.sample_all();f.control();f.fail('rolled_back');let result=f.cmd('assign_vpn',{section_id:'main',vpn:'vpn_b'});
    check(result.status=='rolled_back');f.c.tick();check(length(f.calls)==1 && f.actual.main=='vpn_a');
});
test('manual policies survive service restart',()=>{
    let f=fixture();f.c.sample_all();f.cmd('assign_vpn',{section_id:'main',vpn:'vpn_b'});
    let restarted=fixture(f.disk());check(restarted.c.state.policies.main.vpn=='vpn_b' && restarted.c.state.run_mode=='observe');
});
test('unknown method and shell payload rejected',()=>{
    let f=fixture();let rejected=0;
    for(let item in [['exec',{}],['assign_vpn',{section_id:'main;reboot',vpn:'vpn_b'}]])
        try{f.cmd(item[0],item[1]);}catch(e){rejected++;}
    check(rejected==2);
});
test('rollback blocks retries across a restart',()=>{
    let f=fixture();f.c.sample_all();f.control();f.fail('rolled_back');f.cmd('assign_vpn',{section_id:'main',vpn:'vpn_b'});
    let restarted=fixture(f.disk());restarted.c.sample_all();restarted.c.tick();check(!length(restarted.calls));
});
test('restart is idempotent and preserves policies and assignments',()=>{
    let f=fixture();f.control();let before=copy(f.c.state.policies), args={vpn:'vpn_a',request_id:'restart-test001',expected_revision:f.c.state.revision};
    let a=f.c.mutate('restart_vpn',args), b=f.c.mutate('restart_vpn',args);
    check(a.status=='completed' && b.status=='completed' && length(f.calls)==1);
    check(sprintf('%J',before)==sprintf('%J',f.c.state.policies) && f.actual.main=='vpn_a');
});
test('restart rejects protected unknown and unapproved targets',()=>{
    let f=fixture();f.control();let rejected=0;
    for(let vpn in ['inbound_vpn','wan','vpn_a;reboot','missing'])
        try{f.cmd('restart_vpn',{vpn});}catch(e){rejected++;}
    check(rejected==4 && !length(f.calls));
});
test('restart failure cannot be reported as completed',()=>{
    let f=fixture();f.control();f.fail('restart_failed');check(f.cmd('restart_vpn',{vpn:'vpn_a'}).status=='restart_failed');
    check(f.actual.main=='vpn_a' && !f.c.state.journal);
});
test('interrupted restart is recovered without replaying down',()=>{
    let f=fixture(), saved=f.disk();saved.journal={kind:'restart_vpn',vpn:'vpn_a',request_id:'restart-crash001'};
    saved.operations['restart-crash001']={status:'pending'};
    let restarted=fixture(saved);check(restarted.c.state.operations['restart-crash001'].status=='interrupted');
    check(!restarted.c.state.journal && !length(restarted.calls));
});
test('observe forbids actual interface restart',()=>{
    let f=fixture(), rejected=false;
    try{f.cmd('restart_vpn',{vpn:'vpn_a'});}catch(e){rejected=true;}
    check(rejected && !length(f.calls));
});
print(sprintf('NATIVE_CORE_TESTS=%d\n',count));
