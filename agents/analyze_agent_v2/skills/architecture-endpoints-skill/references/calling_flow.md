# WebRTC Calling — End-to-End Architecture

**Signaling Path**: Browser → Mobius (HTTP/WSS→SIP translation) → SSE (SIP edge) → WxCAS (Application Server) → Destination

**Media Path**: Browser ↔ MSE (DTLS-SRTP) ↔ Destination

**Call Types & Routing:**

- **WebRTC to WebRTC**: WxCAS resolves destination browser → Mobius notifies Browser 2 → Both browsers establish DTLS-SRTP with their local MSE.
- **WebRTC to PSTN**: WxCAS resolves PSTN destination → SSE signals toward Local Gateway → Browser↔MSE1 (DTLS-SRTP), MSE1↔MSE2 (RTP), MSE2→LGW (RTP→PSTN).
- **WebRTC to Desk Phone**: WxCAS resolves desk phone → SSE coordinates with MSE → Browser↔MSE1 (DTLS-SRTP), MSE1↔MSE2 (RTP), MSE2→Desk Phone.
