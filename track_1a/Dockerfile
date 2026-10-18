FROM python:3.12-slim
WORKDIR /app
# Installed editable: the harness reads findings/, data/ and runs/ next to src/.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --root-user-action=ignore -e .
COPY findings ./findings
COPY data ./data
# The tests also cover scripts/ and check the summary table of the report.
COPY scripts ./scripts
# Domain packs for make live, e.g. REDTEAM_BANKS=examples/coding (docs/playbooks/new-domain.md).
COPY examples ./examples
COPY tests ./tests
COPY technical_report.md ./
ENV PYTHONUNBUFFERED=1
# Run the graph (make run forces a replay), validate every findings file, then rebuild the five
# findings from data/runs (the speech finding from per-clip scores, keeping the model outputs it
# quotes) and fail on any difference; on success the last thing printed is the report's table.
CMD ["sh", "-c", "python -m redteam.run && python -m redteam.check && python -m redteam.reproduce"]
