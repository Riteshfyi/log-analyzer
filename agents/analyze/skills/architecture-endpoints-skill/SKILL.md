---
name: architecture-endpoints-skill
description: Reference for Webex Calling and Contact Center service architecture, endpoint roles, signaling paths, and media paths. Use when analyzing logs to understand which service does what and how traffic flows.
---

# Architecture and Endpoints

When analyzing Mobius, SSE, MSE, or WxCAS logs, use this skill to look up:

- **Service roles**: What each endpoint (Mobius, SSE, MSE, WxCAS, CPAPI, CXAPI, U2C, WDM, Mercury, Kamailio, RTMS, RAS) does and how they interact.
- **Signaling and media paths**: End-to-end flow for WebRTC Calling vs. Contact Center (browser → Mobius → SSE → …).
- **Call types and routing**: WebRTC-to-WebRTC, WebRTC-to-PSTN, WebRTC-to-Desk Phone, and Contact Center flows.

Consult the reference documents:

- **references/architecture_and_endpoints.md** — service roles and endpoint descriptions.
- **references/calling_flow.md** — WebRTC Calling end-to-end architecture (signaling, media, call types).
- **references/contact_center_flow.md** — Contact Center end-to-end architecture (signaling, media, Kamailio/RTMS/RAS, health ping, timers, failover).

Use them to attribute log lines to the correct service and to explain signaling/media paths in your analysis.
