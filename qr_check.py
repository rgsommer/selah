#!/usr/bin/env python3
"""Diagnose the phone-upload QR: what URL it encodes and whether the server is
actually reachable. Read-only.

    python3 qr_check.py
"""

import os
import socket

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from modules.config_utils import load_config


def listening(host, port):
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def main():
    cfg = load_config("display_config.json")
    port = int(cfg.get("web_control_port", 5000))

    try:
        import flask
        flask_ok = f"yes (v{flask.__version__})"
    except Exception as e:
        flask_ok = f"NO  ->  pip3 install --break-system-packages flask   ({e})"
    try:
        import qrcode  # noqa: F401
        qr_ok = "yes"
    except Exception:
        qr_ok = "NO  ->  pip3 install --break-system-packages qrcode"

    from modules.upload_qr import _local_ip, _upload_url
    ip = _local_ip()
    url = _upload_url(cfg)

    print(f"web_control_enabled : {cfg.get('web_control_enabled')}")
    print(f"upload_qr_enabled   : {cfg.get('upload_qr_enabled')}")
    print(f"qrcode installed    : {qr_ok}")
    print(f"flask installed     : {flask_ok}")
    print(f"detected LAN IP     : {ip}")
    print(f"web_control_port    : {port}")
    print(f"QR encodes URL      : {url}")
    print(f"server @ localhost  : {'UP' if listening('127.0.0.1', port) else 'DOWN — Selah web server not running'}")
    print(f"server @ {ip:<15}: {'UP' if listening(ip, port) else 'DOWN — not reachable on the LAN IP'}")
    print()
    print("Now, from a phone ON THE SAME WIFI as the Pi, open this in a browser:")
    print(f"    {url}")
    print("If that page loads by typing it, the server is fine and the issue is")
    print("just QR scanning. If it does NOT load, the phone isn't on the same")
    print("network, or the server isn't running (see the UP/DOWN lines above).")


if __name__ == "__main__":
    main()
