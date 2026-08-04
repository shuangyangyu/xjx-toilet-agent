FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

COPY requirements.txt .
RUN pip install --no-cache-dir \
        "paho-mqtt>=2.1.0,<3" \
        "pydantic-settings>=2.2.0" \
        "pycryptodome>=3.20.0" \
        "cryptography>=35" \
        "construct>=2.10.56,<3" \
        attrs \
        "PyYAML>=5,<7" \
        "tqdm>=4,<5" \
        "appdirs>=1,<2" \
        "defusedxml>=0,<1" \
        pytz \
        python-dateutil \
        croniter \
        click \
        ifaddr \
        zeroconf \
    && pip install --no-cache-dir --no-deps "python-miio>=0.5.12"

COPY src ./src

CMD ["python", "-m", "xjx_toilet_agent", "run"]
