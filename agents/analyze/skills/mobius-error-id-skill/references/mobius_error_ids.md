# Mobius Error IDs and Call ID Reference

Reference for Mobius HTTP response codes and `mobius-error` codes. Use this to interpret errors in Mobius logs (e.g. `fields.response_status`, mobius-error in response body). **For each error, use the detailed sections below to explain what the error means, user/call impact, likely root cause, and what to check next in your analysis.**

---

## Registration errors (detailed)

### 403 FORBIDDEN — mobius-error 101: Per-user device limit exceeded

**What it means:** The client tried to register a device (browser/WebRTC client) with Mobius, but the system rejected it because the user has hit the maximum number of allowed device registrations, or this specific device is already considered registered, or a registration for this device is already in progress.

**User/call impact:** The user cannot register this device for WebRTC calling. They may see a registration failure in the client; existing calls on other devices may work, but this device will not be able to place or receive calls until registration succeeds.

**Root cause direction:** (1) User has genuinely reached the global per-user device limit — check entitlement and how many devices are registered. (2) Stale or duplicate registration: the device is already in Mobius/Redis cache, or a previous registration never completed and is still in progress. (3) Race: two registration requests for the same device; one may succeed and the other gets 101.

**What to check in logs:** Look for multiple REGISTER attempts for the same `DEVICE_ID` or `USER_ID`; check Redis/local cache state if available. Correlate with unregistration and keepalive logs to see if an old registration was not cleaned up. In your analysis, state whether this looks like a limit issue vs. duplicate/stale registration.

**Log pattern:** Log sample available for error code 101.

---

### 403 FORBIDDEN — mobius-error 102: Device creation not enabled for user

**What it means:** Mobius attempted to create or enable a device for this user by talking to CPAPI (Cisco Platform API). CPAPI either did not return a valid browser client ID or SIP address, or returned a 4xx response, so Mobius will not create the device.

**User/call impact:** Registration fails. The user cannot use this device for WebRTC calling. This is typically an entitlement or provisioning issue, not a transient network failure.

**Root cause direction:** (1) User not entitled for WebRTC/browser calling in CPAPI. (2) CPAPI returned invalid or missing browserClientId/sipAddress. (3) CPAPI returned 4xx (e.g. forbidden, not found) — the exact CPAPI response in upstream logs is key.

**What to check in logs:** Find the CPAPI request/response preceding this error (same time window, same user/device). Check for CPAPI 4xx, timeouts, or empty/invalid browserClientId or sipAddress. In analysis, state whether the failure is at CPAPI (entitlement/provisioning) vs. Mobius logic.

**Log pattern:** Log sample available for error code 102.

---

### 403 FORBIDDEN — mobius-error 103: Device creation failed

**What it means:** Mobius tried to complete device creation by sending a SIP REGISTER to the SSE (Signaling Service Edge). The SSE responded with a final error (e.g. 403), so device creation failed.

**User/call impact:** Registration fails. The browser/client cannot be used for calling. The failure is downstream of Mobius (at the SIP/SSE layer).

**Root cause direction:** SSE rejected the REGISTER — reasons can include policy, capacity, or invalid/duplicate registration data. The SSE 403 (or other final error) is the direct cause; Mobius is correctly surfacing it.

**What to check in logs:** Correlate with SSE logs for the same time and REGISTER transaction (e.g. same sipCallId or correlation IDs). Identify the exact SIP response code and reason from SSE. In analysis, attribute the root cause to SSE and note the SIP response code and any reason phrase.

**Log pattern:** None specifically; look for REGISTER and final response in SIP/SSE logs.

---

### 503 SERVICE UNAVAILABLE (registration)

**What it means:** Registration could not be completed because of a transient or backend failure: timeout to SSE or CPAPI, failure to store state in Redis or local map, outbound proxy (OBP) resolution failure, or an unhandled exception in the registration handler.

**User/call impact:** Registration fails. The user may retry; some causes are transient (timeouts, temporary SSE/CPAPI unavailability), others indicate a misconfiguration or backend issue (Redis, OBP).

**Root cause direction:** Use the log message to narrow down:

