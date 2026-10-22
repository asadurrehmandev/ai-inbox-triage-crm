FROM python:3.12-slim

WORKDIR /app

COPY requirements.lock pyproject.toml README.md ./
COPY app ./app
COPY data ./data

RUN pip install --no-cache-dir -r requirements.lock \
    && pip install --no-cache-dir --no-deps .

ENV DATABASE_PATH=/data/triage.db
EXPOSE 8741

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8741"]
