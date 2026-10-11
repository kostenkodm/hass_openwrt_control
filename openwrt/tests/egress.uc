import {check} from '../usr/share/vpn-controller/core.uc';
import {public_ipv4,agreed_ip} from '../usr/share/vpn-controller/egress.uc';
for (let ip in ['0.0.0.0','10.0.0.1','100.64.0.1','127.0.0.1','169.254.1.1','172.16.1.1','192.168.1.1',
    '192.0.0.1','192.0.2.1','192.88.99.1','198.18.0.1','198.51.100.1','203.0.113.1','224.0.0.1','255.255.255.255',
    '1.2.3.256','01.2.3.4','1.2.3','<html>','::1']) check(!public_ipv4(ip),'bad_ip_accepted');
check(public_ipv4('93.184.216.34') && public_ipv4('8.8.8.8'),'public_ip_rejected');
check(agreed_ip([{host:'alpha.test',ip:'93.184.216.34'},{host:'beta.test',ip:'93.184.216.34'}],true)=='93.184.216.34');
check(agreed_ip([{host:'alpha.test',ip:'93.184.216.34'}],true)==null);
check(agreed_ip([{host:'alpha.test',ip:'93.184.216.34'},{host:'ALPHA.test',ip:'93.184.216.34'}],true)==null);
check(agreed_ip([{host:'alpha.test',ip:'93.184.216.34'},{host:'beta.test',ip:'93.184.216.35'}],true)==null);
check(agreed_ip([{host:'alpha.test',ip:'10.0.0.1'},{host:'beta.test',ip:'10.0.0.1'}],true)==null);
check(agreed_ip([{host:'alpha.test',ip:'198.51.100.2'}],false)=='198.51.100.2');
print('PASS dynamic public IPv4 validation, distinct echo hosts, agreement and static compatibility\n');
