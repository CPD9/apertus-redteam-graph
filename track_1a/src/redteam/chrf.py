"""chrF as in Popović (2015), "chrF: character n-gram F-score for automatic MT evaluation"."""
from collections import Counter
from statistics import mean


def char_ngrams(text, n):
    return Counter(text[i:i + n] for i in range(len(text) - n + 1))


def chrf(hypothesis, reference, max_n=6, beta=2.0):
    # Average n-gram precision and recall over n = 1..6, whitespace removed, recall weighted by beta.
    hyp = "".join(hypothesis.split())
    ref = "".join(reference.split())
    precisions, recalls = [], []
    for n in range(1, max_n + 1):
        hyp_grams, ref_grams = char_ngrams(hyp, n), char_ngrams(ref, n)
        if not hyp_grams or not ref_grams:
            continue
        overlap = sum((hyp_grams & ref_grams).values())
        precisions.append(overlap / sum(hyp_grams.values()))
        recalls.append(overlap / sum(ref_grams.values()))
    if not precisions:
        return 0.0
    p, r = mean(precisions), mean(recalls)
    if p + r == 0:
        return 0.0
    return 100 * (1 + beta ** 2) * p * r / (beta ** 2 * p + r)
