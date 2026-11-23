from database import db
from datetime import datetime

class datiTelemetrici(db.Model):
    __tablename__ = 'telemetry_records'
    
    id = db.Column(db.Integer, primary_key=True)
    sensor_id = db.Column(db.String(50), nullable=False) # es: "sensoreCPU_01"
    metric = db.Column(db.String(50), nullable=False)    # es: "temperatura"
    value = db.Column(db.String(50), nullable=False)     # es: valore in numero - 32, 78, 67
    status = db.Column(db.String(50), default="OK")      # STATO: "OK", "WARNING", "CRITICAL"
    
    # Viene salvata in automatico l'ora in cui viene salvato il record
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "sensor_id": self.sensor_id,
            "metric": self.metric,
            "value": self.value,
            "status": self.status,
            
            # Formatto la data in un una stringa con un formato più leggibile
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }

class configurazioneAlert(db.Model):
    __tablename__ = 'alert_config'
    
    id = db.Column(db.Integer, primary_key=True)
    # Identificativo del dispositivo a cui appartengono le sogle 
    sensor_id = db.Column(db.String(50), nullable=False, unique=True, default="default")
    tempMax = db.Column(db.Float, default=60.0, nullable=False)  # Temperatura massima consentita
    # Nel database la colonna storica si chiama "umiditàMax", ma nel codice e nel JSON
    # uso "umiditaMax" (senza accento) per evitare problemi di encoding.
    umiditaMax = db.Column('umiditàMax', db.Float, default=70.0, nullable=False)
    ramMax = db.Column(db.Float, default=90.0, nullable=False)  # Percentuale massima di utilizzo RAM consentita
    alertsEnabled = db.Column(db.Boolean, default=True, nullable=False)  # Abilita o disabilita gli alert
    
    def to_dict(self):
        return {
            "sensor_id": self.sensor_id,
            "tempMax": self.tempMax,
            "umiditaMax": self.umiditaMax,
            "ramMax": self.ramMax,
            "alertsEnabled": self.alertsEnabled
        }