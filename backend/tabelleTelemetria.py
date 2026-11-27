from database import db
from datetime import datetime

# Tabella che contiene tutti i dati di telemetria ricevuti dai sensori.
class datiTelemetrici(db.Model):
    __tablename__ = 'telemetry_records'

    # Numero progressivo assegnato automaticamente a ogni record.
    id = db.Column(db.Integer, primary_key=True)
    # Nome del dispositivo che ha inviato il dato (es. "sensore_server_1").
    sensor_id = db.Column(db.String(50), nullable=False)
    # Tipo di misura ricevuta (es. "temperatura", "umidita", "utilizzo_ram").
    metric = db.Column(db.String(50), nullable=False)
    # Valore numerico della misura (es. 32.5, 78, 67), salvato come testo nella colonna.
    value = db.Column(db.String(50), nullable=False)
    # Stato calcolato dall'API confrontando il valore con le soglie: "OK", "WARNING" o "CRITICAL".
    status = db.Column(db.String(50), default="OK")

    # Data e ora del salvataggio, salvata in UTC (es. "2026-11-25 10:30:00").
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # Converte il record in un dizionario, così Flask può restituirlo come JSON.
    def to_dict(self):
        return {
            "id": self.id,
            "sensor_id": self.sensor_id,
            "metric": self.metric,
            "value": self.value,
            "status": self.status,

            # La data resta in UTC; la dashboard la converte nell'ora italiana.
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }

# Tabella con le soglie di allarme: una riga per il Default e una per ogni sensore personalizzato.
class configurazioneAlert(db.Model):
    __tablename__ = 'alert_config'

    # Numero progressivo assegnato automaticamente a ogni configurazione.
    id = db.Column(db.Integer, primary_key=True)
    # Identificativo del dispositivo a cui appartengono le soglie.
    # "default" indica la configurazione usata dai sensori che non hanno impostazioni proprie.
    sensor_id = db.Column(db.String(50), nullable=False, unique=True, default="default")
    # Temperatura massima consentita (es. 60.0 °C).
    tempMax = db.Column(db.Float, default=60.0, nullable=False)
    # Nel database la colonna storica si chiama "umiditàMax", ma nel codice e nel JSON
    # uso "umiditaMax" (senza accento) per evitare problemi di encoding.
    # Umidità massima consentita (es. 70.0 %).
    umiditaMax = db.Column('umiditàMax', db.Float, default=70.0, nullable=False)
    # Percentuale massima di utilizzo RAM consentita (es. 90.0 %).
    ramMax = db.Column(db.Float, default=90.0, nullable=False)
    # Se è True gli avvisi sono attivi; se è False lo stato dei dati resta sempre "OK".
    alertsEnabled = db.Column(db.Boolean, default=True, nullable=False)

    # Converte la configurazione in un dizionario, così Flask può restituirla come JSON.
    def to_dict(self):
        return {
            "sensor_id": self.sensor_id,
            "tempMax": self.tempMax,
            "umiditaMax": self.umiditaMax,
            "ramMax": self.ramMax,
            "alertsEnabled": self.alertsEnabled
        }
