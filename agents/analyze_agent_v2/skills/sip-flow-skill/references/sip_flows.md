# SIP Flow Reference

## 1. Basic Call Setup (INVITE Transaction)

### Successful Call
```
Caller (Mobius)          SSE              WxCAS           Callee (Mobius)
     |--- INVITE -------->|                |                    |
     |<-- 100 Trying -----|                |                    |
     |                     |--- INVITE --->|                    |
     |                     |<-- 100 Trying-|                    |
     |                     |               |--- INVITE -------->|
     |                     |               |<-- 100 Trying -----|
     |                     |               |<-- 180 Ringing ----|
     |                     |<-- 180 Ring---|                    |
     |<-- 180 Ringing -----|                |                    |
     |                     |               |<-- 200 OK ---------|
     |                     |<-- 200 OK ----|                    |
     |<-- 200 OK ----------|                |                    |
     |--- ACK ------------>|                |                    |
     |                     |--- ACK ------>|                    |
     |                     |               |--- ACK ----------->|
     |                     |               |                    |
     |==================== RTP Media (via MSE) =================|
     |                     |               |                    |
     |--- BYE ------------>|                |                    |
     |                     |--- BYE ------>|                    |
     |                     |               |--- BYE ----------->|
     |                     |               |<-- 200 OK ---------|
     |                     |<-- 200 OK ----|                    |
     |<-- 200 OK ----------|                |                    |
```

### Early Media (183 Session Progress)
When the callee provides early media (ringback tone, IVR prompts):
```
Caller           SSE             WxCAS           Callee
  |--- INVITE ---->|               |                |
  |<-- 100 Trying -|               |                |
  |                |--- INVITE --->|                |
  |                |               |--- INVITE ---->|
  |                |               |<-- 183 + SDP --|
  |                |<-- 183 + SDP -|                |
  |<-- 183 + SDP --|               |                |
  |--- PRACK ----->|               |                |
  |                |--- PRACK ---->|                |
  |                |               |--- PRACK ----->|
  |                |               |<-- 200 (PRACK)-|
  |============ Early Media (RTP via MSE) ==========|
  |                |               |<-- 200 OK -----|
  |<-- 200 OK -----|               |                |
  |--- ACK ------->|               |                |
```

## 2. Call Hold / Resume

### Hold (re-INVITE with sendonly)
```
Holder           SSE             WxCAS           Held Party
  |--- re-INVITE -->|               |                |
  |  (a=sendonly)   |--- re-INVITE->|                |
  |                 |               |--- re-INVITE ->|
  |                 |               |<-- 200 OK -----|
  |                 |               |  (a=recvonly)   |
  |                 |<-- 200 OK ----|                |
  |<-- 200 OK ------|               |                |
  |--- ACK -------->|               |                |
```

### Resume (re-INVITE with sendrecv)
Same flow as hold but with `a=sendrecv` in SDP.

## 3. Call Transfer (REFER)

### Blind Transfer
```
A (Transferor)    SSE        WxCAS       B (Transferee)    C (Target)
  |--- REFER ------>|           |              |               |
  |  Refer-To: C    |           |              |               |
  |<-- 202 Accepted-|           |              |               |
  |                 |--- INVITE (B to C) ----->|               |
  |                 |           |              |--- INVITE --->|
  |<-- NOTIFY ------|           |              |               |
  |  (100 Trying)   |           |              |<-- 200 OK ---|
  |<-- NOTIFY ------|           |              |               |
  |  (200 OK)       |           |              |               |
  |--- BYE -------->|  (A hangs up)            |               |
  |<-- 200 OK ------|           |              |               |
```

### Attended Transfer
Same as blind but the transferor first establishes a call with the target (consultation call), then sends REFER with `Replaces` header.

## 4. Call Forwarding

### Forwarding (302 Moved Temporarily)
```
Caller           SSE             WxCAS           Forwarder       Target
  |--- INVITE ---->|               |                |               |
  |                |--- INVITE --->|                |               |
  |                |               |--- INVITE ---->|               |
  |                |               |<-- 302 --------|               |
  |                |               |  Contact: target               |
  |                |               |--- ACK ------->|               |
  |                |               |--- INVITE ---->|-------------->|
  |                |               |<-- 200 OK -----|---------------|
  |                |<-- 200 OK ----|                |               |
  |<-- 200 OK -----|               |                |               |
```

