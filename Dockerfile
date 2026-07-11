FROM python:3.11-slim

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Tokyo

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["./entrypoint.sh"]
