// SPDX-License-Identifier: MIT
// Policy engine shared by the native daemon and native ucode tests.
export function check(ok, code) {
    if (!ok) die(code || 'invalid_argument');
};
export function copy(value) { return json(sprintf('%J', value)); };
export function exact(args, names) {
    check(type(args) == 'object');
    check(length(keys(args)) == length(names));
    for (let k in names) check(exists(args, k));
};
export function ident(s) {
    return type(s) == 'string' && length(s) <= 63 && match(s, /^[A-Za-z0-9_][A-Za-z0-9_.-]*$/);
};
function number(n, low, high) {
    check((type(n) == 'int' || type(n) == 'double') && n >= low && n <= high);
};
export function engine(platform, saved) {
    let state = saved || {
        schema: 1, controller_id: platform.uuid(), revision: 0,
        automation: false, run_mode: 'observe', settings: {
            probe_interval: 60, failure_cycles: 3, quorum: 2, min_hold: 600
        }, policies: {}, events: [], event_seq: 0, operations: {}, recovery_required: false
    };
    check(state.schema == 1, 'storage_error');
    state.blocked ??= {}; state.application ??= {};
    let health = {}, sections = {}, vpns = {}, hold = {}, blocked = state.blocked;
    const persist = () => platform.save(state);
    const event = (kind, context) => {
        push(state.events, {event_id: ++state.event_seq, type: kind,
            time: platform.date(), ...(context || {})});
        if (length(state.events) > 200) shift(state.events);
    };
    function discover() {
        let data = platform.discover();
        vpns = data.vpns;
        let next = {};
        for (let sid, meta in data.sections) {
            if (!ident(sid) || meta.connection_type != 'vpn' || meta.applied_vpn in (platform.capabilities().protected_interfaces || [])) continue;
            if (!state.policies[sid]) state.policies[sid] = {
                mode: 'manual', vpn: meta.applied_vpn, candidates: [],
                algorithm: 'priority', return_policy: 'after_hold', quality_margin: 5, preferences: {}
            };
            next[sid] = {...(state.application[sid] || {}), ...(sections[sid] || {}), ...meta,
                policy: state.policies[sid], all_unavailable: sections[sid]?.all_unavailable || false,
                application_state: sections[sid]?.application_state || state.application[sid]?.application_state || 'observed',
                reason: sections[sid]?.reason || state.application[sid]?.reason || 'discovered',
                last_switch: sections[sid]?.last_switch || state.application[sid]?.last_switch};
            if (sections[sid] && sections[sid].applied_vpn != meta.applied_vpn) {
                state.revision++;
                // LuCI wins. Never immediately overwrite an external assignment.
                state.policies[sid].mode = 'manual'; state.policies[sid].vpn = meta.applied_vpn;
                blocked[sid] = true;
                next[sid].reason = 'external_change';
                event('config_conflict', {section_id: sid});
            }
            hold[sid] ??= platform.now();
        }
        sections = next;
    }
    function h(vpn) {
        let sample = health[vpn];
        if (!sample || platform.now() - sample.sample_at > state.settings.probe_interval * 2 + 5)
            return {available: null, http_test: null, fresh: false};
        return {...sample, fresh: true};
    }
    function eligible(sid, vpn) {
        return vpns[vpn]?.approved == true && h(vpn).available == true &&
            (h(vpn).section_checks?.[sid] ?? true) == true;
    }
    function policy_ok(sid, p) {
        exact(p, ['mode','vpn','candidates','algorithm','return_policy','quality_margin','preferences']);
        check(p.mode in ['manual','auto']);
        check(ident(p.vpn) && vpns[p.vpn]?.approved == true);
        check(type(p.candidates) == 'array' && length(p.candidates) > 0 && length(p.candidates) <= 32);
        let unique = {};
        for (let v in p.candidates) {
            check(ident(v) && vpns[v]?.approved == true && !unique[v]); unique[v] = true;
        }
        check(p.algorithm in ['priority','quality'] && p.return_policy in ['sticky','after_hold']);
        number(p.quality_margin, 0, 100); check(type(p.preferences) == 'object');
        for (let v, n in p.preferences) { check(unique[v]); number(n, -10, 10); }
        if (p.mode == 'manual' && p.vpn != sections[sid].applied_vpn)
            check(eligible(sid, p.vpn), 'unavailable');
    }
    function sample_all() {
        let samples = platform.probe(vpns, sections, state.settings);
        for (let vpn, sample in samples) {
            if (!vpns[vpn] || !vpns[vpn].approved) continue;
            let old = health[vpn] || {}, passes = 0;
            for (let key, ok in sample.checks) if (ok) passes++;
            let pass = passes >= state.settings.quorum && sample.egress == true;
            let failures = pass ? 0 : (old.failures || 0) + 1;
            let available = pass ? true : (failures >= state.settings.failure_cycles ? false : old.available);
            let window = old.window || []; push(window, pass ? 100 : 0);
            if (length(window) > 10) shift(window);
            let sum = 0; for (let n in window) sum += n;
            health[vpn] = {...sample, failures, available, http_test: pass,
                success_percent: sum / length(window), stability_percent: sum / length(window),
                window, sample_at: platform.now()};
            if (available != old.available && available != null)
                event(available ? 'vpn_recovered' : 'vpn_failed', {vpn});
        }
    }
    function score(v, policy) {
        let sample = h(v);
        return (sample.success_percent || 0) * 0.7 + (sample.stability_percent || 0) * 0.2 +
            10 / (1 + (sample.latency_ms || 0) / 100) + (policy.preferences[v] || 0);
    }
    function choose(sid, s) {
        let p = s.policy, current = s.applied_vpn;
        if (p.mode == 'manual') return current == p.vpn || eligible(sid,p.vpn) ? p.vpn : null;
        let usable = filter(p.candidates, v => eligible(sid,v));
        if (!length(usable)) return null;
        let best = usable[0];
        if (p.algorithm == 'quality') for (let v in usable) if (score(v,p) > score(best,p)) best = v;
        if (!(current in usable)) return h(current).available == null ? current : best;
        if (platform.now() - hold[sid] < state.settings.min_hold ||
            (p.algorithm == 'priority' && p.return_policy == 'sticky')) return current;
        if (p.algorithm == 'quality' && score(best,p) - score(current,p) < p.quality_margin) return current;
        return best;
    }
    function tick(request_id) {
        discover();
        let targets = {};
        for (let sid, s in sections) {
            let target = choose(sid,s); s.proposed_vpn = target;
            let down = s.policy.mode == 'auto' && length(s.policy.candidates) > 0 &&
                length(filter(s.policy.candidates, v => h(v).available != false)) == 0;
            if (down != s.all_unavailable) event(down ? 'all_unavailable' : 'section_recovered', {section_id:sid});
            s.all_unavailable = down;
            if (target == null || target == s.applied_vpn || blocked[sid]) continue;
            if (state.run_mode != 'control') s.application_state = 'pending_observe';
            else if (s.policy.mode == 'auto' && !state.automation) s.application_state = 'automation_paused';
            else if (!state.recovery_required) targets[sid] = target;
        }
        let outcome = 'completed';
        if (length(keys(targets))) {
            check(platform.ready(), 'control_disabled');
            state.revision++;
            let before = {}; for (let sid, target in targets) before[sid] = sections[sid].applied_vpn;
            state.journal = {request_id, before, targets}; persist();
            outcome = platform.apply(targets, state.journal);
            if (outcome == 'recovery_required') state.recovery_required = true;
            // Refresh without treating our own write as a LuCI conflict.
            let actual = platform.discover().sections;
            for (let sid, target in targets) {
                sections[sid].applied_vpn = actual[sid]?.applied_vpn;
                sections[sid].application_state = outcome == 'completed' ? 'applied' : outcome;
                sections[sid].reason = outcome;
                if (outcome == 'completed') {
                    hold[sid] = platform.now(); sections[sid].last_switch = platform.date();
                    event('switched', {section_id:sid, previous:before[sid], vpn:target, request_id});
                } else blocked[sid] = true;
                state.application[sid] = {application_state:sections[sid].application_state,
                    reason:sections[sid].reason,last_switch:sections[sid].last_switch};
            }
            if (outcome != 'completed') event(outcome, {request_id});
            if (outcome != 'recovery_required') delete state.journal;
        }
        persist(); return outcome;
    }
    function status() {
        let data = {};
        for (let v, meta in vpns) {
            data[v] = {...meta, ...h(v)}; delete data[v].window; delete data[v].sample_at;
        }
        return {api_version:1, controller_id:state.controller_id, boot_id:platform.boot_id,
            revision:state.revision, simulated:false, automation:state.automation,
            run_mode:state.run_mode, settings:copy(state.settings), sections:copy(sections), vpns:data,
            recovery_required:state.recovery_required, latest_event_id:state.event_seq,
            ...platform.service_status()};
    }
    function read(method, args) {
        if (method in ['capabilities','status','sections','vpns']) {
            exact(args, []);
            if (method == 'capabilities') return {api_version:1, controller_id:state.controller_id,
                controller_kind:'openwrt_ucode', simulated:false, simulation_control:false,
                production_control:false, safe_apply:false, experimental_control:platform.ready(),
                fail_closed_verified:false, real_egress_verified:false, real_egress_verification:true,
                policy_control:true, section_endpoints:true, async_operations:true,
                ...platform.capabilities()};
            if (method == 'status') return status();
            return status()[method];
        }
        if (method == 'operation') {
            exact(args,['request_id']); return copy(state.operations[args.request_id] || {status:'unknown'});
        }
        if (method == 'history') {
            exact(args,['after']); check(type(args.after) == 'int' && args.after >= 0);
            return {events:filter(state.events, e => e.event_id > args.after), cursor:state.event_seq,
                gap:length(state.events) > 0 && args.after < state.events[0].event_id - 1};
        }
        die('method_not_found');
    }
    function mutate(method, args) {
        let shapes = {set_automation:['enabled'], configure:['run_mode','probe_interval','failure_cycles','quorum','min_hold'],
            set_policy:['section_id','policy'], assign_vpn:['section_id','vpn'], restart_vpn:['vpn'], diagnose:[]};
        check(exists(shapes,method), 'method_not_found');
        exact(args, [...shapes[method],'request_id','expected_revision']);
        check(type(args.request_id) == 'string' && match(args.request_id,/^[A-Za-z0-9_-]{8,80}$/));
        let digest = sprintf('%J', {method,args});
        let old = state.operations[args.request_id];
        if (old) { check(old.digest == digest,'conflict'); return copy(old); }
        discover(); check(type(args.expected_revision) == 'int' && args.expected_revision == state.revision,'conflict');
        check(!state.recovery_required,'recovery_required');
        let policy;
        if (method == 'set_automation') check(type(args.enabled) == 'bool');
        if (method == 'configure') {
            check(args.run_mode in ['observe','control']);
            number(args.probe_interval,60,3600); number(args.min_hold,0,86400);
            check(type(args.failure_cycles) == 'int' && type(args.quorum) == 'int');
            number(args.failure_cycles,1,10); number(args.quorum,2,3);
            if (args.run_mode == 'control') check(platform.ready(),'control_disabled');
        }
        if (method in ['assign_vpn','set_policy']) {
            check(ident(args.section_id) && sections[args.section_id]);
            policy = method == 'set_policy' ? args.policy : {...copy(sections[args.section_id].policy),mode:'manual',vpn:args.vpn};
            // First manual assignment can seed the locally approved candidates.
            if (!length(policy.candidates)) policy.candidates = filter(keys(vpns),v => vpns[v].approved);
            policy_ok(args.section_id,policy);
        }
        if (method == 'restart_vpn') {
            check(state.run_mode == 'control','control_disabled');
            check(ident(args.vpn) && vpns[args.vpn]?.approved == true &&
                vpns[args.vpn]?.restart_allowed == true && platform.ready(), 'restart_forbidden');
        }
        state.revision++;
        let result = {status:'pending', request_id:args.request_id, revision:state.revision,digest};
        state.operations[args.request_id] = result;
        while (length(keys(state.operations)) > 256) delete state.operations[keys(state.operations)[0]];
        if (method == 'set_automation') state.automation = args.enabled;
        if (method == 'configure') {
            state.run_mode = args.run_mode;
            for (let k in keys(state.settings)) state.settings[k] = args[k];
        }
        if (policy) {
            state.policies[args.section_id] = copy(policy); sections[args.section_id].policy = state.policies[args.section_id];
            delete blocked[args.section_id]; event('policy_changed',{section_id:args.section_id,request_id:args.request_id});
        }
        persist();
        if (method == 'diagnose') sample_all();
        if (method == 'restart_vpn') {
            // Persist before down. Recovery may only bring this interface UP, never replay down.
            state.journal = {kind:'restart_vpn',request_id:args.request_id,vpn:args.vpn};
            event('vpn_restart_started',{vpn:args.vpn,request_id:args.request_id}); persist();
            result.status = platform.restart(args.vpn);
            if (result.status == 'recovery_required') state.recovery_required = true;
            else delete state.journal;
            delete health[args.vpn];
            event(result.status == 'completed' ? 'vpn_restart_completed' : 'vpn_restart_failed',
                {vpn:args.vpn,request_id:args.request_id,code:result.status});
        } else result.status = tick(args.request_id);
        result.revision = state.revision; persist(); return copy(result);
    }
    discover();
    if (state.journal) {
        let result = platform.recover(state.journal);
        state.recovery_required = result == 'recovery_required';
        if (!state.recovery_required) delete state.journal;
        for (let id, op in state.operations) if (op.status == 'pending') op.status = result;
        event('restart_recovery',{code:result});
    } else {
        for (let id, op in state.operations) if (op.status == 'pending') op.status = 'interrupted';
    }
    persist();
    return {state, read, mutate, sample_all, tick, discover, status};
};
