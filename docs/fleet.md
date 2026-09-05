# Legion Fleet hierarchy

LEGION is the central command-and-control system. It manages policy, assignments,
communications, monitoring, alerting, coordination, and audit records across the Fleet.

## Terms

| Term | Meaning |
|---|---|
| LEGION | Central management plane (`legionctl` + optional local HUD). |
| Fleet | All Sentinel assets enrolled in Legion. |
| Zone | Physical, logical, or mission coverage area. Stable `zone_id`, editable name. |
| Cohort | Operational unit targeting five Sentinels for a Zone. May be understrength, nominal, or reinforced. |
| Primus | Transferable lead-Sentinel *designation* inside a Cohort. Not mesh routing or telemetry aggregation. |
| Sentinel | Individual asset. Today: RF/SOI sensor nodes. |
| Group | Ad hoc CLI label for targeting. **Not** a Cohort. |

## Readiness

Cohort readiness is derived, not stored:

- **nominal**: 5 active members and a Primus assigned
- **understrength**: fewer than 5 active members
- **reinforced**: more than 5 active members
- **degraded**: Primus missing or Primus offline/degraded
- **unassigned**: active Cohort has no Zone
- **inactive**: Cohort withdrawn

Zone coverage: unstaffed, partial, covered, degraded, or inactive.

## Storage

Zones and Cohorts live in `inventory.json` alongside Sentinels and groups.
Existing inventories load with empty `zones` and `cohorts` lists.
Credentials stay in the keyring; they are never copied into Zone/Cohort records.
Assignment changes do not deploy SOI profiles.
