import os
import json
import time
import requests
import paho.mqtt.client as mqtt

# Parametri letti dalle variabili d'ambiente del docker-compose.yml.
BROKER_HOST = os.getenv("MQTT_BROKER", "hivemq")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "telemetry/#")
API_URL = os.getenv("API_URL", "http://api:5000/api/telemetry")


def on_connect(client, userdata, flags, reason_code, properties):
    """Callback eseguita ogni volta che il worker si connette (o riconnette) a HiveMQ."""
    if reason_code == 0:
        print(f"[MQTT-WORKER] Connesso a HiveMQ ({BROKER_HOST}:{BROKER_PORT})")
        # Mi iscrivo a tutti i sottotopic di telemetry/ (es. telemetry/sensore_server_1).
        client.subscribe(MQTT_TOPIC)
        print(f"[MQTT-WORKER] Sottoscritto al topic: {MQTT_TOPIC}")
    else:
        print(f"[MQTT-WORKER] Errore di connessione al broker (codice: {reason_code})")


def on_message(client, userdata, msg):
    """Callback eseguita alla ricezione di ogni pacchetto MQTT."""
    # Il payload arriva come bytes: lo trasformo in testo UTF-8.
    raw_payload = msg.payload.decode("utf-8", errors="replace")
    print(f"[MQTT-WORKER] Messaggio ricevuto su '{msg.topic}': {raw_payload}")

    try:
        dati = json.loads(raw_payload)
    except json.JSONDecodeError:
        print("[MQTT-WORKER] Payload scartato: non è un JSON valido")
        return

    # Se il JSON non include sensor_id, provo a ricavarlo dal topic
    # (es. telemetry/sensore_server_1 -> sensore_server_1).
    if "sensor_id" not in dati:
        parti_topic = msg.topic.split("/")
        if len(parti_topic) >= 2 and parti_topic[1]:
            dati["sensor_id"] = parti_topic[1]

    # Inoltro il dato all'API Flask: lei calcola lo stato con le soglie e salva su SQLite.
    try:
        risposta = requests.post(API_URL, json=dati, timeout=5)
        if risposta.status_code in (200, 201):
            esito = risposta.json()
            print(f"[MQTT-WORKER] Salvato su DB -> status={esito.get('status')}")
        else:
            print(f"[MQTT-WORKER] Errore API ({risposta.status_code}): {risposta.text}")
    except requests.RequestException as exc:
        print(f"[MQTT-WORKER] Impossibile raggiungere l'API Flask: {exc}")


def main():
    # Uso CallbackAPIVersion.VERSION2, richiesta da paho-mqtt >= 2.0.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="telemetry-mqtt-worker")
    client.on_connect = on_connect
    client.on_message = on_message

    # Attendo che il container HiveMQ abbia completato l'avvio:
    # riprovo la connessione ogni 3 secondi finché non risponde.
    while True:
        try:
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
            break
        except Exception as exc:
            print(f"[MQTT-WORKER] HiveMQ non ancora pronto ({exc}), nuovo tentativo tra 3s...")
            time.sleep(3)

    # Resto in ascolto per sempre; la libreria gestisce da sola le riconnessioni.
    client.loop_forever()


if __name__ == "__main__":
    main()
