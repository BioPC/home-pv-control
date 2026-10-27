# Initial real-HA findings

Commit a95da1627196a4e3a875802b0a8d018469976a6a, run 40552483545.

- Both Linux jobs passed the 70 dependency-free foundation tests.
- HA 2026.10.4: real suite 3 passed, 3 failed. Two tests tried to patch a slotted ServiceRegistry instance, which is read-only. The trap now patches its class, preserving the same no-service-call assertion. The third test assumed runtime_data remains an attribute after HA unload; HA deletes it. The same absence-of-runtime assertion now accepts removal or None. Independent owner/listener/task cleanup assertions remain unchanged.
- HA 2025.12.0: dependency import failed before collecting real tests. aiodns 3.5.0 resolved pycares 5.2.1, which lacks ares_query_a_result. Pin pycares 4.11.0 (a release predating HA 2025.12.0) in the minimum test environment. Do not change HA or integration policy.

No native production source has been changed in response to this first run. Eight additional acceptance cases cover discovery, exact/stable unique IDs, user rename, listener/timer cleanup, corrupt/missing ledger, partial legacy detection and malformed import.
