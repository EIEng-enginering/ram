# Engineering risk register · Revision A

These are design risks. Controls remain unverified until the cited tests pass.

| ID | Risk | Priority | Proposed control | Trace |
|---|---|---|---|---|
| R01 | Unit, exposure basis or denominator changes distort comparisons | High | Typed units, preserved originals, explicit exposure and nominal/target bases | RAM-01, RAM-06 |
| R02 | Drawing ambiguity creates fictitious paths or redundancy | High | Typed edges, evidence review, unresolved connections, shared-utility checks | RAM-02, RAM-08 |
| R03 | Missing or proprietary data are misrepresented | High | Explicit missing and EXAMPLE states, cited imports, review controls, authorised sources | RAM-01, RAM-08, RAM-10 |
| R04 | Unsupported engine assumptions produce confident estimates | High | Method eligibility, known answers, versioned validation and blocked unsupported behaviour | RAM-04, RAM-05 |
| R05 | Storage, concurrent outages or queues double count lost volume | High | Balance checks and deterministic event-order fixtures | RAM-03, RAM-06, RAM-07 |
| R06 | False convergence or irreproducibility misleads the decision | High | Seed and run hashes, uncertainty labels, diagnostics for rare events and near-zero loss | RAM-05, RAM-07 |
| R07 | Stale or unsubstantiated findings enter the final report | High | Snapshot-bound metrics, claim verification, explicit stale/review checks | RAM-09, RAM-10 |
| R08 | Provider receives project documents outside user intent | High | Local operation by default, explicit provider configuration, controlled evidence sharing | RAM-08 |
| R09 | Migration or synced-folder writes corrupt the project | High | Transactional migrations, backups, locking and validated archive round-trips on Windows | RAM-01, RAM-12 |
| R10 | A cross-domain model is mistaken for a qualified domain model | High | Versioned supported behaviours and separate acceptance examples | RAM-11 |
