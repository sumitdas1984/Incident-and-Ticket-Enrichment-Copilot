---
doc_id: incident-2025-03-14-resolver-notes
title: Incident 2025-03-14 — High-Pressure Boiler Tube Leak, Resolver Notes
source_type: resolution_note
asset_class: boiler
severity: critical
version: 1.0
last_updated: 2025-03-20
tags: [boiler, leak, incident, postmortem, economiser]
---

# Incident 2025-03-14 — High-Pressure Boiler Tube Leak, Resolver Notes

> **Note for readers.** This is a synthetic past-incident
> reconstruction. Names, dates, and specific numbers are
> illustrative.

## 1. Summary

On 2025-03-14 at 04:18 local time, high-pressure boiler HP-201
tripped on a confirmed tube leak. The leak was located on the
gas-side of the economiser, tube 14 row 3. The unit was off-line
for 38 hours. Operationally the recovery was clean; the root
cause was traced to sootblower coverage gaps at the economiser
inlet.

## 2. Timeline

| Time | Event |
|---|---|
| 04:18 | Conductivity trip on the continuous-blowdown line. |
| 04:19 | Operator confirmed drum-level drop. Tripped FD/ID fans. |
| 04:21 | Shift supervisor on the floor. |
| 04:34 | Audible hiss localised to the economiser inlet. |
| 05:02 | Casing opened. Visible leak confirmed on tube 14. |
| 06:11 | Affected tube plugged. Make-up water checked. |
| 07:00 | Casing closed. Leak test on the seal-welds. |
| 09:45 | Unit on bars. Combustion trial. |
| 18:30 | Unit at full load. |

## 3. Root cause

The economiser had not been cleaned by sootblower lane 3 for
26 hours preceding the trip. The sootblower controller had
faulted on a stuck-poppet indication. The soot accumulated on
the gas-side of the tubes, dropping the local metal temperature
below the dew-point of the flue gas. Sulphuric acid
condensation followed, and the gas-side corrosion penetrated
the tube wall of row 3.

## 4. Why the sootblower lane faulted

The poppet indicator on lane 3 had been replaced during the
last outage but the limit-switch wiring was reversed. The
controller saw the poppet "open" when it was in fact "closed"
and vice versa. The fault code generated was a soft fault and
was not acted on.

## 5. Corrective actions

1. **Reverse and re-test the lane-3 limit-switch wiring** before
   the next startup.
2. **Add a hard alarm** on the sootblower poppet-fault code so
   that future soft faults require operator acknowledgement.
3. **Walk the sootblower coverage** for all four lanes;
   specifically, add a coverage-overlap check at the economiser
   inlet.
4. **Schedule a tube-bundle inspection** of the economiser
   inlet within the next 21 days.
5. **Update the boiler operating procedure** to include a
   daily check of the sootblower fault log.

## 6. Lessons learned

- **Soft faults are silent failures.** A fault that the
  controller does not act on is invisible at the operator
  console. Every soft fault needs an explicit escalation
  policy.
- **Coverage overlap is not optional.** A single missed lane
  can breach the dew-point envelope on adjacent tubes within
  24 hours.
- **Trip-fast wins.** Tripping on the conductivity trip, not
  waiting for a flame failure, saved the casing from
  escalation.

## 7. What worked well

- The shift team recognised the leak within 60 seconds of the
  first instrument trip.
- The local isolate valves on the economiser section worked
  as designed.
- The standby tube-plug crew was on the floor within 90
  minutes of the trip.

## 8. What we would change

- The DCS should have a hard alarm on sootblower-poppet soft
  faults. Adding this is in the corrective-action list.
- The boiler-area inspection routine should include a
  daily-walk of the local isolate valves to confirm they
  have not been left in an unsafe position by other work.

## 9. References

- `boiler-tube-leak-troubleshooting.md` — diagnostic steps.
- `high-severity-alarm-escalation.md` — escalation policy.
