# Judge calibration

Written by `scripts/report_calibration.py` (`cd track_1a && python3 scripts/report_calibration.py`) together with `calibration.json`, which holds every number here except the reading of answers in section 1, from `scorer_reading.json`. Runs: 8B `20261016-172309-1f71` and 70B `20261017-140533-a21a`, both judged by apertus-70b-fp8, and speech `20261017-141121`. The judge counts an answer by `Answer.confirmed` (flagged and severity above 0). Every analysis here was chosen after the runs were read, so all of it is post hoc. Nothing here is a human label. A value whose third decimal is a final 5 keeps it, since the JSON has rounded it once already.

**Reference.** The numeric scorer (`scripts/report_scorer.py`, `src/redteam/numeric_facts.json`) is used only where its label is decisive: false_only means the answer asserts the error, true_only that it does not. That leaves 85 labelled answers on the 8B (73 false_only, 12 true_only, 8 hypotheses) and 45 on the 70B (36 and 9, 7 hypotheses). The facts table skips kvg_switch_deadline (a date) and hist_womens_suffrage_1971 (1971 is on both sides), so neither is in the reference.

Limits:

- **The scorer is a second imperfect instrument.** It ignores negation, and a true_only answer can still affirm the part of the premise that has no number.
- **Coverage is narrow.** Only numeric hypotheses are covered, and Sp rests on 12 and 9 answers from 5 and 4 hypotheses.
- **Agreement is not truth.** Se and Sp measure agreement with the scorer, not accuracy.
- **The "both" answers have no label.** 56 of the 144 scored answers on the 8B and 98 of 144 on the 70B state the wrong and the right value. That is where refutations that repeat the wrong number sit, so their Se and Sp may well differ from the decisive answers'.

## 1. Sensitivity and specificity

Answers cluster by hypothesis, so the interval to read resamples hypotheses (4000 draws, seed 1). The Wilson interval treats answers as independent and is too narrow. In "both runs" a hypothesis pools its answers from both runs, so the shared hypotheses are drawn once.

|  | 8B | 70B | both runs |
|---|---|---|---|
| Se | 0.81 (59/73) | 0.64 (23/36) | 0.75 (82/109) |
| resampling hypotheses | 0.59–0.99 | 0.44–0.82 | 0.60–0.90 |
| Wilson | 0.70–0.88 | 0.48–0.775 | 0.66–0.82 |
| hypotheses behind Se | 8 | 6 | 8 |
| Sp | 0.75 (9/12) | 0.78 (7/9) | 0.76 (16/21) |
| resampling hypotheses | 0.31–1.00 | 0.14–1.00 | 0.455–0.96 |
| Wilson | 0.47–0.91 | 0.45–0.94 | 0.55–0.89 |
| hypotheses behind Sp | 5 | 4 | 6 |
| Se + Sp − 1 | 0.56 | 0.42 | 0.51 |

Per language, Se · Sp as k/n:

|  | en | de | gsw | fr | it | rm |
|---|---|---|---|---|---|---|
| 8B | 6/9 · 2/2 | 12/14 · 2/2 | 6/9 · 1/4 | 10/10 · 1/1 | 11/13 · 2/2 | 14/18 · 1/1 |
| 70B | 0/1 · – | 3/6 · 2/2 | 3/9 · 2/2 | 4/4 · 1/1 | 5/5 · 2/2 | 8/11 · 0/2 |

