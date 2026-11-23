FROM python:3.11-slim

WORKDIR /app

# Installa le dipendenze prima di copiare il codice per sfruttare la cache Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py .

# -u disabilita il buffering di stdout così vedi subito i print in "docker logs"
CMD ["python", "-u", "worker.py"]