## 5. SIP Response Code Reference

### 1xx Provisional
| Code | Meaning | Notes |
|------|---------|-------|
| 100  | Trying | Hop-by-hop. Suppresses INVITE retransmissions. |
| 180  | Ringing | End-to-end. Callee alerting. |
| 181  | Call Is Being Forwarded | Optional. Indicates forwarding. |
| 183  | Session Progress | Early media. Contains SDP for early RTP. Requires PRACK if 100rel. |

### 2xx Success
| Code | Meaning | Notes |
|------|---------|-------|
| 200  | OK | Final success. For INVITE: must be ACKed. |
| 202  | Accepted | Used for REFER. Subscription implicitly created. |

### 3xx Redirection
| Code | Meaning | Notes |
|------|---------|-------|
| 301  | Moved Permanently | Target has moved. Update address. |
| 302  | Moved Temporarily | Used for call forwarding. Contains new Contact. |

### 4xx Client Errors
| Code | Meaning | Common Causes in Webex Calling |
|------|---------|-------------------------------|
| 400  | Bad Request | Malformed SIP message, invalid SDP. |
| 401  | Unauthorized | Authentication required. Check credentials. |
| 403  | Forbidden | User not authorized. Check entitlements in CPAPI. |
| 404  | Not Found | Destination not registered or unknown. Check WxCAS routing. |
| 407  | Proxy Auth Required | Proxy authentication needed. |
| 408  | Request Timeout | No response from destination within timer B (32s). Destination unreachable. |
| 415  | Unsupported Media | SDP codec mismatch. Check offered vs supported codecs. |
| 480  | Temporarily Unavailable | Destination offline or not reachable. Check registration status. |
| 481  | Call/Transaction Does Not Exist | BYE/ACK for unknown dialog. Possible state mismatch or race condition. |
| 486  | Busy Here | Callee busy. |
| 487  | Request Terminated | INVITE cancelled by caller (CANCEL sent before final response). |
| 488  | Not Acceptable Here | SDP negotiation failure. Offered codecs/media not acceptable. |
| 491  | Request Pending | Glare: simultaneous re-INVITEs. Retry after random delay. |

### 5xx Server Errors
| Code | Meaning | Common Causes in Webex Calling |
|------|---------|-------------------------------|
| 500  | Server Internal Error | Service crash or unhandled exception. Check SSE/WxCAS logs. |
| 502  | Bad Gateway | Upstream service failure. SSE couldn't reach WxCAS or destination. |
| 503  | Service Unavailable | Overloaded or in maintenance. Check health endpoints. |
| 504  | Server Timeout | Upstream response timeout. Check inter-service connectivity. |

### 6xx Global Errors
| Code | Meaning | Notes |
|------|---------|-------|
| 600  | Busy Everywhere | Callee busy on all devices. |
| 603  | Decline | Callee explicitly rejected the call. |
| 604  | Does Not Exist Anywhere | Number/URI not found globally. |

## 6. SDP Negotiation (Offer/Answer)

### Key SDP Fields to Check
- `v=` — Protocol version (always 0)
- `o=` — Session originator (username, session-id, version, address)
- `c=` — Connection info (IP address for media)
- `m=` — Media line: `m=audio <port> RTP/SAVPF <payload types>` or `m=video ...`
- `a=rtpmap:` — Codec mapping (e.g., `a=rtpmap:111 opus/48000/2`)
- `a=sendrecv` / `a=sendonly` / `a=recvonly` / `a=inactive` — Media direction
- `a=ice-ufrag` / `a=ice-pwd` — ICE credentials
- `a=candidate:` — ICE candidates (host, srflx, relay)
- `a=fingerprint:` — DTLS fingerprint for SRTP key exchange
- `a=setup:` — DTLS role (`actpass`, `active`, `passive`)

