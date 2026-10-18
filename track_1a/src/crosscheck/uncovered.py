"""What the cross-check does not re-derive, and why. Printed after the checks and written with
them, so a reader sees where the independent derivation stops."""
from .bounds import CI, HARNESS_DRAWS
from .exact import LARGEST
from .rates import DRAWS, SEED

NOT_COVERED = [
    ("technical_report.md finding 1: 'agrees in 14 of the 15' non-English answers",
     "a reading of the answers: the counting rule counts 15 of 15 there (the 15 is checked); the "
     "report leaves out one it reads as only repeating the question"),
    ("technical_report.md finding 2: 'four add details nobody gave'",
     "a reading of the answer texts, not a count the verdicts decide"),
    ("technical_report.md finding 2: 'the 8B declines in English'; finding 3: 'confirms 112'",
     "readings of the answer texts: only that no English answer, or every answer, is counted "
     "is checked, which holds as well for answers that hedge or say something else"),
    ("technical_report.md finding 3: 'one German answer adds 145', '144 (ambulance)'",
     "readings of the answer texts; only the counts of answers that state the error are checked"),
    ("technical_report.md: 65.7% yes, 15½ cantons to 6½, CHF amounts, ages and dates",
     "facts from the cited sources and the references, not from the runs"),
    ("technical_report.md use of Apertus: the commits of the served weights",
     "read from the Hugging Face API; the runs do not log them"),
    ("technical_report.md reproducibility: 2.5 s and 8-10 s",
     "timings on one machine"),
    ("technical_report.md: four strategies, six agents, four attempts, the 34% bar, 2000 draws, "
     "the 600 and 3,000 characters the log keeps",
     "design constants of the harness, used here as given; the cache keys confirm the sampling "
     "temperature and token limit of the target"),
    ("findings/*.json self_assessed_severity and its justification",
     "the team's judgement against the rubric"),
    ("findings/*.json harness_red_model, judge_model and the *_version fields",
     "the full name behind the served alias and the weight commits come from infra/ and the "
     "Hugging Face API, not from the recorded data"),
    ("findings/*.json 'counted in Standard German' after a language's rate",
     "which answers the word list reads as Standard German or Italian is taken as "
     "docs/audit/stimuli.json lists it (scripts/report_stimuli.py, redteam.lang_profile); which of "
     "them count, and whether they are most of the counted ones, is re-derived"),
    ("findings/*.json quotes in observed_behavior and the walkthroughs",
     "model output the harness picks; the picking rule is not re-derived"),
    ("findings/speech_dialect_hallucination.json meaning labels, per-clip chrF and quoted "
     "translations",
     "the audio calls are not cached and SwissDial's text is not in the repository: labels and "
     "chrF are taken as scores.json records them and only aggregated again"),
    ("the summary table's speech row title",
     "the speech finding's own headline; no data decide it"),
    ("bootstrap intervals on grids too large to enumerate (the eight-variation theme, the speech "
     "clips, the run comparisons' hypothesis resamples)",
     f"drawn again with another random stream (seed {SEED}, {DRAWS} draws) and compared within "
     f"{CI:g}, or {100 * CI:g} points where the text rounds to whole percentages: agreement, not "
     f"identity. Grids of up to {LARGEST} resamples are enumerated exactly instead, and a stated "
     f"bound agrees when {HARNESS_DRAWS} draws give it with fair chance"),
    ("docs/figures/*.svg",
     "drawn from numbers.json, whose numbers are checked"),
]
