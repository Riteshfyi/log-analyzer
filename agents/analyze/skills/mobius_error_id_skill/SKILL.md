---
name: mobius-error-id-skill
description: Interpret Mobius error and call IDs from logs using the reference documentation.
---

# Mobius Error ID Lookup

When analyzing Mobius logs, use this skill to interpret error IDs and call-related identifiers.

## Instructions

1. **Identify Mobius error IDs and call IDs** in the logs you are analyzing (e.g. from `mobius_logs`, or any field containing Mobius error codes, call IDs, or tracking identifiers that map to known error semantics).

2. **Consult the reference document** `references/mobius_error_ids.md` to look up each such ID. That document contains the authoritative mapping of Mobius error/call IDs to their meanings, causes, and remediation notes.

3. **Include the interpretation in your analysis:**
   - In **Error Detection and Root Cause Analysis**: For each Mobius error ID found, state what the ID means (from the reference), likely cause, and suggested fix.
   - In **Root Cause Analysis** (if applicable): Reference the documentation so your explanation is consistent with the defined semantics of each ID.

4. If an ID is not present in the reference document, say so and describe the ID and context so a human can triage or update the documentation.
