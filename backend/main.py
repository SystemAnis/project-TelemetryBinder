import os 
from flask import Flask
from database import db
from tabelleTelemetria import datiTelemetrici
from endpoint_API import api_telemetry

# avvio dell'app Flask
app = Flask(__name__)

# Configurazione per usare SQLite 3.
# In Docker DB_DATA_DIR punta a /data (volume esterno ad /app),
# in locale viene usata la cartella backend/db_data.
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.environ.get('DB_DATA_DIR', os.path.join(basedir, 'db_data'))
os.makedirs(db_path, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(db_path, 'telemetry.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Collego il database all'app
db.init_app(app)

# Creazione automatica del file SQLite 3 e delle tabelle (al primo avvio)
with app.app_context():
    db.create_all()
    print("Database SQLite3 inizializzato con successo!")
    
# Le altre rotte verrano aggiunte qui
app.register_blueprint(api_telemetry)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)