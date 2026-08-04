FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y gcc \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY src ./src

CMD ["python", "-m", "xjx_toilet_agent", "run"]
