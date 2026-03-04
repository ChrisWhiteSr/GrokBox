# Bluetooth A2DP Debug Log
**Device:** Big Blue Party (MAC: `10:B7:F6:1B:A2:AB`)
**Error:** `br-connection-profile-unavailable` / `a2dp-sink profile connect failed: Protocol not available`
**Status:** RESOLVED — seat-monitoring mismatch prevented bluez5 SPA device creation

---

## The Symptom

Every attempt to connect BBP via bluetoothctl fails:

```
Attempting to connect to 10:B7:F6:1B:A2:AB
Failed to connect: org.bluez.Error.Failed br-connection-profile-unavailable
```

bluetoothd log:
```
a2dp-sink profile connect failed for 10:B7:F6:1B:A2:AB: Protocol not available
```

The device pairs fine. It just won't connect.

---

## How A2DP Connection Works on Linux

For the Pi to play audio to a Bluetooth speaker:

1. **WirePlumber** (via `libspa-bluez5`) registers A2DP media endpoints with **bluetoothd** via `org.bluez.Media1.RegisterEndpoint`
2. **bluetoothd** stores these endpoints and advertises the Audio Source UUID on the adapter
3. `bluetoothctl connect <MAC>` negotiates A2DP with the speaker using those endpoints
4. If no endpoints are registered → `Protocol not available`

---

## What We Know

### Infrastructure confirmed present

- `libspa-bluez5.so` installed at `/usr/lib/aarch64-linux-gnu/spa-0.2/bluez5/libspa-bluez5.so` ✓
- WirePlumber `main` profile has `hardware.bluetooth = required` ✓
- WirePlumber reports `bluetooth.audio` in active services (`pw-cli info all`) ✓
- `org.bluez.Media1` interface available on `/org/bluez/hci0` ✓
- `pipewire-audio` v1.4.2-1+rpt3 installed ✓
- Only one WirePlumber instance (runs as varmint) ✓
- No root PipeWire session competing ✓

### The failure pattern

WirePlumber goes through a **register/unregister storm** in the same second:

```
18:13:58  Endpoint registered: sender=:1.780 A2DPSink/sbc
18:13:58  Endpoint registered: sender=:1.780 A2DPSink/aptx_hd
...all codecs registered...
18:15:35  Endpoint unregistered: sender=:1.780 A2DPSink/sbc   ← gone
18:15:35  Endpoint unregistered: sender=:1.780 A2DPSink/aptx_hd
...everything gone, nothing re-registered...
```

After the storm: adapter shows **zero A2DP UUIDs**, D-Bus returns no MediaEndpoints.

---

## Root Cause: WirePlumber Saved State Loop

**Confirmed through live testing** on 2026-02-23.

The cycle:

1. WirePlumber starts **with** a saved `default-routes` entry for BBP:
   ```
   bluez_card.10_B7_F6_1B_A2_AB:profile:a2dp-sink=["headset-output"]
   bluez_card.10_B7_F6_1B_A2_AB:output:headset-output={...}
   ```
2. WirePlumber's profile-state hooks try to restore this saved state onto the BBP card (which is disconnected at startup)
3. Applying a profile/route to a disconnected BT device triggers WirePlumber's bluez5 monitor to tear down and rebuild the media endpoint set
4. The rebuild fails or races — endpoints register then immediately unregister
5. End state: **no endpoints registered**, connection impossible

### The "it worked once" observation

When WirePlumber state was manually wiped and the full PipeWire stack restarted from scratch (no BBP state files), endpoints registered cleanly at 18:13:58 and **stayed registered**. BBP connected successfully. Node 74 "Big Blue Party" appeared in `wpctl status`.

But then starting `grokbox.service` (which opens a PyAudio mic stream) + `grokbox-gui.service` at 18:15:35 caused WirePlumber to unregister everything again — because **connecting BBP had already caused WirePlumber to re-save the state file**, and the service restarts triggered a WirePlumber profile-state restoration attempt on the new saved data.

### The loop

```
Wipe state → WP starts clean → endpoints stay → connect BBP
→ WP saves headset-output state → any WP restart triggers unregister storm
→ must wipe state again
```

---

## What We've Tried

| Action | Result |
|---|---|
| `bluetoothctl trust + pair + connect` | Pair succeeds, connect fails |
| `sudo apt install pipewire-audio` | Already latest (1.4.2-1+rpt3) |
| `systemctl --user restart wireplumber` | Restarts, endpoints register then immediately unregister |
| `systemctl --user restart pipewire pipewire-pulse wireplumber` (together) | Same unregister storm when state file present |
| Full stack restart with **state files wiped** | ✅ Endpoints register and stay — BBP connects successfully |
| BBP connected successfully once | Node 74 appeared in wpctl, audio routing worked |
| `autoswitch-bluetooth-profile.lua` audited | Not the cause — only fires when an audio stream links to BT loopback |
| Created `/etc/wireplumber/wireplumber.conf.d/50-bluetooth.conf` with `bluetooth.use-persistent-storage = false` and `bluetooth.autoswitch-to-headset-profile = false` | Config IS applied (confirmed in debug logs) — but still fails after reboot |
| Rebooted with `50-bluetooth.conf` in place | State files clean, settings applied, **still no endpoints registered** |
| D-Bus monitor during full PipeWire stack restart | WirePlumber calls `GetManagedObjects` on bluetoothd but **never calls `RegisterEndpoint`** |
| `pw-cli info all` factory list | `api.bluez5.*` factories are **completely absent** — SPA plugin not in PipeWire at all |
| WirePlumber debug run (level 3) | Second instance loaded but yielded no bluetooth output — primary WP holds resources |