- **"Registration failed due to connection timeout for device: {}"** — Mobius could not establish or maintain connection to SSE within the timeout. Check SSE health, network path, and load.
- **"No more retries left, failed to setup connection with all remote hosts"** — Mobius tried all known SSE nodes and could not connect. Points to SSE cluster or network issue.
- **"Failed to add device: {} in sorted set"** — Redis write failed. Check Redis connectivity and capacity.
- **"Device entry insertion failed for deviceId {} sipAoR {} outboundProxy {} userUUID {}"** — Local in-memory map insertion failed (e.g. duplicate key or resource).
- **"BaseHandler Exception: {}"** — Unhandled exception in registration handler; inspect stack trace for the actual failure.
- **"OBP resolution failed"** — Outbound proxy (SSE address) resolution failed (DNS or config).
- **"Unhandled SIP response code received"** — SSE sent a SIP response that Mobius does not handle explicitly; note the code in analysis.
- **"No more retries left, registration failed for device: {} with status: {} {}"** — SSE returned an error after retries; the status and message are the direct cause.
- **"Received Client Exception from Provisioning Client while querying Browser Client Id."** — CPAPI call (for browser client id) timed out or threw. Check CPAPI availability and latency.

**What to check in logs:** Match the exact log message above to the failure; then correlate with SSE, CPAPI, or Redis logs in the same time window. In analysis, name the failing dependency (SSE, CPAPI, Redis, OBP) and the concrete log message.

**Log samples:** "Registration: Error code: 503 SERVICE UNAVAILABLE due to error response from SSE" or "due to CPAPI timeout".

---

### 401 UNAUTHORIZED (registration)

**What it means:** The user’s token (used for the registration request) was rejected. Common Identity (CI) returned 401, so Mobius does not consider the user authenticated.

**User/call impact:** Registration fails. The client must present a valid token (re-auth, token refresh, or re-login).

**Root cause direction:** Expired or invalid token; CI outage or misconfiguration; wrong token or audience. Not usually a Mobius bug.

**What to check in logs:** Confirm CI 401 in upstream calls; check token expiry and issuer/audience if available. In analysis, state that authentication failed and whether it is token lifecycle vs. CI/service issue.

---

### 501 NOT IMPLEMENTED (registration)

**What it means:** An uncaught or unhandled exception occurred during registration. The "501 NOT IMPLEMENTED" is often a generic surface for unexpected code paths (e.g. "Incorrect User Data").

**User/call impact:** Registration fails. May be a bug or unexpected input.

**Root cause direction:** Look for "Incorrect User Data" or similar in logs; indicates bad or unexpected user/device data. Could be client bug, schema change, or missing validation.

**What to check in logs:** Search for "Incorrect User Data" and any stack trace in the same request. In analysis, note whether this looks like bad input vs. server-side bug.

---

## Unregistration errors (detailed)

### 404 NOT FOUND (unregistration)

**What it means:** The client asked to unregister a device, but Mobius has no registration record for that identifier (e.g. device already unregistered, or wrong ID).

**User/call impact:** Unregistration request fails. From a user perspective this is often harmless (device was already unregistered); sometimes it indicates a client sending unregister for a non-existent registration.

**Root cause direction:** (1) Idempotent: device was already unregistered. (2) Client sent wrong device/session ID. (3) Registration expired or was cleaned up elsewhere before unregister arrived.

**What to check in logs:** "Registration not found for {}" — confirm the identifier in the message. In analysis, state whether this is expected (idempotent) or points to client/identifier mix-up.

---

### 503 SERVICE UNAVAILABLE (unregistration)

**What it means:** Unregistration could not be completed. Two main cases: (1) Mobius intentionally blocks unregister because the device still has active call(s) — unregister would be unsafe. (2) An exception occurred while handling the unregistration request.

**User/call impact:** Unregistration fails. In case (1), this is correct behavior (protecting active calls). In case (2), the device may remain in a registered state until retry or cleanup.

**Root cause direction:** (1) "Call/s exist for this device, can not continue with unregister request." — By design; do not treat as a bug. (2) "Caught exception {} while handling unregistration" — Inspect the exception; could be backend (e.g. Redis) or logic bug.

