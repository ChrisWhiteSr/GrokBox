#!/bin/bash
xsetroot -solid black
# run openbox in background so we get window management (Alt-Tab)
openbox --config-file /dev/null &
OB_PID=$!
sleep 1 # wait for openbox to initialize

# Launch our GUI
/Code/grokbox/venv/bin/python3 /Code/grokbox/grokbox_gui.py

# When GUI exits, kill openbox so xinit dies
kill $OB_PID
