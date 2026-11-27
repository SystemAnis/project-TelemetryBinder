import os
from flask import Flask
from database import db
from tabelleTelemetria import datiTelemetrici, configurazioneAlert
from endpoint_API import api_telemetry

# Creo l'applicazione Flask.
app = Flask(__name__)

# Configurazione del database SQLite 3.
# In Docker DB_DATA_DIR punta a /data, che è collegata alla cartella ./db_data del computer:
# così il database resta anche quando il container viene ricreato.
# In locale, invece, uso la cartella backend/db_data.
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.environ.get('DB_DATA_DIR', os.path.join(basedir, 'db_data'))
os.makedirs(db_path, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(db_path, 'telemetry.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Collego il database all'app Flask.
db.init_app(app)

# Al primo avvio creo automaticamente il file SQLite 3 e le tabelle.
with app.app_context():
    db.create_all()
    print("Database SQLite3 inizializzato con successo!")

# Registro le rotte dell'API definite nel file endpoint_API.py.
app.register_blueprint(api_telemetry)

# CORS: permette alla dashboard Node-RED (porta 1880) di chiamare le API Flask (porta 5000)
# direttamente dal browser, anche se i due servizi girano su porte diverse.
@app.after_request
def aggiungi_header_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    return response


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
