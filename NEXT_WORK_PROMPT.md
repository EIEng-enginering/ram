# Next execution prompt · RAM Model after 0.3.0.dev1

Use the 0.3.0.dev1 package root as the project. Read PROJECT_STATE.md, WORKPACK_STATUS.md, DEVIATIONS.md, CHANGELOG.md
and docs/METHODS_IMPLEMENTED.md first. Do not commit, push or publish without separate authorisation. Never ask for an
API key in chat. Preserve all existing tests and the 0.2 legacy reproduction fixture. Any method, RNG or event-order
change needs a new method version and a separate reference check.

1. **Windows acceptance (first).** On a clean Windows machine with Python 3.12, extract to
   `C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\30 RAM` (or a path with
   spaces, `&` and Unicode), run `.\setup.ps1`, then the suite with Tee-Object to `TEST_RESULTS\WINDOWS_0_3.txt`.
   Launch `.\run.ps1 -Case '.\examples\Offshore_Production\Migrated_From_Alpha_0.2.ramcase'` and exercise import,
   Model editor edit/undo/save, simulation, Decisions preview/approve, named model/run approvals and all four exports.
   Run `tools\verify_reports.py` on the exported folder. Record OS build, Python and package versions and times.
2. **Instruction differences.** Compare the requester's separately attached instruction file (not readable in the
   0.3.0.dev1 pass) with WORKPACK_STATUS.md and implement any difference.
3. **Independent verification.** Have an engineer check docs/EXAMPLE_ONSHORE_UTILITY_REFERENCE.md, the CTMC and
   periodic-test references, and the deferral classification rule. Record the outcome in TEST_RESULTS.
4. **External adapters.** With an authorised P&ID Reader export sample, map its contract and add fixtures; map DEXPI
   only against an official version with representative fixtures; add OCR for scanned drawings. Until then keep them
   marked unverified.
5. **Live provider.** Only with authorised access entered outside chat: run the synthetic reference projects (ambiguous
   P&IDs, contradictory documents) and record each as passed/failed/blocked.
6. **Open features.** Mapping editor UI, free-form canvas and graphical nested RBD, separate drawing of parallel edges,
   multi-product flow, global sensitivity, rare-event methods.
7. Rebuild `RAM_MODEL_COMPLETION_HANDOVER_<version>.zip` from a clean staging directory and verify it against
   SHA256SUMS. Label it a release candidate only when items 1–3 are complete.
