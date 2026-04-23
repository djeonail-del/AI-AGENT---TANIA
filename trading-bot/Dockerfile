FROM python:3.11-slim

WORKDIR /app

# System deps for pyarrow + httpx
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY prepare.py strategy.py bot.py research.py emergency_close.py ./
COPY db/schema.sql ./db/schema.sql

# Data + logs persisted via volume
VOLUME ["/app/db", "/app/data"]

# Default command = champion bot. Override with `docker compose run research` etc.
CMD ["python", "-u", "bot.py"]
