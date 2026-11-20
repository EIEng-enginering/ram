# Requirements traceability · 0.3.0.dev1 (development checkpoint)

Test modules: test_storage, test_engines, test_workflow (0.2, retained), test_wp1_data, test_wp2_physical,
test_wp2_desktop, test_wp3_methods, test_wp4_decisions, test_wp5_ai_intake, test_wp6_examples.
Linux evidence: TEST_RESULTS/WP6_CHECKPOINT_LINUX.txt (82 tests: 81 pass, 1 BLOCKED skip). Windows: PENDING.

| ID | Requirement | Implementation | Evidence | Open |
|---|---|---|---|---|
| RAM-01 | Evidence, units, provenance, mapping, migration, exchange | storage.py, 003_provenance.sql, units.py, mapping.py, exchange.py, observations.py | test_storage, test_workflow, test_wp1_data | mapping editor UI |
| RAM-02 | RBD, flow, dependencies, priorities, yields, recycles, validation | flow.py, analytics.py, simulation.py | test_engines, test_wp2_physical, REFERENCE_VERIFICATION.txt | multi-product |
| RAM-03 | Buffers (several) and constrained repair | flow.py, simulation.py | test_two_buffer_conservation_and_hand_trace, test_initial_inventory_at_both_limits, test_exact_six_hour_cover_retained, crew queue tests | – |
| RAM-04 | Analytical references | analytics.py, tests | test_engines, test_wp3_methods (CTMC, NHPP, periodic test, β-factor) | – |
| RAM-05 | Seeded simulation, method versions, diagnostics | simulation.py, study.py | LegacyReproduction, test_zero_event_run_is_not_zero_risk, REPEATABILITY.txt | rare-event acceleration |
| RAM-06 | Volume, loss classes, periods, economics, balance | simulation.py, reporting.py | test_wp3_methods, test_wp6_examples | – |
| RAM-07 | Attribution, options, sensitivity, uncertainty | decision.py, study.py, ui.py Decisions | test_wp4_decisions | global sensitivity |
| RAM-08 | Evidence intake and AI workflow | intake.py, assistant.py, engineering_import.py | test_ai_output_boundaries, test_wp5_ai_intake | OCR, DEXPI, P&ID Reader (BLOCKED), live provider (BLOCKED) |
| RAM-09 | Model views, editing and replay | editing.py, ui.py | test_wp2_physical editing tests, test_wp2_desktop, screenshots | Windows GUI acceptance |
| RAM-10 | Four formats, review state, separate approvals | reporting.py | test_workflow, tools/verify_reports.py, REPORT_AGREEMENT.txt | engineering layout review |
| RAM-11 | Offshore, onshore and utility reference examples | example.py, cli.py | test_wp6_examples, examples/, docs/EXAMPLE_*.md | independent industrial benchmark |
| RAM-12 | Windows launch and return ZIP | setup.ps1, run.ps1, tools/build_pack.py | manifested ZIP, Linux logs | native Windows acceptance |
