# Deye EMS — development guidance

Current Deye EMS release: **2.6.5**.

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
- Document non-obvious behavior as part of each code change. Explain why an invariant, safety check, ordering rule, or fallback exists where it is implemented. Keep affected comments and public documentation in sync with behavior, and avoid restating obvious code.
- For each release, keep the version in the README release label and repository layout description aligned with the integration manifest, and include it in the release commit title. Include the relevant version in commit titles that update the public file descriptions.

## Whole-repository consistency

Before closing any fix or release, review the complete public repository for affected references, including code comments, README in both languages, INSTALL, MIGRATION, SPECIFICATION, TARIFFS, VALIDATION, preview, tests, Marketplace metadata and release notes. Update every affected file in the same work and verify the result on GitHub. Preserve accurate files as they are.

For each release, check that the manifest, backend and panel version and registration, package, release notes, AGENTS.md version marker, visible documentation version labels and release commit title agree. Verify the checks, published tag and asset, and the version actually loaded on the production instance. Preserve compatibility, saved settings and source mappings, and retain a rollback path. Report anything still pending or unverified.

Keep the GitHub repository homepage current after every public change. Verify the rendered README in both languages and the visible release label. Keep the homepage focused on product behavior, installation and user-facing links. Keep release workflow details out of the project overview.

At each release, verify the explicit version on all four public repository-layout rows: custom_components/deye_ems, preview, release-notes, and tests. Verify the directory rows and current file descriptions on the GitHub homepage together.

For every public fix and release, review the full tree recursively, including file and directory descriptions visible on GitHub. Verify affected headings, version labels, links, code comments and last-change titles against the actual published state before reporting completion. Internal review belongs in the repository workflow, outside the user-facing homepage.

Review comments and docstrings recursively across all project files, including sources, tests, preview and automation. On each change, check affected explanations against the implemented behavior and update stale ones in the same commit. Comment where needed to explain reasoning, safety, ordering and compatibility. Do not add filler comments or comments to formats that do not support them.

Use MAJOR.MINOR.PATCH versioning for new releases without zero-padding. Bump MINOR and reset PATCH for backward-compatible, substantial engine changes. Use PATCH for smaller fixes. Preserve published tags and assets.
