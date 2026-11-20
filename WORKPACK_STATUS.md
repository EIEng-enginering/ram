# Workpack status · RAM Model 0.3.0.dev1 · DEVELOPMENT CHECKPOINT

Executed 20 November 2026 (AWST, UTC+8) on a Linux build host: Python 3.12.16, PySide6 6.12.0, Qt offscreen
(full list in TEST_RESULTS/ENVIRONMENT_LINUX.txt). The Windows destination folder was **not reachable** and nothing
was copied there. Windows native acceptance is **PENDING (not run, not passed)**. No live AI provider was used.

Instruction basis: the in-package GROK_MASTER_PROMPT.md. The separately attached instruction file, which the requester
said differs slightly, **could not be read** by the executing agent (it was not accessible), so any differences
between it and GROK_MASTER_PROMPT.md have not been applied. See DEVIATIONS.md.

Status: DONE = implemented and tested here. PARTIAL = part implemented, rest open. OPEN = not done.
BLOCKED = needs an external fixture, credential or host that was not available.

Final suite (Linux): **82 tests, 81 passed, 1 skipped as BLOCKED, 0 failed** (TEST_RESULTS/WP6_CHECKPOINT_LINUX.txt).
The 20 original 0.2 tests are all retained; two were adapted, with the reasons recorded in CHANGELOG.md.

