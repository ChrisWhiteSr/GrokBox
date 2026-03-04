#!/usr/bin/env python3
"""Patch grokbox_daemon.py to initialize paused=False before the main loop."""
import sys

path = "/Code/grokbox/grokbox_daemon.py"
content = open(path).read()

target = '    log.info("GrokBox Daemon starts listening for \'Hey Jarvis\'...")\n    \n    try:'
replacement = '    log.info("GrokBox Daemon starts listening for \'Hey Jarvis\'...")\n    paused = False\n    \n    try:'

if "paused = False" in content:
    print("Already patched — nothing to do.")
    sys.exit(0)

if target in content:
    patched = content.replace(target, replacement, 1)
    open(path, "w").write(patched)
    print("PATCHED OK")
else:
    print("ERROR: Target string not found. Manual fix needed.")
    sys.exit(1)