**What to check in logs:** Match the message above; if calls exist, correlate with call logs for that device. In analysis, distinguish "blocked by design" vs. "exception during unregister".

---

### 501 NOT IMPLEMENTED (unregistration)

**What it means:** Unhandled exception during unregistration (e.g. "Incorrect User Data"). Same interpretation as 501 for registration.

**User/call impact:** Unregistration may not complete; device state may be inconsistent.

**What to check in logs:** Look for "Incorrect User Data" or exception details. In analysis, note bad input or server-side handling gap.

---

## Call errors (detailed)

### 403 FORBIDDEN — mobius-error 112: Device is not registered

**What it means:** The client sent a call-related request (e.g. make call, answer, disconnect) using a device-id that Mobius does not have in its registration state. The device either never registered successfully or already unregistered.

**User/call impact:** The call action fails. User may see "device not registered" or similar. They may need to re-register (refresh, reload, or re-login) before placing or answering calls.

**Root cause direction:** (1) Registration failed earlier (check for 101/102/103/503 in registration flow). (2) Registration expired or was removed (keepalive miss, unregister). (3) Client using wrong device-id or session. (4) Race: unregister completed before call request was processed.

**What to check in logs:** Confirm there is no successful registration for this device-id in the same time window; look for prior registration failures or unregister. "Call: Error code: 403 : FORBIDDEN, mobius-error: 112, due to Device not registered". In analysis, tie 112 to the registration state and any prior registration/unregistration events.

---

### 403 FORBIDDEN — mobius-error 115: User Busy

**What it means:** The device cannot accept this call (or call action) because it is already busy: either a call is in the process of being set up ("allocating" state) or the SSE returned SIP 486 Busy Here.

**User/call impact:** Incoming call may not be presented, or a new outbound call may fail. The user or the other party may see "busy" or "user busy".

**Root cause direction:** (1) Legitimate: user/device is on another call or call is being set up. (2) Stuck state: a previous call left the device in "allocating" and never cleared — look for incomplete call teardown. (3) SSE sent 486 (callee busy) — downstream routing or endpoint state.

**What to check in logs:** Look for another call or "allocating" state for the same device; look for 486 in SIP logs. "Call: Error code: 403: FORBIDDEN, mobius-error: 115, due to User busy". In analysis, state whether this is expected (user busy) vs. possible stuck state.

---

### 403 FORBIDDEN — mobius-error 118: Not Acceptable

**What it means:** The call or session setup was rejected by the SSE with SIP 488 Not Acceptable. Typically relates to SDP/negotiation: codecs, media, or session parameters were not acceptable to the far end or the network.

**User/call impact:** Call setup fails. User may see a generic call failure or "not acceptable" type message.

**Root cause direction:** SDP/codec mismatch, unsupported media type, or policy rejection. Check SDP in SIP messages (offer/answer) and any codec or media restrictions in SSE/downstream.

**What to check in logs:** Find the 488 response from SSE and the associated INVITE/offer. Compare SDP (m= lines, codecs) with what the client sent. In analysis, describe the negotiation failure (e.g. no common codec, or rejected media).

---

### 403 FORBIDDEN — mobius-error 119: Call Rejected

**What it means:** The call was explicitly rejected by the SSE with SIP 403 or 603 (or equivalent). The network or destination rejected the call, not Mobius.

**User/call impact:** Call fails; user may see "call rejected" or "declined".

**Root cause direction:** Policy (e.g. blocking), destination rejected (603 Decline), or SSE/backend returned 403/603. The root cause is downstream; Mobius is forwarding the rejection.

**What to check in logs:** Find the 403/603 from SSE and the reason phrase. Correlate with WxCAS/SSE logs for routing and rejection reason. In analysis, state who rejected (SSE, destination, policy) and the SIP code and reason.

---

### 403 FORBIDDEN — mobius-error 121: Mid Call Request Rejected

**What it means:** A mid-call request (e.g. hold, resume, transfer, add media) was sent to CXAPI (Call Control API), and CXAPI returned a 4xx response. Mobius surfaces this as 121.

