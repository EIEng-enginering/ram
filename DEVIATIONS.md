# Scope, deviations and open qualifications · 0.3.0.dev1 development checkpoint

## Deviations from the execution instructions

| Item | Deviation | Reason / consequence |
|---|---|---|
| Instruction file | The requester attached a separate instruction file said to differ slightly from GROK_MASTER_PROMPT.md. It could not be read by the executing agent. | Work followed the in-package GROK_MASTER_PROMPT.md. Any differences in the attached file are **not applied**; check them against WORKPACK_STATUS.md. |
| Windows target folder | Not reachable from the Linux build host. | Nothing was copied there. Package root is the install directory. Windows native tests PENDING. |
| Release label | Development checkpoint, not release candidate. | Windows acceptance, live provider, P&ID Reader integration and independent verification are open. |
| Two existing tests adapted | test_storage (version constant) and test_workflow (extra run approval). | See CHANGELOG.md; intent preserved, nothing deleted or weakened. |
| Package version | 0.3.0.dev1 with method rammodel-des-0.3. | The 0.2 profile reproduces bit-identically for models without 0.3 features. |

## Capability status after this pass

| Area | Delivered in 0.3.0.dev1 | Still open |
|---|---|---|
| Data (M1) | Units catalogue and canonical conversion, configurable CSV/XLSX mappings with preview and atomic rollback, value basis and applicability, import batches, observations and approved rate estimates, schema 3 migration, revision history | Mapping editor UI (mappings are JSON files); reviewer workflow UI for observations |
| Graph (M2) | Model editor tab (property forms, connect mode, undo/redo, change list, audit, baseline confirmation), priorities, several buffers, yields, declared recycles, explicit rejection of unsupported topologies | Multi-product flow; free-form drag-and-drop canvas and graphical nested-RBD drawing; parallel edges between the same two nodes are drawn on top of each other |
| Analytical (M3) | Exact periodic hidden failure with test downtime; references for standby CTMC, NHPP minimal repair, beta-factor CCF | Wider analytical coverage (e.g. imperfect proof tests) |
| Simulation (M4) | Operating clocks, restoration rules, exponential repair, CCF, standby groups with start failures, weather policies, schedules, calendar periods, deferral, economics, balance and diagnostics | Rare-event acceleration; correlated parameter uncertainty |
| Options (M5) | Decisions tab: paired comparisons with validity notes, tornado, input-uncertainty ranking | Many-variable global sensitivity |
| AI (M6) | Off by default; text and text-layer PDF intake; schema-validated actions with basis; robust provider error handling; credential isolation tests (mocked) | OCR for scanned drawings; DEXPI mapping; direct P&ID Reader contract (BLOCKED, no authorised sample); live provider qualification (BLOCKED, no authorised credentials) |
| Reports (M7) | Method profile, bases, stop reason, diagnostics, balance, economics basis, periods sheet, tornado, counterfactual gains, separate approvals, narrative edit history; automated four-format agreement check | Engineering and client review of layouts and legends |
| Examples (M8) | Offshore (preserved), migrated alpha copy, onshore 0.3 example, independent utility reference case | Independent industrial benchmark; representative real project acceptance |
| Distribution | setup.ps1/run.ps1 unchanged in behaviour; Linux tests, benchmark and repeatability evidence | Native Windows acceptance; independent engineering review |

Standards are cited for context only (ISO 20815:2026, ISO 14224:2016, IEC 61078:2016, IEC 61165:2006). No conformity or certification is claimed.