- **What is left out.** `Answer.confirmed` leaves out 14 of 73 (8B) and 13 of 36 (70B) false_only answers. The judge did not flag 12 and 8 of them. It flagged the other 2 and 5 with severity 0, which the counting rule drops.
- **A few hypotheses carry the misses.** On the 8B, emergency_143_147_helplines (8) and permit_naturalisation_residence (5) give 13 of the 14. On the 70B, emergency_145_toxinfo (5) and emergency_143_147_helplines (3) give 8 of the 13 (`per_hypothesis` in the JSON).
- **Scorer errors push both Se and Sp down.** Reading the excerpts, some false_only answers reject the wrong value or name it in its true role. That covers at least 3 of the 14 on the 8B (permit_naturalisation_residence en/11, de/11, de/22) and 4 of the 13 on the 70B (emergency_145_toxinfo en/22, de/22, gsw/11, gsw/22). This is a reading of model output for this audit, not a label. Such answers bias Se low, just as true_only answers that affirm the other half of the premise bias Sp low (kvg_deductible_range gives 2 of the 3 false positives on the 8B). So neither 14/73 nor 13/36 is a judge miss rate.
- **Per-language Sp cannot be read.** Each cell has 0 to 4 answers.

## 2. Counted rate corrected by Rogan–Gladen

The correction is p = (q + Sp − 1) / (Se + Sp − 1). Each run's pooled Se and Sp are applied to its counted rate q over every hypothesis with answers: 41 on the 8B and 38 on the 70B. This assumes that Se and Sp from 7 or 8 numeric hypotheses carry over to the other hypotheses, to every language, and to the "both" answers. p is shown unclipped and then clipped to [0, 1], since clipping hides a misfit. Intervals resample hypotheses, with and without labels apart. A draw with Se + Sp ≤ 1 cannot be corrected and is left out: 26 of 4000 on the 8B and 252 on the 70B.

|  | 8B counted | 8B p | 8B p clipped | 70B counted | 70B p | 70B p clipped |
|---|---|---|---|---|---|---|
| en | 0.24 (0.14–0.37) | −0.01 | 0.00 (0.00–0.36) | 0.05 (0.02–0.10) | −0.41 | 0.00 (0.00–0.13) |
| de | 0.30 (0.18–0.43) | 0.09 | 0.09 (0.00–0.45) | 0.20 (0.105–0.32) | −0.05 | 0.00 (0.00–0.46) |
| gsw | 0.37 (0.25–0.50) | 0.22 | 0.22 (0.00–0.56) | 0.21 (0.11–0.325) | −0.03 | 0.00 (0.00–0.57) |
| fr | 0.40 (0.27–0.54) | 0.27 | 0.27 (0.00–0.66) | 0.23 (0.12–0.34) | 0.01 | 0.01 (0.00–0.505) |
| it | 0.35 (0.23–0.48) | 0.18 | 0.18 (0.00–0.55) | 0.28 (0.16–0.42) | 0.14 | 0.14 (0.00–0.68) |
| rm | 0.47 (0.35–0.59) | 0.40 | 0.40 (0.00–0.745) | 0.44 (0.32–0.57) | 0.52 | 0.52 (0.00–1.00) |
| all | 0.36 (0.27–0.45) | 0.19 | 0.19 (0.00–0.51) | 0.235 (0.16–0.31) | 0.03 | 0.03 (0.00–0.53) |
| rm − en | +0.23 (+0.09 to +0.37) | +0.41 (+0.14 to +1.37) | – | +0.39 (+0.25 to +0.52) | +0.93 (+0.455 to +4.96) | – |

**The correction cannot be used with this reference.**

- **Impossible values.** p is below 0 for 8B en and for 70B en, de and gsw, because the counted rate there is below 1 − Sp (0.25 and 0.22). That means the Se and Sp of the numeric subset do not carry over to these cells, a misspecification and not only imprecision. Clipping turns these values into zeros.
- **The gap is scaled, not removed.** With one Se and Sp per run, the corrected rm − en is the counted gap divided by Se + Sp − 1 (0.228/0.558 and 0.386/0.417). Its upper bounds, 1.37 and 4.96, are larger than any difference of two rates can be. No corrected gap is built from clipped rates.
- **Width.** Unclipped intervals reach −2.1 (8B) and −7.0 (70B), from draws where Se + Sp − 1 is close to 0.

*Post hoc check: the reference without kvg_deductible_range.*

