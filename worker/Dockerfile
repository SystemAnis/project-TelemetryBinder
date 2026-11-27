FROM python:3.11-slim

WORKDIR /app

# Installo le dipendenze prima di copiare il codice: se il codice cambia,
# Docker riusa questo passaggio e la build è più veloce.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py .

# -u disabilita la bufferizzazione dell'output: i print compaiono subito in "docker logs".
CMD ["python", "-u", "worker.py"]
