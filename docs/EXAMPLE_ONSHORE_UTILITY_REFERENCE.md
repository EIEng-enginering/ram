# Worked examples · synthetic onshore gas plant and independent utility reference case

All values are invented EXAMPLE data. Folder: examples/Onshore_Utility_Reference. Reproduce with
`python -m rammodel.cli --onshore <folder> --runs 500` (seed 42; utility reference seed 11, 200 × 20,000 h).

## Independent utility reference case (hand calculation)

A grid supply GRID (MTBF 990 h, exponential repair mean 10 h → A_g = 0.99) is required by two compressors C1 and C2
(MTBF 190 h, exponential repair mean 10 h → A_c = 0.95), each 60 units/h against a 100 units/h target. Calendar clocks
and unlimited crews make all items independent, so

efficiency = A_g × (A_c² × 1.0 + 2 A_c (1 − A_c) × 0.6) = 0.99 × 0.9595 = **0.949905**.

| Quantity | Value |
|---|---|
| Expected (hand) | 0.949905 |
| Simulated mean (200 reps × 20,000 h, seed 11) | 0.949657 |
| Standard error | 0.000356 |
| Tolerance (4 SE + 0.0015 start-up bias, all-up start) | 0.002922 |
| Result | PASS (difference 0.000248) |
| Same plant ignoring the shared grid (false redundancy) | 0.9595, rejected as optimistic |

The discrepancy is within sampling error. Simulation starts with all items up, which biases short horizons slightly
upward; hence the stated bias allowance.

## Synthetic onshore gas plant (0.3 features)

Field → slug catcher buffer (300 m³, initial 150) → two 70 m³/h compression/dehydration trains (yield 0.98, routing
priority train 1 then train 2, shared dehydrator, both compressors and both export pumps need GRID) → product tank
(800 m³, initial 400) → export pumps A/B as a 1-running standby group with 2 % start failure probability and idle aging
factor 0.1. Compressor common-cause shock (MTBF 30,000 h, 48 h repair), two crews, a 72 h access closure with the
`suspend` weather policy, demand 100/90/100 m³/h by season from 1 January 2027, a 168 h deferral window at 10 m³/h
recovery, and economics of AUD 40/m³ (2027 real, synthetic) discounted at 7 %/yr.

Results (500 replications, seed 42, 8,760 h): mean efficiency **99.7357 %** (95 % CI 99.7037–99.7677 %); mean
shortfall 7,033 m³ of which recovered 4,834, lost 2,082 and potentially deferred at horizon 117 m³; mean discounted lost
value AUD 80,668 (from entered assumptions only). A doubled product tank improves efficiency by **+0.0961 pp**
(paired 95 % CI +0.0880 to +0.1043 pp). The draft reports are in Reports/ and are labelled DRAFT | EXAMPLE DATA.

No independent hand result exists for the whole onshore plant; its conservation (balance residual < 1e-6), period
sums, contractual demand (2160×100 + 4392×90 + 2208×100 = 832,080 m³) and repeatability are tested in
tests/test_wp6_examples.py. Independent engineering verification remains open.
