#!/bin/bash
MAC="10:B7:F6:1B:A2:AB"
echo "== Reconnecting to $MAC =="
sudo bluetoothctl trust $MAC
sudo bluetoothctl pair $MAC
sudo bluetoothctl connect $MAC
sleep 3

# Make sure bluetooth is the default audio sink
SINK_ID=$(wpctl status | awk '/Sinks:/,/(Sources|Filters|Video):/' | grep "Big Blue Party" | grep -oP '\b\d+\b' | head -n 1)
if [ -n "$SINK_ID" ]; then
    echo "Setting default audio sink to Node $SINK_ID"
    wpctl set-default $SINK_ID
else
    echo "Could not find Big Blue Party in wpctl Sinks status"
fi

echo "== Testing pw-play =="
pw-play /Code/grokbox/beep.wav

echo "== Restarting Grokbox Service =="
sudo systemctl restart grokbox
echo "Done! The microphone should be hot in a few seconds."
