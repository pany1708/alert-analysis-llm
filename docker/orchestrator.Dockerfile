FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir fastapi uvicorn[standard] httpx pydantic python-dotenv pyyaml structlog prometheus-client
COPY services ./services
COPY config ./config
COPY policies ./policies
ENV PYTHONPATH=/app
CMD ["uvicorn", "services.orchestrator.main:app", "--host", "0.0.0.0", "--port", "8003"]
