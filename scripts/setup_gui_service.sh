#!/bin/bash
sudo bash -c 'cat > /etc/systemd/system/grokbox-gui.service << EOF
[Unit]
Description=GrokBox Fullscreen GUI
After=systemd-user-sessions.service plymouth-quit-wait.service grokbox.service
Conflicts=getty@tty7.service

[Service]
ExecStart=/usr/bin/xinit /Code/grokbox/venv/bin/python3 /Code/grokbox/grokbox_gui.py -- :0 -nocursor vt7
User=root
StandardInput=tty
TTYPath=/dev/tty7
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF'

sudo systemctl daemon-reload
sudo systemctl enable grokbox-gui.service
sudo systemctl restart grokbox-gui.service
sudo systemctl status grokbox-gui.service
