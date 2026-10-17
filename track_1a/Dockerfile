FROM python:3.12-slim
WORKDIR /app
COPY src ./src
COPY findings ./findings
COPY data ./data
COPY tests ./tests
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
# Run the graph, then fail the container if any findings file breaks the schema.
CMD ["sh", "-c", "python -m redteam.run && python -m redteam.check"]
