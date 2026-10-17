"""The models a findings file names: the full Hugging Face id of a model vLLM served under a short
name, and the commit of the weights each model was served from (runs do not log it)."""

SERVED_AS = {"apertus-70b-fp8": "onprem-ai/Apertus-v1.5-70B-FP8"}  # infra/runpod/serve_70b_red.sh
# The head of each model's main branch when the pod downloaded its weights for the runs of 16 and
# 17 October 2026, read from the Hugging Face API (huggingface.co/api/models/<id>) on 17 October.
REVISIONS = {"swiss-ai/Apertus-v1.5-8B": "ef4bbc54d6fe658bc782280ff9f3b53a10a9758f",
             "onprem-ai/Apertus-v1.5-70B-FP8": "70378c8df951c9f932e0a28f72e0148d868b5f6b",
             "gcoli/whisper-large-v3-swiss-german-mit": "38955e408982fbdd6163f823bc821542b44751a5"}


def model_id(name: str) -> str:
    return SERVED_AS.get(name, name)


def versioned(key: str, name: str) -> dict:
    """{key: commit} for weights whose commit is known, else nothing: a version is never guessed."""
    return {key: REVISIONS[name]} if name in REVISIONS else {}


def model_card(name: str, parameters: dict) -> dict:
    """The model block of a findings file."""
    return {"name": name, **versioned("version", name), "provider": name.split("/")[0],
            "source_url": f"https://huggingface.co/{name}", "parameters": parameters}
