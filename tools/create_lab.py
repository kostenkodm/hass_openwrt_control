"""Prepare a standalone localhost HTTPS laboratory."""
import argparse
from pathlib import Path

from custom_components.openwrt_vpn.demo.certificates import create_lab

__all__ = ["create_lab"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, default=Path("work/lab"))
    folder = parser.parse_args().lab
    create_lab(folder)
    print("Local HTTPS laboratory prepared; credentials remain in the private lab directory.")
