# OpenWrt adapter status

Prototype 0.1 contains a limited RPC ACL template. It does not contain an installable native controller or rpcd login provisioning.

The executable controller model is simulator/ and runs locally in Python. It must not be installed on целевом роутере.

Before implementing a deployable ucode/procd package, verify runtime modules, implement real discovery and egress probes, resolve Podkop's stop/start apply gap, and test rollback, LuCI concurrency, IPv4/IPv6 no-leak behavior and inbound_vpn preservation.

Do not install this ACL alone expecting a working vpn.controller object. No UCI, shell, service or network permissions are granted by it.
