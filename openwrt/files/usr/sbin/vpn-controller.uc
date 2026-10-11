#!/usr/bin/ucode
// SPDX-License-Identifier: MIT
import * as fs from 'fs';
import * as ubus from 'ubus';
import * as uloop from 'uloop';
import { engine, copy, check } from '../share/vpn-controller/core.uc';
import { platform } from '../share/vpn-controller/platform.uc';

const base = '/etc/vpn-controller', queue = base + '/request.json';
const helper = '/usr/libexec/vpn-controller-io';
let config = json(fs.readfile(base + '/config.json'));
check(type(config) == 'object','local_config_error');
fs.mkdir('/var/run/vpn-controller',0700);
let lock = fs.open('/var/run/vpn-controller/daemon.lock','a',0600);
check(lock && lock.lock('xn'),'already_running');
uloop.init();
let bus = ubus.connect(); check(bus,'ubus_unavailable');
let cache = null, cache_time = 0;
const parent_stat = split(fs.readfile('/proc/self/stat'),' ');
const parent_pid = parent_stat[0], parent_start = parent_stat[21];
let worker = uloop.task(pipe => {
    let conn = ubus.connect(); check(conn,'ubus_unavailable');
    let p = platform(config,conn);
    let controller = engine(p,json(fs.readfile(base + '/state.json') || 'null'));
    let next_probe = 0;
    function publish() {
        pipe.send({status:controller.status(),capabilities:controller.read('capabilities',{}),
            events:controller.state.events, operations:controller.state.operations});
    }
    publish();
    while (split(fs.readfile('/proc/' + parent_pid + '/stat') || '', ' ')[21] == parent_start) {
        let pending = fs.readfile(queue);
        if (pending) {
            let command = json(pending);
            try { controller.mutate(command.method,command.args); }
            catch(e) {
                controller.state.operations[command.args.request_id] = {
                    status:'rejected', request_id:command.args.request_id,
                    error:{code:split(''+e,'\n')[0]}, revision:controller.state.revision};
                p.save(controller.state);
            }
            fs.unlink(queue); system([helper,'sync',base]); publish();
        }
        if (p.now() >= next_probe) {
            try { controller.sample_all(); controller.tick(); }
            catch(e) { /* No unvalidated data become health successes. Retry next cycle. */ }
            next_probe = p.now() + controller.state.settings.probe_interval;
            publish();
        }
        system(['/bin/sleep','1']);
    }
},data => { cache = data; cache_time = time(); });
check(worker,'worker_unavailable');
let watchdog;
watchdog = uloop.timer(1000,function() {
    if (worker.finished()) { uloop.end(); exit(1); }
    watchdog.set(1000);
});
let term = uloop.signal('SIGTERM',() => {worker.kill(); uloop.end();});
function response(method, req) {
    let args = copy(req.args || {}); delete args.ubus_rpc_session;
    if (!cache) return {ok:false,error:{code:'unavailable'}};
    if (method == 'capabilities') return cache.capabilities;
    if (method == 'status') {
        let snapshot = copy(cache.status);
        if (time() - cache_time > snapshot.settings.probe_interval * 2 + 5)
            for (let v,meta in snapshot.vpns) {meta.available=null;meta.http_test=null;meta.fresh=false;}
        return snapshot;
    }
    if (method in ['sections','vpns']) return cache.status[method];
    if (method == 'history') {
        if (type(args.after) != 'int' || args.after < 0) return {ok:false,error:{code:'invalid_argument'}};
        return {events:filter(cache.events,e => e.event_id > args.after), cursor:cache.status.latest_event_id,
            gap:length(cache.events) > 0 && args.after < cache.events[0].event_id - 1};
    }
    let pending = fs.readfile(queue), command = pending ? json(pending) : null;
    if (method == 'operation') {
        if (cache.operations[args.request_id]) return cache.operations[args.request_id];
        let durable = json(fs.readfile(base + '/state.json') || '{}').operations?.[args.request_id];
        if (durable) return durable.revision > cache.status.revision ?
            {status:'pending',request_id:args.request_id} : durable;
        return command?.args.request_id == args.request_id ?
            {status:'pending',request_id:args.request_id} : {status:'unknown'};
    }
    if (type(args.request_id) != 'string' || !match(args.request_id,/^[A-Za-z0-9_-]{8,80}$/) ||
        type(args.expected_revision) != 'int') return {ok:false,error:{code:'invalid_argument'}};
    if (cache.operations[args.request_id]) {
        let old = cache.operations[args.request_id];
        if (old.digest && old.digest != sprintf('%J',{method,args})) return {ok:false,error:{code:'conflict'}};
        return old;
    }
    if (command) return command.method == method && sprintf('%J',command.args) == sprintf('%J',args) ?
        {status:'pending',request_id:args.request_id} : {ok:false,error:{code:'busy'}};
    if (args.expected_revision != cache.status.revision) return {ok:false,error:{code:'conflict'}};
    let text = sprintf('%J',{method,args});
    if (length(text) > 16384) return {ok:false,error:{code:'invalid_argument'}};
    check(fs.writefile(queue + '.next',text) != null,'storage_error'); fs.chmod(queue + '.next',0600);
    check(system([helper,'sync',queue + '.next']) == 0,'storage_error');
    check(fs.rename(queue + '.next',queue),'storage_error');
    check(system([helper,'sync',base]) == 0,'storage_error');
    return {status:'pending',request_id:args.request_id};
}
const write = {request_id:'',expected_revision:0,ubus_rpc_session:''};
let shapes = {capabilities:{ubus_rpc_session:''},status:{ubus_rpc_session:''},
    sections:{ubus_rpc_session:''},vpns:{ubus_rpc_session:''},
    history:{after:0,ubus_rpc_session:''},operation:{request_id:'',ubus_rpc_session:''},
    set_automation:{...write,enabled:true},
    configure:{...write,run_mode:'',probe_interval:0,failure_cycles:0,quorum:0,min_hold:0},
    set_policy:{...write,section_id:'',policy:{}},assign_vpn:{...write,section_id:'',vpn:''},restart_vpn:{...write,vpn:''},diagnose:write};
let methods = {};
for (let method, args in shapes) {
let bound_method = method;
methods[method] = {args,call:req => {
    try { return response(bound_method,req); }
    catch(e) { return {ok:false,error:{code:'storage_error'}}; }
}};
}
check(bus.publish('vpn.controller',methods),'publish_failed');
uloop.run();
