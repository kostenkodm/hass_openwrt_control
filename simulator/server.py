"""Standalone localhost HTTPS ubus laboratory using the integration's demo backend."""
from custom_components.openwrt_vpn.demo.server import APP_KEY, Lab, create_app, main

__all__ = ["APP_KEY", "Lab", "create_app", "main"]

if __name__ == "__main__":
    main()
