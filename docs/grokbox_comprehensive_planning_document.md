# Grokbox -- Comprehensive Planning Document

*(AI-Orchestrated Voice-First Entertainment Appliance)*

------------------------------------------------------------------------

# 1. Executive Summary

Grokbox is a Linux-based, voice-first home entertainment control system
designed to replace proprietary streaming boxes and fragmented
remote-driven experiences.

It functions as: - A sidecar compute appliance connected to a primary TV
and audio system - A deterministic, domain-specific voice interface - A
subscription-aware content resolver - A composable multi-window media
surface

The primary target audience is older adults who dislike complex remotes
and app navigation.

The long-term vision is an agent-native media control plane that
abstracts away apps entirely.

------------------------------------------------------------------------

# 2. Vision Statement

"Push one button. Say what you want. It just works."

Grokbox removes: - App awareness - Menu navigation - Input juggling -
Subscription confusion - Device routing complexity

Users interact with intent, not interfaces.

------------------------------------------------------------------------

# 3. Target User Definition

Primary User: Older adults (60+)

Pain Points: - Cannot see remote buttons - Forget button functions - Do
not understand app ecosystems - Confused by subscription fragmentation -
Frustrated by inconsistent UI behaviors

Desired Experience: - Single-button interaction - Natural speech
commands - Reliable behavior - No visible complexity

------------------------------------------------------------------------

# 4. System Architecture Overview

## 4.1 Hardware Layer

Base Unit: - Mini PC (Ryzen 5-class) - 4K HDMI output - Integrated audio
routing - Multiple room microphones - BLE push-to-talk remote (single
button)

TV becomes a display panel. Audio system becomes output hardware.
Grokbox owns orchestration.

------------------------------------------------------------------------

## 4.2 Software Stack

### Layer 1: Linux Base

-   Wayland compositor
-   PipeWire for audio routing
-   BLE stack
-   Secure boot & signed updates (future phase)

### Layer 2: Playback Drivers

1.  Web Driver (Chromium app-mode + Widevine)
2.  Android Driver (Waydroid)
3.  Local TV Driver (OTA / FAST / DVR)

### Layer 3: Intent Engine

-   Local ASR
-   Closed-set intent classifier (\~1,000 commands)
-   Slot extraction
-   Confidence scoring
-   Deterministic dispatcher

### Layer 4: Layout Engine

-   Multi-window grid (up to 4x4)
-   Full-screen focus control
-   Ambient UI mode

------------------------------------------------------------------------

# 5. Voice Interaction Model

Remote: - Single push-to-talk button - No navigation controls

Voice Philosophy: - Closed domain command universe - Synonym-aware -
Deterministic intent mapping - No conversational AI in critical path

Example Flow: Speech → ASR → Intent → Driver Selection → Layout →
Playback

------------------------------------------------------------------------

# 6. Content Strategy (Retail Product)

Retail build must remain legally compliant.

Playback hierarchy: 1. Legitimate subscription services (YouTube TV,
Hulu Live, etc.) 2. FAST channels 3. OTA tuner fallback

System resolves: - Which service user subscribes to - Which source
contains requested content - Best available playback method

Power-user mode may support extended integrations but remains separate
from retail build.

------------------------------------------------------------------------

# 7. Development Phases

## Phase 1: Big-Screen Prototype (7 Days)

-   Working YouTube TV in Chromium app mode
-   Spotify API integration
-   Voice → Intent → Playback working
-   Basic grid layout
-   Ambient UI

Hardware polish not required.

## Phase 2: Reliability for Older Users

-   Optimize first 20 core commands
-   Improve confidence handling
-   Subscription resolver logic
-   Habit recognition patterns

## Phase 3: Productization

-   Hardware enclosure
-   Remote refinement
-   OTA updates
-   Legal compliance
-   Support documentation

------------------------------------------------------------------------

# 8. Risk Assessment

Technical Risks: - DRM compatibility - App UI changes breaking
automation - ASR edge cases

Market Risks: - User trust in voice-only systems - Subscription
ecosystem volatility

Mitigation: - Deterministic drivers - Conservative fallback logic -
Continuous command refinement

------------------------------------------------------------------------

# 9. Lab Setup Requirements

Development Lab Needs: - Primary 4K TV - Secondary monitor - Mini PC
test rig - BLE remote prototype - Microphone array - Amp & speakers -
OTA tuner (optional)

Workspace should allow: - Screen compositing testing - Audio routing
experiments - Rapid driver iteration

------------------------------------------------------------------------

# 10. Future Extensions

-   Multi-room orchestration
-   Personalization per user profile
-   Pattern-based predictive suggestions
-   Secure hardware root-of-trust
-   Agent-addressable device APIs

------------------------------------------------------------------------

# 11. Guiding Principle

If an 80-year-old can: - Push one button - Say what they want - And
reliably get it

Then Grokbox succeeds.

Everything else is secondary.
