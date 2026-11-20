# Methods implemented in 0.2 alpha

Engineering methods informed by [ISO 20815:2026](https://www.iso.org/standard/89174.html), [IEC 61078](https://webstore.iec.ch/en/publication/25647) and [IEC 61165](https://webstore.iec.ch/en/publication/4721). These references describe the wider discipline. The program's calculations are qualified only by the included evidence. Formats for physical topology exchange may be informed by [DEXPI](https://dexpi.org/specifications/).

- **Reliability block diagrams.** Independent series, parallel and k-out-of-n availability. Nested trees reject repeated assets. Single repairable unit is MTBF divided by MTBF plus MTTR. CTMC analysis solves the stationary distribution for a finite generator.
- **Standby.** One virtual asset represents an identical-unit pair with perfect active capability when working. Cold standby sets dormant failure rate to zero, warm uses a lower rate, and hot uses the active rate. Only one exponential repair channel applies to this pair. A failed immediate switchover keeps service down until the active unit is restored. This repair channel is separate from the model's shared crew, spares and weather pool. Initialized with both units available.
- **Hidden failures.** The analytical routine reports the lambda-tau/2 approximation and the exact periodic result under perfect detection and instantaneous restoration. In discrete events, a latent mode's capacity consequence begins when it fails. Discovery occurs at the next periodic test and the normal restore model follows. The project model must explicitly document when a hidden mode affects capacity in practice.
- **Failure and repair.** Calendar exposure while a failure mode is healthy. Independent lifetime draws for exponential, Weibull and lognormal modes. A mode gets a new lifetime after restoration. During simultaneous component failures, use the maximum fractional capacity loss. Maintenance forces the affected equipment down without resetting its failure clocks. Shared dependency votes use binary input availability. Logistics delay and mobilisation precede queue entry. Crews and spares limit repair start, closed weather windows prevent starts, and active work continues through subsequent access closures.
- **Production.** Directed acyclic single-product flow network. SciPy HiGHS solves a mass-balanced linear program, first maximising delivered product up to target and then filling inventory at that delivery rate. Optional fixed splits are enforced together. The one tank has net fill/draw rate and capacity limits. Exact empty/full crossings create events. The simple profile has constant feed and target. Report capacity shortfall against target in volume per horizon and distinguish it from financial loss or recoverable deferral.
- **Statistics.** Independent replications, with NumPy PCG64 streams derived from seed, replication number and stable mode ID. Starting conditions are stated in each model. A report includes lower-tail percentiles, approximate Student-t intervals for the mean and the convergence sequence. The 1% tolerance is applied to mean efficiency. This interval convention is approximate with repeated stopping checks; zero sampled variance for a stochastic case is flagged rather than accepted as convergence. Paired options use common streams for unchanged modes.
- **Attribution.** Mean nominal downtime by mode, equipment operational uptime, and coincident outage groups. Group losses sum to measured demand shortfall. A coincident outage may be incidental. The programmatic counterfactual removes a specified mode and estimates the difference. That gain is nonadditive and may differ from coincident attribution.
- **Uncertainty.** A programmatic nested sampler supports independent uniform bounds on specified failure/repair parameters. It reports percentiles of the estimated conditional mean. Finite inner sampling adds noise. The count-over-exposure estimate supports a Poisson interval including a nonzero upper bound for zero counts.

# Additions in method rammodel-des-0.3 (package 0.3.0.dev1)

Standards for context (no conformity claimed): ISO 20815:2026 (3rd edition, production assurance), ISO 14224:2016
(reliability data), IEC 61078:2016 (RBD), IEC 61165:2006 (Markov techniques).

**Method profile.** Each run records `method_profile`. "0.2-compatible" means no 0.3 feature is present; the 0.2 event
order, random streams and LP layout are then used and results are bit-identical to 0.2 alpha. Otherwise the profile
lists the 0.3 features used. New events are queued after legacy events at equal times; new random quantities use
separate PCG64 streams keyed ("repair", asset, mode), ("demand", asset, mode) and ("@ccf", id).

**Units.** Canonical units: time h, rate 1/h, volume m³, standard volume Sm³, mass t, energy MWh, power MW, the matching
rates, fraction and count. A US oil barrel is 0.158987294928 m³. One year = 8,760 h (8,766 h only when the unit `yr_8766` is used). "month" and "m" (metre or minute) are
refused as ambiguous. Blank is missing, never zero. Conversions between dimensions are refused. Converting between
calendar and operating exposure requires an explicit utilisation.

**Failure clocks.** `exposure: calendar` ages continuously (0.2 behaviour). `exposure: operating` ages only while the
asset is available and carries flow on one of its edges (an asset with no flow edges, such as a utility, operates
whenever it is available); an idle standby member therefore does not age at the operating rate. `idle_factor` f ages an available, non-operating asset
at f times the operating rate. No asset ages while failed, under maintenance or under test (corrected during this pass,
see CHANGELOG). `initial_age` offsets the first life.

**Restoration.** `as_good_as_new` draws a fresh life. `as_bad_as_old` (minimal repair) samples the residual life
conditional on the current age for Weibull and lognormal (exponential is memoryless). Checked against the NHPP
expectation E[N(t)] = (t/η)^k.

**Repair duration.** `repair_distribution: fixed` (0.2) or `exponential` with the entered mean, drawn from the separate
repair stream. Logistics and mobilisation precede the crew queue as in 0.2.

**Hidden failures with test downtime.** Periodic proof test every τ hours lasting d hours (capacity lost while
testing); a hidden failure is found at the next test. With perfect detection, zero repair time and renewal at each test,
the mean unavailability is

U = 1 − (e^(−λd) − e^(−λτ)) / (λτ),

derived by integrating availability over one test cycle: the item is down during the test [0, d) and from failure to
the end of the cycle; for d = 0 this reduces to the exact periodic result 1 − (1 − e^(−λτ))/(λτ).

**Common cause.** `common_cause` entries fail ≥ 2 listed assets together, either as a Poisson process (`mtbf`, used as
the β-factor share λ_c = βλ with the independent parts entered as (1 − β)λ) or at deterministic `times`. Each shock is
a separate mode named "CCF:<id>" and is repaired once through the shared crew.

**Standby groups.** `standby_groups: [{members, running k}]`. At each state change, in member order, available members
keep running until k are running; idle available members start as needed. A start is a demand: members with a
`distribution: demand` mode fail to start with the entered probability (at t > 0 only) and are repaired like any
failure. Groups share crews and spares. The 0.2 `standby_pair` (dedicated exponential channel) is retained unchanged
for historical reproduction. Verified against independently constructed CTMCs for five settings.

**Weather policies.** `continue` (0.2): work started before an access closure continues; repairs cannot start while
closed. `suspend`: active repair pauses during a closure and resumes with its remaining duration.

**Schedules and periods.** Piecewise-constant `demand_schedule`, `feed_schedule` and `capacity_schedule`.
`calendar_start` attributes every interval to calendar months by splitting at month boundaries; years are sums of
months. Zero demand everywhere is refused (efficiency undefined).

**Contractual, no-failure and delivered.** Each run records contractual demand (scheduled demand × time), the
no-failure delivery (same model, all failures removed, deterministic) and the simulated delivery.

**Unmet demand.** Without a `deferral` policy all shortfall is lost (0.2). With `deferral {window_h, recovery_rate}`,
each interval's shortfall becomes a backlog chunk timestamped at the start of that interval. Spare capacity above
demand (up to the recovery rate) repays the oldest chunk first. A chunk not repaid within window_h of its timestamp is
classified lost at that time; chunks still open at the horizon are "potentially deferred". Shortfall = recovered +
lost + deferred is asserted.

**Flow solution.** Lexicographic HiGHS LP stages: delivery up to demand → catch-up up to recovery rate → total
inventory fill → each buffer in listed order → routing priority levels → minimum flow on declared recycle edges. Each
stage fixes the previous optimum within 1e-12 relative. Edge `yield` (0, 1] removes (1 − y) of the edge inflow as a
recorded yield loss. Cycles are refused unless broken by declared `recycle_edges`. Several products are refused.

**Balance.** Supply = delivered + inventory change + yield loss + residual, reported per replication and as a maximum
absolute residual, with per-buffer in/out totals.

**Economics.** Only from entered `economics {currency, cost_basis, source, value_per_unit, discount_rate_per_year}`;
lost value is discounted continuously at k = ln(1 + r)/8760 per hour and integrated exactly over each interval.

**Diagnostics and stop reason.** Every simulation reports a stop reason and diagnostics: replications with shortfall,
a rule-of-three upper bound (3/n) when none is seen (never "zero risk"), a rare-event flag, zero-variance detection and
the relative half-width of mean shortfall.

**Decisions.** Paired comparisons record the fraction of matched random streams and validity notes when the routing
or failure logic differs. Kinds of uncertainty are labelled separately: `sampling` (Monte Carlo error on a mean),
`paired_delta` (paired difference interval) and `input` (outer-loop parameter sampling). Tornado bars are paired
differences with source links. Input-uncertainty ranking reports the probability that each option is best and ranking
changes.

**Value basis and estimates.** Library values carry `stated`, `inferred`, `estimated` or `synthetic`. Failure-rate
estimates use only accepted, reviewed, same-basis observations: λ̂ = n/T with a two-sided chi-square Poisson interval (95 % by default); zero events
produce no point estimate.
