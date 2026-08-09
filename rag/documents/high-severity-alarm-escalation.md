---
doc_id: high-severity-alarm-escalation
title: High-Severity Alarm — Site Escalation Procedure
source_type: escalation
asset_class: site
severity: critical
version: 1.0
last_updated: 2026-07-15
tags: [escalation, alarm, critical, shift-supervisor, ops-manager]
---

# High-Severity Alarm — Site Escalation Procedure

## 1. Purpose

Defines the escalation path for any alarm tagged "critical" or
"high" in the alarm-management system. Applies to operators,
shift supervisors, and the on-call engineering rota.

## 2. When to escalate

A "critical" alarm is escalated within 5 minutes of the alarm
firing, regardless of clock time. A "high" alarm is escalated
within 15 minutes if the operator has not yet acknowledged and
actuated on the alarm.

## 3. Escalation chain

The escalation chain is ordered by latency. A higher tier
automatically receives the page if the lower tier fails to
acknowledge within the documented latency.

1. **Operator on shift.** The first tier. Always pages first.
2. **Shift supervisor.** Pages if the operator has not
   acknowledged within 90 seconds.
3. **Ops manager.** Pages if the shift supervisor has not
   acknowledged within 3 minutes.
4. **Site manager.** Pages if the ops manager has not
   acknowledged within 5 minutes.
5. **On-call engineering rota.** Pages if the alarm is
   unresolved after 15 minutes.

## 4. Acknowledgement vs. resolution

Acknowledging the alarm silences the audible and the page
chain. Resolution is the action that removes the underlying
condition. The acknowledgement is not the resolution. Both
must be logged.

## 5. Communication

Each page should include:

- The alarm tag and the priority.
- The asset class.
- The current value vs. the alarm setpoint.
- The last-known operator action.

## 6. After-hours

After-hours, the chain is identical. The on-call rotation
covers tier 5. The shift supervisor's mobile is the primary
contact for tier 3.

## 7. Site-wide critical alarms

A site-wide critical alarm (e.g., fire, loss of main power,
loss of instrument air) pages all on-duty operators at the
same time. The site-wide chain is documented in the
emergency-response plan and is not part of this procedure.

## 8. Operator note

This document describes the *escalation* procedure.
It does not describe the *technical* response — that lives
in the asset-specific operating procedure (see the
troubleshooting and SOP documents in this knowledge base).

## 9. Examples

- **Example 1.** A high-pressure boiler trip fires a
  critical alarm. The operator on shift acknowledges within 30
  seconds. The shift supervisor arrives at the unit within 4
  minutes and takes charge. The escalation chain does not
  proceed past tier 2.
- **Example 2.** A compressor surge alarm fires at 02:00
  local time. The operator does not acknowledge within 90
  seconds. The shift supervisor's page goes out. The shift
  supervisor acknowledges from her mobile and arrives at the
  unit within 10 minutes. The escalation chain proceeds to
  tier 2 only.
- **Example 3.** A cooling-water header pressure drop fires
  a critical alarm. The shift supervisor is on the floor
  and acknowledges within 30 seconds. The ops manager
  receives the page but does not need to escalate further
  because the unit is stabilised.

## 10. Disclaimer

This document does not override the binding site emergency
response plan. When this procedure and the emergency
response plan conflict, follow the emergency response plan.
