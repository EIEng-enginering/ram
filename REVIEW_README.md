# Independent review entry point · 0.3.0.dev1

1. Verify file digests with `SHA256SUMS` (e.g. `sha256sum -c SHA256SUMS`, or Get-FileHash in PowerShell). The archive
   root is the intended project directory.
2. Read PROJECT_STATE.md, WORKPACK_STATUS.md, docs/DECISIONS.md, docs/METHODS_IMPLEMENTED.md (0.3 additions at the
   end), DEVIATIONS.md and CHANGELOG.md (method change, the defect found by CTMC verification, adapted tests).
3. Run the suite (USER_GUIDE.md) and keep the log. Linux evidence is in TEST_RESULTS; Windows evidence does not exist yet.
4. Independently check the known answers:
   - single repairable unit 90/10 → 0.9; series 0.9 × 0.8 → 0.72; parallel → 0.98; 2oo3 at 0.9 → 0.972;
   - standby CTMCs (tests/test_wp3_methods.py builds the generators independently);
   - periodic proof test with test downtime: U = 1 − (e^(−λd) − e^(−λτ))/(λτ);
   - exact 600 m³ / 6 h buffer cover → zero shortfall; two-buffer hand trace in test_wp2_physical;
   - utility reference case 0.949905 (docs/EXAMPLE_ONSHORE_UTILITY_REFERENCE.md).
   `python tools/verify_references.py` prints expected vs simulated with negative controls.
5. Legacy reproduction: tests/fixtures/alpha_0_2_reference_replays.json was produced by the untouched 0.2 source;
   `LegacyReproduction` replays it. `tools/benchmark_0_2_vs_0_3.sh` compares run times on the same host.
6. Report agreement: `python tools/verify_reports.py examples` checks status, run, method and every metric mean
   across JSON/XLSX/DOCX/PDF.
7. AI: inspect tests/test_wp5_ai_intake.py. No live provider result is included; the live test is skipped as BLOCKED.
