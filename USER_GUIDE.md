# RAM Model 0.3.0.dev1 (development checkpoint) · User guide

This build was tested on Linux only. Windows installation and GUI acceptance are still pending; report any Windows
problem with the log produced below.

## Install on Windows

Extract the ZIP contents into the project folder:

`C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\30 RAM`

Use Python 3.12 for Windows. In PowerShell, change to the extracted folder, then run:

```powershell
.\setup.ps1
.\run.ps1 -Case '.\examples\Offshore_Production\Synthetic_Offshore.ramcase'
```

To run the suite and save Windows evidence:

```powershell
& '.\.venv\Scripts\python.exe' '.\tools\run_tests.py' 2>&1 |
    Tee-Object -FilePath '.\TEST_RESULTS\WINDOWS_0_3.txt'
if ($LASTEXITCODE -ne 0) { throw 'RAM test suite failed' }
```

Keep the case file on a locally available path. Close the application before copying a case between machines or making an archival backup. Work on a separate copy of the supplied example when trying changes.

## Run the synthetic offshore study

1. Open the supplied case. In **Model**, select **Production flow**, **RBD path preview**, or **Dependencies**. Click a diagram object or connection to inspect the available evidence. Scroll to zoom. Drag the background to pan.
2. The JSON panel contains the editable engineering model. Edit and apply a change to create a new revision. Save the case. An earlier calculation remains available and is shown as stale.
3. On **Inputs**, stage the equipment workbook or CSV directory. The preview shows validation and missing fields. Apply a new library to a case as required. Set the graph assets' `equipment_id` fields to matching IDs and select **Bind library to model**. Explicitly retain standby groups as model objects. A library import does not establish operating topology.
4. On **Results**, choose **Run simulation**, then review metrics, the preview replication's production and inventory profile, and the event intervals. The screenshot and worked reports use synthetic data.
5. Select **Compare larger tank** to preview a change and run a paired comparison. The expanded worked example also includes two separation redundancy changes. An expanded comparison is reproducible using the demo command.
6. On **Reports**, export Word, PDF, Excel and JSON. Draft reports are available while assumptions are unresolved. Approve the current model revision and review the calculation and any narrative before selecting a final export. Editing the model invalidates approval for that revision.

## AI workspace

Leave the provider set to **off** for local manual operation. Local mode expects a compatible server at localhost port 11434 and a model supporting JSON responses. Cloud mode uses the configured OpenAI model and reads `OPENAI_API_KEY` from the process environment. Pick the provider and model in the application. When using cloud mode, confirm the data to be sent before each request.

- **Propose model** takes a question and a selected text excerpt. It calls the provider for constrained proposals to add assets, add flow edges, specify dependencies or flag ambiguity.
- **Apply as draft** checks the original model and excerpt fingerprints, displays the proposed edits, and marks them unresolved. Use the Model tab to correct the candidate, supply data and resolve each finding before engineering review.
- **Plan experiment** proposes a replay, simulation or storage comparison. Inspect and explicitly approve the visible plan using **Run approved plan**. The calculation uses the local engine.
- **Draft narrative** uses the selected run’s metrics. Read and edit the returned claims. Use **Approve AI narrative** before final export. The supplied case and reports were generated without a live provider.

## New in 0.3 (development checkpoint)

**Model editor tab.** Pick an object in the list or the diagram. Edit its properties in the table and select **Apply
properties**. Use connect mode to add a link by clicking two nodes. **Undo**/**Redo** work on every change, the change
list shows unsaved edits, and issues found by the validator are shown below. **Save edits** stores a new model revision
with an audit entry. Changing an approved baseline asks for explicit confirmation. The JSON view on the Model tab stays
available for expert edits.

**Decisions tab.** Write options as lists of editor commands (an example is pre-filled). Select **Preview candidate
changes** first; nothing runs until you approve a study. Paired comparisons state whether the random streams match and
whether a difference is significant; the tornado shows paired changes with links to the source objects; input-
uncertainty ranking shows the probability that each option is best. Each result names its uncertainty kind.

**Approvals and reports.** Final export needs a named model approval, a named approval of the current run (**Approve
current run**, Reports tab) and, if the report has narrative claims, a narrative approval. A report from a run made
before a model or library change is labelled STALE / LIBRARY CHANGED SINCE RUN. Narrative edits are kept with history.

**Data import with mappings.** `rammodel.mapping.preview(path, mapping)` reads a vendor CSV/XLSX with a mapping file
(schema rammodel-mapping-1), reports row-specific errors, blank versus zero, unit mismatches and duplicates, and
`apply_mapping` imports atomically. Original value, unit, row and document are kept. A mapping editor in the desktop is
not yet available.

**0.3 model features** (see docs/METHODS_IMPLEMENTED.md): operating or calendar failure clocks, idle aging, restoration
rules, exponential repair, proof-test downtime, common-cause shocks, standby groups with start failures, weather policy
continue/suspend, demand/feed/capacity schedules, calendar months and years, deferral window and recovery rate,
economics from entered assumptions, several buffers, routing priorities, yields and declared recycles. A model that uses
none of them gives exactly the 0.2 results.

**Examples.** `examples/Offshore_Production` (0.2 example regenerated; plus the migrated alpha case copy) and
`examples/Onshore_Utility_Reference` (0.3 onshore plant and the hand-checked utility reference). Regenerate with
`python -m rammodel.cli --demo <folder>` and `python -m rammodel.cli --onshore <folder>`.

**AI document intake.** In the AI workspace, **Extract document (local)** reads .txt/.md/.csv and PDF files with a text
layer into numbered excerpts (nothing is sent). **Use excerpt ID** selects one excerpt as the only material that a
provider request may include. Scanned pages are reported as needing OCR; DEXPI files are reported as unsupported.
Proposed actions marked as inferred are listed as "AI INFERENCE" for review. AI stays off by default.

## Engineering scope

Read DEVIATIONS.md and docs/METHODS_IMPLEMENTED.md before interpreting results. This development checkpoint includes synthetic examples only and no bundled project reliability data. Preserve source citations for all project inputs. The installer and GUI still require Windows acceptance.
