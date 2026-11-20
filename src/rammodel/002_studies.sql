CREATE TABLE study (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    model_json TEXT NOT NULL CHECK(json_valid(model_json)),
    model_hash TEXT NOT NULL,
    reviewer TEXT,
    reviewed_at TEXT
) STRICT;
CREATE TABLE run (
    id TEXT PRIMARY KEY NOT NULL,
    model_hash TEXT NOT NULL,
    record_json TEXT NOT NULL CHECK(json_valid(record_json)),
    created_at TEXT NOT NULL
) STRICT;
CREATE TABLE review_log (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    detail TEXT NOT NULL
) STRICT;