**User/call impact:** The mid-call action (hold, transfer, etc.) fails. The call may remain in its previous state; user may see an error for that action.

**Root cause direction:** CXAPI rejected the request — invalid state, invalid parameters, or policy. Check CXAPI logs and the specific 4xx code and body.

**What to check in logs:** Correlate with CXAPI request/response for the same call and timestamp. Note the 4xx code and any error message. In analysis, attribute the failure to CXAPI and the reason (state, params, or policy).

---

### 503 SERVICE UNAVAILABLE — mobius-error 117: Timeout error

**What it means:** Offer-answer (SDP) negotiation did not complete within the expected time (ROAP_TIMEOUT). The client or the network did not complete the exchange in time.

**User/call impact:** Call setup fails with a timeout. User may see "call failed" or "timeout".

**Root cause direction:** (1) Network or client latency; (2) Client or far end not responding to offer/answer in time; (3) ROAP timeout value too short for the path. Check timing between offer and answer in logs.

**What to check in logs:** Measure time between sending offer and receiving answer (or timeout). Look for delayed or lost SIP/HTTP messages. In analysis, state whether the timeout is client-side, network, or backend delay.

---

### 503 SERVICE UNAVAILABLE — mobius-error 120: Not Available

**What it means:** The call or request could not be fulfilled because the SSE rejected it, CXAPI returned 5xx/6xx or threw, or an unknown exception occurred in the call handler (e.g. null pointer). This is a catch-all for "service or logic unavailable".

**User/call impact:** Call or call action fails. User may see a generic error or "not available".

**Root cause direction:** (1) SSE rejection — check SSE logs for the same transaction. (2) CXAPI 5xx/6xx or exception — check CXAPI logs. (3) Null pointer or exception in Mobius call handler — look for stack trace; may be a bug or unexpected state. Example: "Call: Error code: 503 :SERVICE UNAVAILABLE, mobius-error: 120, due to null pointer exception while processing Connect request from client".

**What to check in logs:** Match the exact "due to" message; correlate with SSE and CXAPI. In analysis, name the failing component and whether it looks like backend failure vs. Mobius bug (e.g. NPE).

---

### 404 NOT FOUND — mobius-error 113: Call not found

**What it means:** The client sent a request for an existing call (e.g. answer, disconnect, update) using a call-id that Mobius does not have in its call state. The call may have already ended, or the call-id is wrong or from another instance.

**User/call impact:** The call action fails. User may see "call not found" or similar. The call may have been torn down already, or there is a client/state sync issue.

**Root cause direction:** (1) Call already ended (BYE, timeout, or cleanup). (2) Client using stale or wrong call-id. (3) Request routed to a Mobius instance that does not have this call (instances may not share call state). (4) Race: teardown completed before the request was processed.

**What to check in logs:** "Call: Error code: 404 NOT FOUND, mobius-error: 113, Call not found". Look for BYE or call teardown for this call-id before the 404; check if multiple Mobius instances are involved. In analysis, state whether the call was already gone vs. wrong ID vs. instance mismatch.

---

### 500 INTERNAL SERVER ERROR — mobius-error 114: Error in processing call

**What it means:** Something went wrong while Mobius was processing the call: SSE rejected a request, an exception occurred while processing the SSE response, or the client sent an event that is not valid in the current call state (e.g. answer when not ringing).

**User/call impact:** Call or call action fails; user may see a generic server error.

**Root cause direction:** (1) SSE rejection — see SSE logs. (2) Unknown exception processing SSE response — look for stack trace. (3) "Client event isn't supported in current call state" — client sent an out-of-order or invalid event (e.g. answer before 180/183, or disconnect in wrong state). Example: "Call: Error code: 500 SERVER ERROR, mobius-error: 114, due to client event isn't supported in current call state."

**What to check in logs:** Match the "due to" message; correlate call state (ringing, connected, etc.) with the client event. In analysis, state whether the failure is client protocol/state machine vs. SSE/Mobius backend.

---

### 400 BAD REQUEST (calls)

**What it means:** The request body or parameters were invalid: parse error, schema mismatch, or missing required field. Mobius could not interpret or validate the request.

