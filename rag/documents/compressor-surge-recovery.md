---
doc_id: compressor-surge-recovery
title: Centrifugal Compressor Surge — Recovery Procedure
source_type: procedure
asset_class: compressor
severity: high
version: 1.0
last_updated: 2026-06-15
tags: [compressor, surge, anti-surge, recycle, trip]
---

# Centrifugal Compressor Surge — Recovery Procedure

## 1. Definition

Surge is a violent, low-frequency oscillation of flow through a
centrifugal compressor, most often when the operating point falls
to the left of the surge line on the compressor map. Each surge
cycle can drive bearing temperatures up by 30 °C in seconds and
mechanically fatigue the rotor.

## 2. Indications

- Audible low-frequency "boom" from the compressor casing.
- Anti-surge valve (ASV) position swings between 0 and 100 % over
  1–2 second cycles.
- Discharge pressure oscillates by more than 10 % of setpoint.
- Discharge temperature rises sharply.
- Bearing vibration spikes above the alarm threshold (typically
  7.1 mm/s RMS).

## 3. Immediate recovery (within 30 seconds)

1. **Open the anti-surge valve to 100 %** if the controller has
   not already done so. Manual override is required when the
   controller is in fault.
2. **Reduce compressor suction pressure** if the upstream process
   allows. Lowering suction shifts the operating point to the
   right of the surge line.
3. **Hold the recycle valve open** until the discharge pressure
   has stabilised for at least 60 seconds.
4. **Trip the compressor** if the surge continues for more than
   30 seconds despite ASV open. Continued surge under load
   destroys bearings and seals.

## 4. Root cause hunt

Surge is a symptom, not a cause. After stabilising the unit, log
the event and walk the following checklist:

- **Process side.** Has the suction flow changed? Is there a
  recently closed bypass or a tripped upstream pump?
- **Anti-surge controller.** Are the controller setpoint and the
  controller mode (auto / manual) correct? A controller in
  manual with the wrong position is the most common cause of
  repetitive surge.
- **Mechanical.** Has the impeller been recently cleaned or
  rebuilt? A newly polished impeller moves the surge line to
  the right and may require a fresh performance test before
  bringing the unit back to nameplate flow.
- **Instrumentation.** Check the ASV position feedback, the
  flow transmitter, and the discharge pressure transmitter for
  pluggage or drift.

## 5. Returning to service

After the unit has been stable for 30 minutes:

1. Slowly close the ASV back to the controller's auto-output
   position. Watch for any oscillation.
2. Re-engage the controller in automatic.
3. Ramp the discharge pressure up to setpoint in 5 % steps, with
   a 60-second dwell between steps.
4. Re-baseline the bearing vibration and discharge temperature
   once at setpoint.

## 6. Documentation

Open an incident ticket at the end of the event covering: time
of surge, controllers mode at time of event, root cause
hypothesis, corrective action taken, and which operating-procedure
section was followed. Attach the DCS event log dump.

## 7. Common operator mistakes

- **Closing the ASV too early.** A 30-second dwell at the
  anti-surge end-stop is the minimum; 5 minutes is safer.
- **Trending the wrong channel.** The flow signal lags pressure
  by 1–2 seconds; trust the ASV position when they disagree.
- **Forgetting the recycle.** Recycle is the steady-state
  backup for ASV; both should be in service.
