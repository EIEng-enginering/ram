# Decisions · Revision B

## Approved by the owner

| ID | Decision | Baseline |
|---|---|---|
| D01 | Time and metrics | Calendar hours. Monthly, annual and whole-horizon summaries. Include planned outages, show nominal production denominator and report equipment operational availability separately. |
| D02 | Failure and restoration | Exponential failure unless a supported distribution is selected. Fixed logistics, mobilisation and active repair in the base case unless explicitly overridden. Independent failures unless a dependency is explicitly modelled. |
| D03 | Flow and storage | Explicit capacity, routes and splits. Proportional routing only when specified. Track capacity, initial inventory and rates. Apply buffer limits to delivered production. |
| D04 | Simulation reporting | Seeded replications, P10/P50/P90, 95% mean CI, begin at 1,000 and expand up to 100,000, warn above 1% relative mean CI half-width at the cap. |
| D05 | AI and exports | AI off by default, pluggable, manual operation available. AI drafts reviewed before final reports, no invented reliability values, EXAMPLE labelling, JSON/XLSX/DOCX/PDF exports. |

## AI and model workflow approved by the owner

Approved on 20 November 2026 (Perth). These decisions resolve and expand the four benchmark proposals.

| ID | Decision | Approved baseline |
|---|---|---|
| D06 | Input sequence | Begin with CSV/XLSX registers, reliability tables, process descriptions and structured P&ID Reader exports. Add Word/PDF, scanned drawings, maintenance histories and schedules in stages. Prefer structured formats when provided. Preserve source locations. |
| D07 | System coverage | Use a common equipment, service, capacity, dependency and restoration model. Qualify offshore, onshore process and utility reference cases. Flag behaviours beyond the supported model. |
| D08 | Failure and numerical inputs | AI proposes categories and extracts traceable values. Conflicts stay visible. Missing data remains blank. Qualified estimators may derive parameters from engineer-approved observations and document exposure and uncertainty. |
| D09 | Operating logic | AI proposes duty and standby, switching, partial capacity, storage and shared dependencies. Show evidence or mark inferences. Preserve materially different plausible alternatives for review. |
| D10 | Model views | Link editable RBD, production flow and dependency views. Include evidence inspection, reviewable changes, undo and outage playback. |
| D11 | Calculation authority | Use structured, allowlisted actions with engineering validation. Allow read-only checks. Require approval before baseline changes and new experiment batches. Store inputs, revision, engine version and seed. |
| D12 | Scenario analysis | Rank candidate alternatives using the study baseline. Preserve comparable conditions, use matched streams when appropriate and report the uncertainty on the difference. Distinguish input uncertainty from sampling uncertainty. |
| D13 | Report writing | AI drafts interpretations and recommendations. Stored metrics supply values and figures. Claims reference current runs, scenarios and evidence. Engineer reviews the narrative before final export. |
| D14 | Provider operation | AI off by default. Offer optional local and cloud modes through a common interface. Use selected excerpts by default in cloud mode, protect credentials, support progress and cancellation, and reuse reviewed extractions when valid. |
| D15 | Qualification | Define thresholds before provider comparisons. Use engineer-reviewed reference projects, measure errors, evidence coverage and review time, and rerun qualification after changes. Every release-test quantitative claim must resolve to the stored result. |