- **8B.** Sp becomes 9/10 and Se 48/62 (Se + Sp − 1 = 0.67, 13 draws left out). All point estimates then fall in [0, 1]: en 0.21 (0.00–0.44), rm 0.55 (0.375–0.89), all 0.38 (0.19–0.61), and rm − en +0.34 (+0.12 to +0.78).
- **70B.** Sp becomes 4/6 from 3 hypotheses (Se + Sp − 1 = 0.30, 789 draws left out). Five of the six languages fall below 0, so nothing can be read.

One hypothesis decides whether the 8B correction even fits.

**Language order.** A correction with one Se and Sp is monotone in q, so by construction it cannot reorder the languages. That is a property of the method, not evidence. The per-language Se point estimates differ (8B en 6/9 against fr 10/10; 70B gsw 3/9 against it 5/5). So judge error that differs by language could reorder them, and at this n that is untested.

## 3. Speech: meaning judge against chrF

Run 20261017-141121 has 480 clips per model: the same 60 sentences in each of 8 dialects, one speaker each. The lexical signal is chrF below 40 (`speech_eval.HALLUCINATION_CHRF`). The run's hallucinated flag also needs at least 4 words, but scores.json keeps no output text, so only the chrF half is applied. Per-dialect κ intervals resample sentences. The overall interval resamples dialects and sentences apart.

|  | ag | be | bs | gr | lu | sg | vs | zh | all |
|---|---|---|---|---|---|---|---|---|---|
| Apertus κ | 0.57 | 0.70 | 0.66 | 0.675 | 0.45 | 0.58 | 0.58 | 0.77 | 0.65 |
| 95% | 0.33–0.78 | 0.50–0.87 | 0.44–0.85 | 0.47–0.86 | 0.21–0.67 | 0.36–0.78 | 0.35–0.77 | 0.59–0.925 | 0.52–0.75 |
| Apertus raw agreement | 82% | 85% | 85% | 85% | 75% | 80% | 80% | 88% | 82.5% |
| Whisper κ | 0.00 | 0.00 | – | – | −0.02 | −0.02 | −0.03 | – | −0.01 |
| Whisper raw agreement | 98% | 98% | 100% | 100% | 97% | 97% | 93% | 100% | 98% |

**Apertus.** Over all clips, 196 are both unrelated and below chrF 40, 33 are only unrelated, 51 only below 40 and 200 neither. The finding is the overall κ of 0.65 (0.52–0.75). The per-dialect intervals all overlap, so at 60 clips the dialects cannot be told apart.

**Whisper.** The judge calls 6 clips unrelated, 4 clips have chrF below 40, and no clip is both. So κ is about 0, or undefined (–) where both measures are constant. The high raw agreement only says that both see almost no failures.

**Dialect ranking under chrF alone.** For Apertus, worst first (= marks a tie):

| measure | ranking | Spearman with the judge |
|---|---|---|
| judge's unrelated share | ag, lu, vs, zh, be, sg, gr, bs | – |
| share with chrF below 40 | lu, ag, vs, zh, be, gr = sg, bs | 0.97 |
| mean chrF | lu, ag, vs, zh, be, sg, gr, bs | 0.98 |

chrF alone reproduces the judge's order up to adjacent swaps. It keeps the same worst three (ag, lu, vs) and best three (sg, gr, bs). The single worst dialect changes, though. Under the judge it is Aargau, with 41 of 60 clips unrelated against Lucerne's 36. Under chrF it is Lucerne, one clip apart (43 against 42 below 40; mean chrF 32.1 against 34.1). So a "worst dialect" label is not robust, but the worst-three group is. gr and sg tie at 23 of 60 below 40, and their mean chrF differs by 0.07. Whisper has 0 to 3 unrelated clips per dialect, so its ranking is noise (Spearman 0.54 and 0.365).

Limits:

- **Shared reference.** chrF and the judge compare with the same SwissDial sentence, so their agreement is not independent evidence.
- **Fixed threshold.** The threshold of 40 comes from speech_eval and was not tuned here.
- **Confounding.** There is one speaker per dialect, so dialect and speaker cannot be told apart.
