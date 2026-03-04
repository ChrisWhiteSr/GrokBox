#!/usr/bin/env python3
"""One-time pairing script for NVIDIA Shield TV.
Run this, then enter the PIN shown on the Shield screen.
"""
import asyncio
import os
import sys

sys.path.insert(0, "/Code/grokbox")
# activate venv packages
site = "/Code/grokbox/venv/lib/python3.13/site-packages"
if site not in sys.path:
    sys.path.insert(0, site)

from androidtvremote2 import AndroidTVRemote, InvalidAuth

SHIELD_IP = "10.0.0.167"
CERT_DIR = "/Code/grokbox/.shield-cert"
CERT_FILE = os.path.join(CERT_DIR, "shield_cert.pem")
KEY_FILE = os.path.join(CERT_DIR, "shield_key.pem")


async def main():
    os.makedirs(CERT_DIR, exist_ok=True)

    remote = AndroidTVRemote(
        client_name="GrokBox",
        certfile=CERT_FILE,
        keyfile=KEY_FILE,
        host=SHIELD_IP,
    )

    await remote.async_generate_cert_if_missing()

    # Try connecting — if already paired, this will succeed
    try:
        await remote.async_connect()
        print(f"Already paired with Shield at {SHIELD_IP}!")
        print(f"  is_on: {remote.is_on}")
        print(f"  current_app: {remote.current_app}")
        print(f"  device_info: {remote.device_info}")
        return
    except InvalidAuth:
        print(f"Not yet paired. Starting pairing with Shield at {SHIELD_IP}...")
    except Exception as e:
        print(f"Connection failed ({e}), attempting pairing...")

    # Start pairing — Shield will show a PIN on screen
    await remote.async_start_pairing()
    print("\nA PIN code should now be displayed on your Shield TV screen.")
    code = input("Enter the PIN: ").strip()

    try:
        await remote.async_finish_pairing(code)
        print("\nPairing successful!")
    except InvalidAuth:
        print("\nWrong PIN. Please try again.")
        return

    # Verify connection
    await remote.async_connect()
    print(f"Connected to Shield at {SHIELD_IP}")
    print(f"  is_on: {remote.is_on}")
    print(f"  current_app: {remote.current_app}")
    print(f"  device_info: {remote.device_info}")
    print(f"\nCerts saved to {CERT_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