### Common SDP Issues
- **Codec mismatch**: Offer contains codecs not in answer → 488 or no media
- **Missing ICE candidates**: No relay candidates → can fail behind strict NAT/firewall
- **Port 0 in answer**: Media stream rejected by answerer
- **IP mismatch**: SDP `c=` address unreachable → one-way or no audio
- **Direction conflict**: Both sides `sendonly` → no bidirectional media

## 7. SIP Timers (RFC 3261)

| Timer | Default | Purpose |
|-------|---------|---------|
| T1 | 500ms | RTT estimate. Base for retransmission intervals. |
| T2 | 4s | Maximum retransmission interval for non-INVITE requests. |
| T4 | 5s | Maximum time a message remains in the network. |
| Timer A | Initially T1 | INVITE retransmission interval (doubles each retransmit). |
| Timer B | 64*T1 (32s) | INVITE transaction timeout. No response → 408. |
| Timer C | >3min | Proxy INVITE transaction timeout. |
| Timer D | >32s (UDP) | Wait time after INVITE client receives non-2xx. |
| Timer F | 64*T1 (32s) | Non-INVITE transaction timeout. |
| Timer H | 64*T1 (32s) | Wait time for ACK after sending non-2xx to INVITE. |

### Debugging with Timers
- **No 100 Trying within T1**: Possible network issue or destination down.
- **INVITE retransmissions (Timer A doubling)**: 500ms, 1s, 2s, 4s... indicates no response from next hop.
- **Timer B expiry (32s)**: No final response to INVITE. Results in 408 Request Timeout.
- **Missing ACK after 200 OK (Timer H)**: Dialog state leak. Possible NAT/firewall blocking ACK.

## 8. Common Failure Patterns

### One-Way Audio
- **Symptoms**: One party can hear, other cannot.
- **Check**: SDP `c=` addresses, ICE connectivity, NAT traversal, `a=sendrecv` direction, firewall rules on RTP ports.
- **In logs**: Look for ICE failure events, OODLE/media quality alerts, OOOOOOO (no media flowing).

### Call Drops After ~32 Seconds
- **Cause**: Timer B expiry — INVITE not answered.
- **Check**: Destination registration, SSE→WxCAS connectivity, WxCAS→destination routing.

### ooooo (No Audio) / oOOOOOo (Intermittent)
- **Check**: MSE logs for RTP packet counters, ICE state, DTLS handshake completion.

### Registration Failures
- **401/407 loops**: Authentication issues. Check credentials and nonce handling.
- **Keepalive failures**: 5 missed keepalives (30s interval) → unregistration. Check network stability.

### Call Setup Failures
- **Location Service Error 404**: User not registered on WxCAS. Check REGISTER flow.
- **488 Not Acceptable Here**: SDP mismatch. Compare offered vs required codecs.
- **Location Service Error 480**: User temporarily unavailable. Check device status.

### Ooooo (Ooh Pattern - Ooooo in SSE Logs)
- Periodic patterns of capital and lowercase letters in SSE logs represent media flow quality markers.
- All lowercase (`ooooo`) = no media detected.
- Capital letters = media packets detected in that interval.

## 9. SIP Dialog Correlation Across Services

To trace a single call across Mobius, SSE, and WxCAS logs:

1. **Call-ID**: Same across all services for a given dialog leg. Search all log sources with the same Call-ID.
2. **From-tag / To-tag**: Combined with Call-ID, uniquely identifies a dialog. Use to distinguish forked calls.
3. **CSeq**: Sequence number per method. Helps order messages within a dialog.
4. **Via branch**: Transaction identifier. Same branch = same transaction across hops.
5. **Tracking ID**: Webex-specific. Correlates browser session to SIP dialog. Found in Mobius logs and X-headers in SIP.

### Cross-Service Mapping
| Identifier | Mobius Logs | SSE/MSE Logs | WxCAS Logs |
|-----------|------------|-------------|-----------|
| Call-ID | `sipCallId` field | `Call-ID` header | `Call-ID` header |
| Tracking ID | `trackingId` field | X-Cisco-TrackingId header | X-Cisco-TrackingId header |
| Session ID | `sessionId` / `localSessionId` | Session-ID header | Session-ID header |
| Correlation ID | `correlationId` field | X-Cisco-CorrelationId | X-Cisco-CorrelationId |
