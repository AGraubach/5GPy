FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY split72_simulation.py .
COPY scenarios ./scenarios

RUN useradd --create-home simulator \
    && mkdir -p /app/results \
    && chown -R simulator:simulator /app

USER simulator

CMD ["python", "split72_simulation.py", "--config", "scenarios/split72_topology.json", "--output", "results/split72_results.json", "--csv", "results/split72_packets.csv", "--plots-dir", "results/plots", "--strict"]
