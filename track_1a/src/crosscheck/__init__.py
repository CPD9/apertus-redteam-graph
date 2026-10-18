"""A second, independent derivation of every number the report and the findings state, from the
recorded runs, the LLM cache and the speech scores. It shares with redteam only what finds a
recorded reply (the cache key, the pack reader, the prompts the harness sent) and counts,
pools and bootstraps on its own.

    PYTHONPATH=src python3 -m crosscheck [--diffs] [--json PATH]
"""
