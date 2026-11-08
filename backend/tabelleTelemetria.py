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