---

## Updated Root Cause (2026-02-23, session 2)

**The `50-bluetooth.conf` fix did not solve it.** After a clean reboot with clean state files and the config in place, the problem persists.

### What we now know for certain

- WirePlumber IS connecting to bluetoothd (calls `GetManagedObjects` on D-Bus system bus)
- But WirePlumber **never calls `org.bluez.Media1.RegisterEndpoint`** — confirmed via `dbus-monitor`
- `pw-cli info all` shows **zero `api.bluez5.*` factory objects** — the bluez5 SPA plugin is not being instantiated inside PipeWire
- WirePlumber's session.services list says `bluetooth.audio` and `api.bluez` are active — but this reflects WirePlumber's *intent*, not actual SPA device creation
- The `libspa-bluez5.so` file exists and loads OK (`spa-inspect` confirms)
- `alsa-vm.conf` is harmless (only VM ALSA period size tweaks)

### Working theory

WirePlumber's `monitors/bluez.lua` Lua script is running (it calls `GetManagedObjects`), but it is **failing silently when trying to create the `api.bluez5.enum.dbus` SPA device** inside PipeWire. Without that SPA device, no endpoints ever get registered and no `bluez_card.*` devices ever appear.

Possible causes:
1. **Missing dependency at load time** — the Lua script's `requires` list includes `pw.client-device` and `support.export-core`; if either isn't ready when the monitor fires, it bails silently
2. **D-Bus race at boot** — bluetoothd started at 18:51:05, WirePlumber at 18:51:12; the `org.bluez` D-Bus name may not have been fully ready
3. **`bluetooth.use-persistent-storage = false` breaking the SPA device init** — needs to be tested by removing the 50-bluetooth.conf and trying without it

---

## Actual Root Cause (2026-02-23, session 3) — RESOLVED

### The bug

WirePlumber's `monitors/bluez.lua` (line 552) controls whether the Bluetooth SPA device monitor is created:

```lua
if seat_state == "active" then
  monitor = createMonitor()
elseif monitor then
  monitor:deactivate(Feature.SpaDevice.ENABLED)
  monitor = nil
end
```

The logind module reported seat state `"online"` on this headless Pi (no graphical desktop session). Since `"online" != "active"`, **`createMonitor()` was never called**. No SPA device → no `api.bluez5.enum.dbus` → no `RegisterEndpoint` calls to bluetoothd → no A2DP endpoints → `Protocol not available`.

### How it was found

Full WirePlumber debug output (`WIREPLUMBER_DEBUG=5`) captured to `/tmp/wp_debug.log` (36K lines). The smoking gun was line 13223:

```
I 20:32:29.576061  s-monitors bluez.lua:550:startStopMonitor: <WpLogind:...> Seat state changed: online
```

The logind module emits both `"active"` (graphical session on the seat) and `"online"` (user logged in, no graphical session). A headless Raspberry Pi running via SSH/autologin will always be `"online"`, never `"active"`.

### The fix

Disable seat monitoring so the Bluetooth monitor starts unconditionally:

```
# /etc/wireplumber/wireplumber.conf.d/50-bluetooth-no-seat.conf
wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}
```

After restarting the PipeWire stack:
- All A2DP endpoints registered immediately and **stayed registered**
- BBP connected on first attempt
- Connection survived `grokbox.service` restart (no unregister storm)
- BBP automatically set as default PipeWire audio sink

### Previous theories — disposition

| Theory | Verdict |
|---|---|
| WirePlumber saved-state loop causing unregister storm | **Partially correct** — the unregister storm was real but was a *symptom* of WP trying to restore state with no monitor running, not the root cause |
| `bluetooth.use-persistent-storage = false` breaking SPA init | **Wrong** — the `50-bluetooth.conf` override was removed and the problem persisted |
| D-Bus race between bluetoothd and WirePlumber at boot | **Wrong** — timing was fine; the monitor was simply never created |
| Missing SPA dependency at load time | **Wrong** — all deps were satisfied; the Lua script ran but took the wrong branch |

---

## Key Files

| File | Role |
|---|---|
| `/usr/lib/aarch64-linux-gnu/spa-0.2/bluez5/libspa-bluez5.so` | SPA BT plugin (present ✓) |
| `/usr/share/wireplumber/scripts/monitors/bluez.lua` | WirePlumber BT monitor script — **contains the seat state bug** |
| `/usr/share/wireplumber/wireplumber.conf` | Main config — `main` profile has `hardware.bluetooth = required` |
| `/etc/wireplumber/wireplumber.conf.d/50-bluetooth-no-seat.conf` | **The fix** — disables seat monitoring |
| `/Code/grokbox/scripts/connect_speaker.sh` | Manual BT reconnect script |

---

*Last updated: 2026-02-23 (session 3) by Claude Opus 4.6*
