from flask import Blueprint, request, jsonify
from database import db
from tabelleTelemetria import datiTelemetrici

# Inizializzo il Blueprint per separare le rotte dell'API dal file principale dell'app
api_telemetry = Blueprint('api_telemetry', __name__)

# Enpoint POST: riceve i dati dal sensore e li salva nel database
@api_telemetry.route('/api/telemetry', methods=['POST'])

def ricevi_dati():
    # prende il payload JSON dalla richiesta
    dati = request.get_json()
    
    # controllo che ci siano tutti i campi richiesti
    if not dati or 'sensor_id' not in dati or 'metric' not in dati or 'value' not in dati:
        return jsonify({'error': 'Dati mancanti nel payload JSON'}), 400
    
    sensor_id = dati['sensor_id']
    metric = dati['metric']
    value = float(dati['value'])
    
    # Logica per analizzare i dati impostandoli secondo lo status dell'allarme
    status = 'OK'
    if metric == "temperatura" and value >= 45.0:
        status = 'CRITICAL'
    elif metric == "utilizzo_ram" and value >= 90.0:
        status = 'WARNING'
        
    # Creazione dell'oggetto ORM per SQLite3
    nuovoDato = datiTelemetrici(
        sensor_id=sensor_id,
        metric=metric,
        value=value,
        status=status
    )
    
    # Scrittura nel database
    db.session.add(nuovoDato)
    db.session.commit()
    
    return jsonify({"messaggio": "Dati ricevuti e salvati con successo", "status": status}), 201

# Endpoint GET: restituisce tutti i dati salvati nel database
@api_telemetry.route('/api/telemetry', methods=['GET'])

def ottieni_dati():
    # Filtraggio dei dati tramite l'URL (es. /api/telemetry?sensor_id=cpu_01)
    sensor_id = request.args.get('sensor_id')
    
    if sensor_id:
        # SELECT * FROM datiTelemetrici WHERE sensor_id = sensor_id
        dati = datiTelemetrici.query.filter_by(sensor_id=sensor_id).all()
    else:
        # SELECT * FROM datiTelemetrici
        dati = datiTelemetrici.query.all()
    
    # dati: lista di oggetti ORM,
    # for r in dati: prende un oggetto alla volta dalla lista "dati"
    # r.to_dict(): converte l'oggetto ORM in un dizionario (es: {"id": 1, "nome": "Mario"})
    return jsonify([r.to_dict() for r in dati]), 200