-- 0.3: value basis (side table keeps the 0.2 mode_value shape unchanged), applicability, import batches, model revision history and
-- reliability observations. Existing rows are preserved; example-sourced values
-- are classified as synthetic.
CREATE TABLE mode_value_meta (
    mode_id TEXT NOT NULL,
    field TEXT NOT NULL,
    value_basis TEXT NOT NULL CHECK(value_basis IN ('stated','inferred','estimated','synthetic')),
    applicability TEXT,
    import_batch TEXT,
    PRIMARY KEY(mode_id, field),
    FOREIGN KEY(mode_id, field) REFERENCES mode_value(mode_id, field) ON DELETE CASCADE
) STRICT;
INSERT INTO mode_value_meta (mode_id, field, value_basis)
    SELECT mode_id, field, CASE WHEN source_id IN (SELECT id FROM source WHERE kind = 'example')
                                THEN 'synthetic' ELSE 'stated' END FROM mode_value;
CREATE TABLE import_batch (
    id TEXT PRIMARY KEY NOT NULL,
    actor TEXT NOT NULL CHECK(length(trim(actor)) > 0),
    created_at TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_sha256 TEXT,
    mapping_json TEXT NOT NULL CHECK(json_valid(mapping_json)),
    row_count INTEGER NOT NULL CHECK(row_count >= 0),
    detail TEXT NOT NULL
) STRICT;
CREATE TABLE model_revision (
    hash TEXT PRIMARY KEY NOT NULL,
    model_json TEXT NOT NULL CHECK(json_valid(model_json)),
    parent_hash TEXT,
    actor TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO model_revision (hash, model_json, parent_hash, actor, note, created_at)
    SELECT model_hash, model_json, NULL, 'migration 003', 'Revision present when the case was upgraded', datetime('now')
    FROM study;
CREATE TABLE failure_observation (
    id TEXT PRIMARY KEY NOT NULL,
    mode_id TEXT NOT NULL REFERENCES failure_mode(id),
    events INTEGER NOT NULL CHECK(events >= 0),
    exposure_hours REAL NOT NULL CHECK(exposure_hours > 0),
    exposure_basis TEXT NOT NULL CHECK(exposure_basis IN ('operating','calendar')),
    source_id TEXT NOT NULL REFERENCES source(id),
    source_locator TEXT NOT NULL CHECK(length(trim(source_locator)) > 0),
    review_state TEXT NOT NULL CHECK(review_state IN ('unreviewed','accepted','rejected')),
    reviewer TEXT,
    CHECK(review_state <> 'accepted' OR (reviewer IS NOT NULL AND length(trim(reviewer)) > 0))
) STRICT;
