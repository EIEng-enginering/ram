"""Engineer-approved failure observations and documented constant-rate estimates.

An estimate is produced only from observations that are accepted by a named
reviewer, all on the failure mode's own exposure basis. The estimate is stored
with value basis ``estimated``, Poisson chi-square bounds and a locator listing
the observation IDs, so the origin and uncertainty remain inspectable.
"""
from datetime import UTC, datetime

from .analytics import constant_rate_estimate


def add_observation(db, obs_id, mode_id, events, exposure_hours, exposure_basis, source_id, locator):
    if type(events) is not int or events < 0:
        raise ValueError("Event count must be a nonnegative integer.")
    db.execute("INSERT INTO failure_observation VALUES (?,?,?,?,?,?,?,'unreviewed',NULL)",
               (obs_id, mode_id, events, float(exposure_hours), exposure_basis, source_id, locator))


def review_observation(db, obs_id, reviewer, accept=True):
    if not reviewer.strip():
        raise ValueError("A named reviewer is required.")
    changed = db.execute("UPDATE failure_observation SET review_state=?, reviewer=? WHERE id=?",
                         ("accepted" if accept else "rejected", reviewer.strip(), obs_id)).rowcount
    if changed != 1:
        raise ValueError("Unknown observation.")


def estimate_rate(db, mode_id, actor, confidence=0.95):
    """Pool accepted observations; refuse mixed bases or unreviewed data."""
    if not actor.strip():
        raise ValueError("Enter an audit actor.")
    row = db.execute("SELECT exposure_basis, distribution FROM failure_mode WHERE id=?", (mode_id,)).fetchone()
    if not row:
        raise ValueError("Unknown failure mode.")
    basis, distribution = row
    if distribution != "exponential":
        raise ValueError("Constant-rate estimation applies only to exponential modes.")
    observations = db.execute("""SELECT id, events, exposure_hours, exposure_basis, review_state, source_id
                                 FROM failure_observation WHERE mode_id=? ORDER BY id""", (mode_id,)).fetchall()
    usable = [o for o in observations if o[4] == "accepted"]
    if not usable:
        raise ValueError("No engineer-accepted observations for this mode.")
    if any(o[4] == "unreviewed" for o in observations):
        raise ValueError("Review or reject every observation before estimating.")
    if {o[3] for o in usable} != {basis}:
        raise ValueError(f"Observations must all use the mode's {basis} exposure basis.")
    if len({o[5] for o in usable}) != 1:
        raise ValueError("Pooling across sources needs a separately documented source; supply one source.")
    events = sum(o[1] for o in usable)
    exposure = sum(o[2] for o in usable)
    estimate = constant_rate_estimate(events, exposure, confidence)
    if events == 0:
        raise ValueError("Zero observed events: the point estimate is zero. Record the upper bound "
                         f"{estimate['interval_per_h'][1]:.4g}/h as a judgement instead of an estimate.")
    rate = estimate["rate_per_h"]
    low, high = estimate["interval_per_h"]
    locator = "estimated from observations " + ", ".join(o[0] for o in usable)
    db.execute("DELETE FROM mode_value WHERE mode_id=? AND field IN ('failure_rate_hour','mtbf_hours')", (mode_id,))
    db.execute("INSERT INTO mode_value VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (mode_id, "failure_rate_hour", rate, usable[0][5], locator,
                f"{events} events / {exposure:g} h", f"1/h ({basis})", "unreviewed", "bounds", low, high, None))
    db.execute("INSERT INTO mode_value_meta VALUES (?,?,?,?,NULL)",
               (mode_id, "failure_rate_hour", "estimated", f"{confidence:.0%} Poisson chi-square interval"))
    db.execute("INSERT INTO review_log (target,action,actor,created_at,detail) VALUES (?,?,?,?,?)",
               (mode_id, "estimate rate", actor.strip(), datetime.now(UTC).isoformat(),
                f"events={events}; exposure_h={exposure}; basis={basis}; bounds=[{low},{high}]"))
    return estimate
