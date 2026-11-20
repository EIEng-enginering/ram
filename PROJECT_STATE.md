# Project state · 20 November 2026 (AWST) · 0.3.0.dev1 development checkpoint

0.3.0.dev1 completes the WP0–WP6 implementation pass of GROK_MASTER_PROMPT.md on a Linux build host. Calculation
method **rammodel-des-0.3**; models without 0.3 features reproduce 0.2 alpha bit-for-bit. Case schema 3 (0.2 cases
migrate on open). See WORKPACK_STATUS.md for DONE/PARTIAL/OPEN/BLOCKED per item, CHANGELOG.md for method changes and
historical failures, DEVIATIONS.md for open scope, and NEXT_WORK_PROMPT.md for the next execution.

Label: **development checkpoint**, not a release candidate, because:
- native Windows acceptance has not been run (PENDING);
- no live AI provider was evaluated (BLOCKED: no authorised credentials);
- direct P&ID Reader integration is unverified (BLOCKED: no authorised sample); DEXPI and OCR are OPEN;
- independent engineering verification of the methods and examples is OPEN.

Linux test result: 82 tests, 81 passed, 1 skipped as BLOCKED (live provider), 0 failed (Python 3.12.16, PySide6
6.12.0, offscreen Qt). The Windows destination
`C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\30 RAM` was not reachable;
the package was **not** copied there.

The separately attached instruction file could not be read during this pass; the in-package GROK_MASTER_PROMPT.md was
followed. No Git commit or push has been made. Nothing was published. No API key was used or stored.
