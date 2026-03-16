---
name: sip-flow-skill
description: Reference for SIP protocol flows, message sequences, error codes, and debugging patterns. Use when analyzing SIP signaling in SSE, MSE, WxCAS, or Mobius logs to understand expected message flows and diagnose failures.
---

# SIP Flow Reference

When analyzing logs that contain SIP signaling (SSE/MSE logs from logstash-wxcalling, Mobius logs from logstash-wxm-app, or WxCAS logs), use this skill to:

- **Understand expected SIP message sequences** for different call scenarios (basic call, call hold, transfer, forwarding, conference).
- **Interpret SIP response codes** and map them to root causes.
- **Identify SIP flow anomalies** such as missing ACKs, retransmissions, unexpected BYEs, or timeout-triggered responses.
- **Correlate SIP dialogs** across services using Call-ID, From/To tags, CSeq, and branch parameters.

Consult the reference document:

- **references/sip_flows.md** — SIP message sequences, response code reference, SDP negotiation, timers, and common failure patterns.

Use this skill alongside the architecture-endpoints-skill to attribute SIP messages to the correct service and understand the signaling path.