| WP | Item | Status | Code | Tests / evidence | Notes |
|---|---|---|---|---|---|
| WP0 | SHA256SUMS verified (66/66) | DONE | – | TEST_RESULTS/WP0_BASELINE_ORIGINAL_0_2_LINUX.txt | pristine copy kept unmodified |
| WP0 | Untouched suite | DONE | – | 20/20 pass, Python 3.12.16 | matches handover count |
| WP0 | Offshore reference, 1,000 reps, seed 42 | DONE | cli.demo | 99.264246 %; three trains +0.676380 pp; larger tank +0.539137 pp; single train −0.540236 pp | identical to bundled Run_Comparisons.json |
| WP1 | Units catalogue, canonical conversion, cross-dimension rejection, ambiguous units rejected | DONE | units.py | test_wp1_data.Units | year = 8760 h; "month" and "m" refused |
| WP1 | Originals (value, unit, row/cell, document, revision, applicability) and value basis (stated/inferred/estimated/synthetic) | DONE | 003_provenance.sql, mapping.py, exchange.py | test_wp1_data | basis stored in side table mode_value_meta |
| WP1 | Operating vs calendar exposure kept separate | DONE | units.convert_exposure, simulation | test_exposure_bases_never_mixed_implicitly, WP3 clocks | utilisation must be explicit |
| WP1 | Blank vs zero vs invalid, mixed units, duplicates, row-specific preview, atomic import and rollback | DONE | mapping.py | test_preview_row_errors_mixed_units_blank_and_zero, test_failed_batch_rolls_back_everything | CSV/XLSX mapping schema rammodel-mapping-1 |
| WP1 | Rate estimate only from accepted, documented observations with exposure and chi-square bounds | DONE | observations.py | test_rate_estimate_from_accepted_observations_only | refuses zero-event point estimates |
| WP1 | Migration 003, alpha case copy migrated without losing its run, newer schema rejected, revision history | DONE | storage.py, study.py | test_migrate_alpha_case_copy_without_losing_run, test_storage | examples/Offshore_Production/Migrated_From_Alpha_0.2.ramcase |
| WP1 | Run reproducibility record (model, library hash, code, RNG scheme, environment, method profile) | DONE | study.calculate/save_run | test_wp3 / reports | |
| WP2 | Graphical editing: object list, property form, connect mode, delete, undo/redo, change list, shared selection, audit on save, baseline confirmation | DONE (Linux offscreen) | editing.py, ui.py "Model editor" | test_edit_undo_redo_reload_and_audit, test_approved_baseline_requires_confirmation, test_wp2_desktop | drag-and-drop node layout and nested-RBD drawing canvas remain basic; Windows GUI acceptance PENDING |
| WP2 | Routing priorities, multiple buffers, edge yield losses, declared recycles, rejection of unsupported topologies (multi-product, undeclared cycles) | DONE | flow.py | test_wp2_physical | multi-product: explicitly rejected (OPEN as a feature) |
| WP2 | Hand checks: series/parallel/nested/k-of-n, reroute, shared utility, two-buffer hand trace, inventory limits, 600 m³ / 6 h fixture | DONE | – | test_wp2_physical, TEST_RESULTS/REFERENCE_VERIFICATION.txt | |
| WP3 | Operating/calendar clocks, idle factor, as-good-as-new / as-bad-as-old, exponential repair, hidden-failure test downtime, initial age | DONE | simulation.py | test_wp3_methods | |
| WP3 | Common-cause shocks (beta factor or deterministic times) | DONE | simulation.py | test_common_cause_beta_factor, test_deterministic_common_cause_outage | calibration by documented beta; no generic data shipped |
| WP3 | Explicit standby groups with start-on-demand failures, shared crews/spares; legacy dedicated-channel standby_pair retained | DONE | simulation.py | CTMC comparisons (5 settings) | |
| WP3 | Demand/feed/capacity schedules, calendar months/years, lost/deferred/recovered classification, economics, no-failure vs contractual vs delivered | DONE | simulation.py, study.py | test_wp3_methods | |
| WP3 | Weather policies (continue/suspend), simultaneous events, crew queues, zero-demand periods, incomplete inputs, whole-case and per-period conservation | DONE | simulation.py | test_wp3_methods | |
| WP3 | Legacy 0.2 profile bit-identical | DONE | – | LegacyReproduction (240 fixed replays), REPEATABILITY.txt | |
| WP4 | Paired option comparison, matched-stream validity notes, significance, adjacent distinguishability | DONE | decision.py, ui.py "Decisions" | test_wp4_decisions | |
| WP4 | Tornado with source links, input-uncertainty ranking (probability best, ranking changes), uncertainty kinds labelled | DONE | decision.py, reporting.py | test_wp4_decisions | |
| WP4 | Diagnostics: zero-event rule of three, rare events, zero variance, stop reason | DONE | simulation.diagnostics | test_zero_event_run_is_not_zero_risk | |
| WP4 | Counterfactual gains reported separately from coincident loss groups | DONE | reporting.py | report sections | |
| WP5 | AI off by default, manual workflow intact | DONE | ui.py, assistant.py | test_ai_off_by_default_and_manual_path | |
| WP5 | Text/Markdown/CSV and text-layer PDF intake with locators; scanned pages flagged needs_ocr | PARTIAL | intake.py | test_wp5_ai_intake.Intake | OCR of scanned drawings OPEN |
| WP5 | DEXPI mapping | OPEN | intake.py reports "unsupported" | test | needs official version and representative fixtures |
| WP5 | Direct P&ID Reader integration | BLOCKED | engineering_import.py (neutral adapter only) | – | no authorised reader export sample; direct integration unverified |
| WP5 | Schema-validated actions, basis stated/inferred, malformed output, timeouts, connectivity loss, invented numbers, cross-case citations, credential isolation, document instructions as data | DONE (mocked provider) | assistant.py | test_wp5_ai_intake.Provider | |
| WP5 | Separate named model, run and narrative approvals for final export; narrative edit history; stale blocking | DONE | reporting.py | test_workflow, test_wp5 | |
| WP5 | Live provider evaluation | BLOCKED | – | skipped test (BLOCKED) | no authorised credentials; never claimed passed |
| WP6 | Offshore case preserved and regenerated; onshore example; independent utility reference case | DONE | example.py, cli.py | test_wp6_examples, examples/*, docs/EXAMPLE_*.md | |
| WP6 | Report content agreement JSON/XLSX/DOCX/PDF, with negative control | DONE | tools/verify_reports.py | TEST_RESULTS/REPORT_AGREEMENT.txt | readable legends/page layout: visual spot check only, engineering review OPEN |
| WP6 | Paths with spaces, ampersand, Unicode; alpha case upgrade | DONE (Linux) | – | test_wp6_examples, test_wp5, test_wp1_data | exact Windows destination path PENDING |
| WP6 | Repeatability and benchmark (same host) | DONE | tools/benchmark_0_2_vs_0_3.sh | REPEATABILITY.txt, BENCHMARK_0_2_vs_0_3.txt | 0.3 ≈ 18.6 % slower on the legacy demo |
| WP6 | Screenshots | DONE | tools/capture_example.py | examples/*/*.png | offscreen Qt render |
| WP6 | Clean native Windows Python 3.12 setup, launch, import, edit, simulate, approve, export | PENDING (BLOCKED) | setup.ps1, run.ps1 | – | no Windows host available |
| WP6 | Independent engineering verification of methods and examples | OPEN | – | – | required before any release-candidate label |
| WP6 | Handover ZIP from clean staging, verified against manifest | DONE | tools/build_pack.py | build log in final report | |
