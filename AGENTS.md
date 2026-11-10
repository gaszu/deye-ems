# Deye EMS — development guidance

- Maintain an independently installable Home Assistant custom integration with a local engine. Runtime must not depend on EMHASS, auxiliary helpers or user automations.
- Preserve the engine contract documented in SPECIFICATION.md. Treat source mappings, safety settings, capacity and power ratings as private configuration. Do not change live settings as part of interface work.
- Start new installations in observation mode. Source changes require observation; resuming control must be explicit and require current valid inputs and a current plan. Never automatically disable another controller.
- Preserve ownership checks, BMS restrictions, actual grid limits, telemetry freshness and fail-closed behavior. Distinguish a calculation, a service attempt, register readback and physical response.
- Use total LOAD once. Optional receiver channels model the SoC forecast; do not add their energy or power a second time to total demand.
- Keep slow forecast and history requests outside the immediate control path. Preserve durable request accounting across restarts and configuration changes.
- Keep credentials in Home Assistant configuration. Never expose stored keys through status, diagnostics, plans, cache, logs or public files. A newly entered wizard key may exist only in transient form memory; clear it on completion, cancellation or disconnect.
- Use the native Home Assistant options flow for Solcast configuration. Opening or cancelling a wizard must not change the forecast source. Saving and disabling require explicit actions; do not prefetch a step that performs a write.
- Keep the interface simple, with muted pastel colors derived from the current HA theme and readable text and focus states in light and dark modes.
- Public documentation describes product behavior and synthetic validation. Keep deployment records, personal configuration, household telemetry and private audits outside the repository.
- Run meaningful checks for changed behavior. Build the standalone ZIP with build_release.py and verify published sources against the tested files. Describe publication and live deployment separately.
