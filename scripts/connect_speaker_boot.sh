#!/bin/bash
MAC="10:B7:F6:1B:A2:AB"
MAX_RETRIES=5

for i in $(seq 1 $MAX_RETRIES); do
    bluetoothctl trust "$MAC"
    bluetoothctl connect "$MAC"
    sleep 3

    # Check if connected
    if bluetoothctl info "$MAC" | grep -q "Connected: yes"; then
        # Give PipeWire time to register the sink
        sleep 2
        SINK_ID=$(wpctl status | awk '/Sinks:/,/(Sources|Filters|Video):/' | grep "Big Blue Party" | grep -oP '\b[0-9]+\b' | head -n 1)
        if [ -n "$SINK_ID" ]; then
            wpctl set-default "$SINK_ID"
            echo "Bluetooth speaker connected and set as default (attempt $i)"
            exit 0
        fi
    fi
    echo "Attempt $i failed, retrying in 3s..."
    sleep 3
done

echo "Could not connect Bluetooth speaker after $MAX_RETRIES attempts"
exit 1
