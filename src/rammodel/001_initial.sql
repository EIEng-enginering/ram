CREATE TABLE source (
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('site', 'vendor', 'licensed', 'judgement', 'example')),
    citation TEXT NOT NULL CHECK(length(trim(citation)) > 0),
    document_sha256 TEXT CHECK(document_sha256 IS NULL OR (
        length(document_sha256) = 64 AND document_sha256 NOT GLOB '*[^0-9a-f]*'
    )),
    revision TEXT
) STRICT;

CREATE TABLE subsystem (
    id TEXT PRIMARY KEY NOT NULL,
    parent_id TEXT REFERENCES subsystem(id),
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    CHECK(parent_id IS NULL OR parent_id <> id)
) STRICT;

CREATE TABLE equipment (
    id TEXT PRIMARY KEY NOT NULL,
    subsystem_id TEXT NOT NULL REFERENCES subsystem(id),
    tag TEXT COLLATE NOCASE NOT NULL CHECK(length(trim(tag)) > 0),
    equipment_class TEXT NOT NULL CHECK(length(trim(equipment_class)) > 0),
    UNIQUE(subsystem_id, tag)
) STRICT;

CREATE TABLE failure_mode (
    id TEXT PRIMARY KEY NOT NULL,
    equipment_id TEXT NOT NULL REFERENCES equipment(id),
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    detection TEXT NOT NULL CHECK(detection IN ('revealed','hidden','unresolved')),
    distribution TEXT NOT NULL CHECK(distribution IN ('exponential','weibull','lognormal','unresolved')),
    exposure_basis TEXT NOT NULL CHECK(exposure_basis IN ('operating','calendar','unresolved')),
    UNIQUE(equipment_id, name)
) STRICT;

-- Values use canonical units. A missing row means a missing value.
-- Field-level applicability and completeness are checked before analysis.
CREATE TABLE mode_value (
    mode_id TEXT NOT NULL REFERENCES failure_mode(id),
    field TEXT NOT NULL CHECK(field IN (
        'failure_rate_hour', 'mtbf_hours', 'weibull_shape', 'weibull_scale_hours',
        'lognormal_median_hours', 'lognormal_sigma', 'logistics_hours',
        'mobilisation_hours', 'active_repair_hours', 'proof_test_hours', 'capacity_loss_fraction'
    )),
    value REAL NOT NULL CHECK(value >= 0 AND value <= 1.7976931348623157e308),
    source_id TEXT NOT NULL REFERENCES source(id),
    source_locator TEXT NOT NULL CHECK(length(trim(source_locator)) > 0),
    original_value TEXT NOT NULL CHECK(length(trim(original_value)) > 0),
    original_unit TEXT NOT NULL CHECK(length(trim(original_unit)) > 0),
    review_state TEXT NOT NULL CHECK(review_state IN ('unreviewed', 'accepted', 'rejected')),
    uncertainty TEXT NOT NULL CHECK(uncertainty IN ('unassessed','bounds','error_factor')),
    low REAL,
    high REAL,
    error_factor REAL,
    PRIMARY KEY(mode_id, field),
    CHECK(field <> 'capacity_loss_fraction' OR (value <= 1 AND (high IS NULL OR high <= 1))),
    CHECK(field IN ('failure_rate_hour','logistics_hours','mobilisation_hours','active_repair_hours',
        'capacity_loss_fraction') OR value > 0),
    CHECK(
        (uncertainty = 'unassessed' AND low IS NULL AND high IS NULL AND error_factor IS NULL)
        OR (uncertainty = 'bounds' AND low IS NOT NULL AND high IS NOT NULL AND
            low >= 0 AND low <= value AND high >= value AND high <= 1.7976931348623157e308 AND
            error_factor IS NULL)
        OR (uncertainty = 'error_factor' AND error_factor IS NOT NULL AND error_factor >= 1 AND
            error_factor <= 1.7976931348623157e308 AND low IS NULL AND high IS NULL)
    )
) STRICT;
