// Test-only netifd/procd fixture; real UCI, ubusd, rpcd, Podkop and sing-box.
import * as fs from 'fs';
import * as ubus from 'ubus';
import * as uloop from 'uloop';
uloop.init(); let bus=ubus.connect();
for(let name in ['vpn_a','vpn_b','vpn_c','lan','inbound_vpn']) {
    let bound = name;
    let status={up:true,device:bound,l3_device:bound,'ipv4-address':[{address:'127.0.0.1',mask:8}]};
    let counts={down:0,up:0};
    function action(method) {
        counts[method]++;
        fs.writefile('/tmp/restart-'+bound+'.json',sprintf('%J',counts));
        if (system(['/sbin/ip','link','set',bound,method]) != 0) return null;
        status.up = method == 'up';return {};
    }
    bus.publish('network.interface.'+bound,{status:{args:{},call:()=>status},
        down:{args:{},call:()=>action('down')},up:{args:{},call:()=>action('up')}});
}
bus.publish('service',{list:{args:{name:''},call:()=>{
    let pid=trim(fs.readfile('/tmp/sing-box.pid') || '');
    return {'sing-box':{instances:{main:{running:pid && fs.stat('/proc/'+pid)!=null,
        pid:+pid,command:['/usr/bin/sing-box','run','-c','/etc/sing-box/config.json']}}}};
}}});
bus.publish('system',{reboot:{args:{},call:()=>({forbidden:true})}});
bus.publish('network.interface.wan',{down:{args:{},call:()=>({forbidden:true})}});
uloop.run();
