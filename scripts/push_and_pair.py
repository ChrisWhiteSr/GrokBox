"""
One-time setup utility: push connect_speaker.sh to GrokBox Pi and run it.
Requires SSH key auth or will prompt for password interactively.

Usage:
    python3 push_and_pair.py <user@host>
    Example: python3 push_and_pair.py varmint@10.0.0.182
"""
import subprocess
import sys

if len(sys.argv) < 2:
    print("Usage: python3 push_and_pair.py <user@host>")
    print("Example: python3 push_and_pair.py varmint@10.0.0.182")
    sys.exit(1)

target = sys.argv[1]

print("Uploading script...")
subprocess.run(['scp', 'scripts/connect_speaker.sh', f'{target}:/Code/grokbox/scripts/'], check=True)

print("Running setup via SSH...")
subprocess.run(['ssh', target, 'chmod +x /Code/grokbox/scripts/connect_speaker.sh && sudo /Code/grokbox/scripts/connect_speaker.sh'], check=True)
