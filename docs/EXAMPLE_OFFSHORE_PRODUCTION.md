# Worked example · synthetic offshore production

The example has a manifold, two half capacity separation trains, two full capacity export pumps, a gas compressor duty/standby pair, three generators with a two-out-of-three dependency, a crude storage buffer, one shared crew, a replenished pump spare and two weather access closures. The example uses EXAMPLE data only.

The study uses seed 42, 1,000 replications, a 2,400 calendar hour horizon and constant target of 100 m³/h. Mean production efficiency was **99.2642%**, with approximate 95% confidence interval **99.2339% to 99.2945%**. P10, P50 and P90 were 98.5868%, 99.3553% and 99.8519%. The run met the implemented mean convergence criterion.

| Option relative to two half capacity trains | Change (percentage points) | Approximate 95% paired CI |
|---|---:|---:|
| One full capacity train | -0.5402 | -0.5827 to -0.4978 |
| Three half capacity trains | +0.6764 | +0.6500 to +0.7027 |
| Double tank capacity, same initial inventory | +0.5391 | +0.5226 to +0.5556 |

The exact-cover benchmark independently models loss of all feed for six hours. It draws 600 m³ at 100 m³/h while feed is unavailable, giving **zero simulated shortfall**. The example reports are labelled draft and assume no live AI provider.

Use the .ramcase to explore the model and saved run, the model JSON to inspect inputs, Run_Comparisons.json for full paired results, and the four PNG files for captured desktop views. The Reports folder contains the generated draft reports and charts. Archive and reproduce the original case before editing its source values.

## 0.3.0.dev1 regeneration

The example was regenerated with the 0.3.0.dev1 code (`python -m rammodel.cli --demo examples/Offshore_Production`).
The model uses no 0.3 features, so the 0.2-compatible profile applies and every number above is reproduced exactly
(TEST_RESULTS/REPEATABILITY.txt). The case file is now schema 3. Comparison records additionally label each interval
kind (`sampling`, `paired_delta`) and significance. `Migrated_From_Alpha_0.2.ramcase` is the original 0.2 case file
opened once with 0.3 (migrated to schema 3, its saved run retained). New screenshots: Model_Editor.png and
Decisions_Tornado.png (the tornado uses 40 replications per bar for illustration only).
