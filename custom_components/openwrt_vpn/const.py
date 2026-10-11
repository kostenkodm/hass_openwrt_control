"""Constants for the limited controller protocol."""
DOMAIN = "openwrt_vpn"
OBJECT = "vpn.controller"
PLATFORMS = ["sensor", "binary_sensor", "select", "switch", "button"]
READ_METHODS = frozenset({"capabilities", "status", "sections", "vpns", "history", "operation"})
WRITE_METHODS = frozenset({"set_automation", "configure", "set_policy", "assign_vpn", "diagnose", "restart_vpn"})