**User/call impact:** Call or call action fails with a bad request. Often a client bug or version mismatch.

**Root cause direction:** Malformed JSON, wrong schema, or client sending unexpected/old format. Check the request payload in logs. In analysis, note the invalid field or parse error if present.

---

### 501 NOT IMPLEMENTED (calls)

**What it means:** The endpoint or call flow is not implemented in Mobius. The client may be using a newer API or a flow that this version of Mobius does not support.

**User/call impact:** Request fails with "not implemented".

**Root cause direction:** API/version mismatch or feature not yet implemented. In analysis, note the endpoint or flow and suggest checking client and Mobius versions.

---

## Other / Ingress and platform errors (detailed)

### 429 TOO MANY REQUESTS

**What it means:** Nginx (or the ingress layer) is rate-limiting because the number of requests exceeded the configured threshold. This is a DoS/abuse protection.

**User/call impact:** Requests are rejected with 429; users may see errors or throttling. Can affect many users if a single client or script is noisy.

**Root cause direction:** (1) Noisy client or script (e.g. retries, polling). (2) Traffic spike. (3) Misconfigured threshold. Check request rate per client/IP in logs. In analysis, state whether this is expected rate limiting and which client or IP is driving the load.

---

### 503 SERVICE UNAVAILABLE (service not ready)

**What it means:** The Mobius instance is not considered "ONLINE" — e.g. health check (ping) failed or the service has not finished starting. Load balancer or orchestrator may stop sending traffic to this instance.

**User/call impact:** Requests to this instance fail with 503. Users may be routed to other instances; if all are down, calling fails.

**Root cause direction:** Instance startup, dependency (e.g. Redis, SSE) failing health check, or overload. Check Mobius ping/health and dependency health. In analysis, state whether this is single-instance vs. broader outage.

---

### 499 CLIENT CLOSED REQUEST

**What it means:** The client closed the TCP/HTTP connection before the server sent the response. Nginx records this as 499.

**User/call impact:** The request did not complete; the client may have navigated away, refreshed, or timed out on its side.

**Root cause direction:** User action (close tab, navigate away), client timeout, or network drop. Usually not a server bug. In analysis, note that the client closed the connection and whether it correlates with timeouts or user actions.

---

## Quick lookup: mobius-error code → meaning

| mobius-error | Category   | Short meaning                                              |
|--------------|------------|------------------------------------------------------------|
| 101          | Registration | Per-user device limit exceeded                           |
| 102          | Registration | Device creation not enabled for user (CPAPI)              |
| 103          | Registration | Device creation failed (SSE rejected REGISTER)             |
| 112          | Calls      | Device is not registered                                  |
| 113          | Calls      | Call not found                                            |
| 114          | Calls      | Error in processing call (SSE/call state/event)            |
| 115          | Calls      | User busy                                                 |
| 117          | Calls      | Timeout (e.g. ROAP offer-answer)                          |
| 118          | Calls      | Not acceptable (e.g. 488 from SSE, SDP/codec)            |
| 119          | Calls      | Call rejected (403/603 from SSE)                           |
| 120          | Calls      | Not available (SSE/CXAPI rejection or exception)          |
| 121          | Calls      | Mid-call request rejected (CXAPI 4xx)                     |

---

## Timers (keepalive and unregistration)

When correlating registration/call failures or unexpected unregisters, use these values (Mobius Basic Training and 2 AM Guide):

- **Registration keepalive:** Browser sends keepalive every **30 seconds**. After **5 missed** keepalives, Mobius triggers **unregistration**. So ~150 seconds of no keepalive → unregister.
- **Call keepalive:** Browser sends keepalive during a call; valid **within 15 minutes**.
- **SIP APP – Registration refresh:** Refreshes with SSE at **3/4 of the Expires** header from REGISTER.
- **SIP APP – Options:** OPTIONS ping to SSE every **35 seconds** to check connectivity.

If you see unregistration (e.g. 404 or 503 with "Call/s exist for this device") shortly after gaps in logs, consider keepalive miss (network, client suspend, or load) as a cause.
