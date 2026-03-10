# Contact Center — End-to-End Architecture

**Signaling Path**: Browser → Mobius → SSE → Kamailio (SIP proxy) → Destination

**Media Path**: Browser ↔ MSE ↔ Destination

**Additional Contact Center Components:**

- **Kamailio**: SIP proxy for Contact Center — handles SIP REGISTER, stores registration details on RTMS Application Server, routes calls to the appropriate destination.
- **RTMS**: Real-time microservice enabling persistent WebSocket connections between clients and backend services.
- **RAS** (Registration, Activation, and provisioning Service): Stores SIP REGISTER Contact and Path headers with expiry, maintains metrics for WebRTC active sessions and calls to WebRTC phones.

**Health ping:** Mobius exposes `/api/v1/ping` (and internal variants). Response should be 200 OK with body `{"message":"Healthy"}`. Per-region endpoints exist for INT and PROD (e.g. US, CA, EU, UAE, UK, AU Sydney/Melbourne, South Africa, Saudi Arabia, Singapore). Backup clusters exist in some regions (e.g. UK, AU, South Africa, Saudi). Use the Mobius Runbook for the full health-check endpoint table and cluster list.

**Timers in Mobius:**

- **Registration keepalive (browser):** Browser sends keepalive periodically to keep registration active. Every **30 seconds**; after **5 missed** keepalives, Mobius triggers unregistration.
- **Call keepalive:** Browser sends keepalive during a call to keep it active; valid **within 15 minutes**.
- **SIP APP – Registration refresh:** Depends on Expires header from REGISTER. Mobius refreshes registration with SSE at **3/4 of the Expires value** before expiry.
- **SIP APP – Options scheduler:** Mobius sends OPTIONS ping to SSE to check connectivity; interval **35 seconds**.

**Kafka (call failover):** When Mobius cannot find registration in local cache but finds it in global DB (e.g. after pod/region failover), the new pod communicates with the old pod via Kafka for owner change. Topic: `MOBIUS_REG_HANDOVER_TOPIC = "RegistrationHandover"`, group: `KAFKA_GROUP_ID = "registration_handover"`.

**Inter-regional failover (updated):** In regions with a local backup (e.g. AU: SYD + MEL), if both primary and backup Mobius clusters are down (e.g. both SYD and MEL cannot reach SSE), Client/SDK will **not** failover to US. All WebRTC calls (WxC, WxCC, Guest Calling) in that region can be non-operational. If only the primary cluster is down (SSEs up), Client/SDK fails over to the backup in the same region (e.g. SYD → MEL). Singapore (SIN) and Canada (CA) have a single Mobius cluster each; they continue to use backup regions (e.g. SYD, US-East) when needed.
