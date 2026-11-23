from flask import Blueprint, request, jsonify, Response
from sqlalchemy import inspect, text
from database import db
from tabelleTelemetria import datiTelemetrici, configurazioneAlert
import csv
import io
from datetime import datetime

# Inizializzo il Blueprint per separare le rotte dell'API dal file principale dell'app
api_telemetry = Blueprint('api_telemetry', __name__)

# Valori di default usati la prima volta che viene creata la configurazione
TEMP_MAX_DEFAULT = 60.0
UMIDITA_MAX_DEFAULT = 70.0
RAM_MAX_DEFAULT = 90.0

migrazioneEseguita = False


def migrazione_config():
    """Aggiunge automaticamente la colonna sensor_id se il DB SQLite proviene dalla versione precedente."""
    global migrazioneEseguita
    if migrazioneEseguita:
        return

    inspector = inspect(db.engine)
    if 'alert_config' in inspector.get_table_names():
        colonne = [col['name'] for col in inspector.get_columns('alert_config')]
        if 'sensor_id' not in colonne:
            # Rimuove eventuali righe duplicate residue prima di creare l'indice univoco
            db.session.execute(text("DELETE FROM alert_config WHERE id NOT IN (SELECT MIN(id) FROM alert_config)"))
            db.session.execute(text("ALTER TABLE alert_config ADD COLUMN sensor_id VARCHAR(50)"))
            db.session.execute(text("UPDATE alert_config SET sensor_id = 'default' WHERE sensor_id IS NULL OR sensor_id = ''"))
            db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_alert_config_sensor_id ON alert_config (sensor_id)"))
            db.session.commit()

    migrazioneEseguita = True


def ottieni_crea_config(sensor_id='default', crea_se_manca=False):
    """Restituisce la configurazione degli alert per un dispositivo specifico (o 'default')."""
    migrazione_config()

    target_id = str(sensor_id).strip() if sensor_id else 'default'
    if not target_id:
        target_id = 'default'

    # 1. Recupera o crea sempre la configurazione base 'default'
    default_cfg = configurazioneAlert.query.filter_by(sensor_id='default').first()
    if not default_cfg:
        default_cfg = configurazioneAlert(
            sensor_id='default',
            tempMax=TEMP_MAX_DEFAULT,
            umiditaMax=UMIDITA_MAX_DEFAULT,
            ramMax=RAM_MAX_DEFAULT,
            alertsEnabled=True,
        )
        db.session.add(default_cfg)
        db.session.commit()

    if target_id == 'default':
        return default_cfg

    # 2. Cerca una configurazione personalizzata per il singolo sensore
    config_sensore = configurazioneAlert.query.filter_by(sensor_id=target_id).first()
    if config_sensore:
        return config_sensore

    # 3. In fase di salvataggio (POST/PUT), crea una riga dedicata clonando i valori di default
    if crea_se_manca:
        config_sensore = configurazioneAlert(
            sensor_id=target_id,
            tempMax=default_cfg.tempMax,
            umiditaMax=default_cfg.umiditaMax,
            ramMax=default_cfg.ramMax,
            alertsEnabled=default_cfg.alertsEnabled,
        )
        db.session.add(config_sensore)
        db.session.commit()
        return config_sensore

    # Altrimenti usa le soglie di default come fallback
    return default_cfg


def calcola_status(metric, value, config):
    """Calcola lo stato del dato su due livelli progressivi: WARNING e CRITICAL."""
    # Se gli avvisi sono disattivati per questo dispositivo, nessun dato va in allarme
    if not config.alertsEnabled:
        return 'OK'

    if metric == 'temperatura':
        # Superata la soglia -> WARNING; superata di almeno +5.0 °C -> CRITICAL
        if value >= config.tempMax + 5.0:
            return 'CRITICAL'
        if value >= config.tempMax:
            return 'WARNING'

    elif metric == 'umidita':
        # Superata la soglia -> WARNING; superata di +10% (o al 100%) -> CRITICAL
        soglia_critica = min(config.umiditaMax + 10.0, 100.0)
        if value >= soglia_critica:
            return 'CRITICAL'
        if value >= config.umiditaMax:
            return 'WARNING'

    elif metric == 'utilizzo_ram':
        # Superata la soglia -> WARNING; superata di +5% (o saturazione al 100%) -> CRITICAL
        soglia_critica = min(config.ramMax + 5.0, 100.0)
        if value >= soglia_critica:
            return 'CRITICAL'
        if value >= config.ramMax:
            return 'WARNING'

    return 'OK'


def leggi_float(dati, chiavi):
    """Legge il primo campo numerico presente nel payload e ne restituisce il valore."""
    for chiave in chiavi:
        if chiave in dati:
            try:
                return float(dati[chiave])
            except (TypeError, ValueError):
                return None
    return None


def leggi_booleano(valore):
    """Converte in booleano anche i valori che arrivano come stringa ('true', 'false', ...)."""
    if isinstance(valore, bool):
        return valore
    if isinstance(valore, str):
        return valore.strip().lower() in ('true', '1', 'yes', 'on', 'si', 'sì')
    return bool(valore)


# Endpoint POST: riceve i dati dal sensore e li salva nel database
@api_telemetry.route('/api/telemetry', methods=['POST'])
def ricevi_dati():
    # Prende il payload JSON dalla richiesta (silent evita errori HTML con JSON non valido)
    dati = request.get_json(silent=True)

    # Controllo che ci siano tutti i campi richiesti
    if not isinstance(dati, dict) or 'sensor_id' not in dati or 'metric' not in dati or 'value' not in dati:
        return jsonify({'error': 'Dati mancanti nel payload JSON'}), 400

    sensor_id = str(dati['sensor_id']).strip()
    metric = str(dati['metric']).strip().lower()

    # Normalizzo il nome della metrica per gestire anche la versione accentata
    if metric == 'umidità':
        metric = 'umidita'

    try:
        value = float(dati['value'])
    except (TypeError, ValueError):
        return jsonify({'error': "Il campo 'value' deve essere un numero"}), 400

    # Calcolo lo stato usando le soglie specifiche del dispositivo (o default) e lo switch "Avvisi attivi"
    config = ottieni_crea_config(sensor_id=sensor_id, crea_se_manca=False)
    status = calcola_status(metric, value, config)

    # Creazione dell'oggetto ORM per SQLite3
    nuovoDato = datiTelemetrici(
        sensor_id=sensor_id,
        metric=metric,
        value=value,
        status=status,
    )

    # Scrittura nel database
    db.session.add(nuovoDato)
    db.session.commit()

    return jsonify({'messaggio': 'Dati ricevuti e salvati con successo', 'status': status}), 201


# Endpoint GET: restituisce tutti i dati salvati nel database
@api_telemetry.route('/api/telemetry', methods=['GET'])
def ottieni_dati():
    # Filtraggio dei dati tramite l'URL (es. /api/telemetry?sensor_id=cpu_01)
    sensor_id = request.args.get('sensor_id')

    if sensor_id:
        # SELECT * FROM telemetry_records WHERE sensor_id = sensor_id
        dati = datiTelemetrici.query.filter_by(sensor_id=sensor_id).all()
    else:
        # SELECT * FROM telemetry_records
        dati = datiTelemetrici.query.all()

    # Lista di oggetti ORM convertiti in dizionari JSON
    return jsonify([r.to_dict() for r in dati]), 200


# Endpoint GET: restituisce l'elenco dei sensori presenti nel database
@api_telemetry.route('/api/sensors', methods=['GET'])
def elenco_sensori():
    sensori = (
        db.session.query(datiTelemetrici.sensor_id)
        .distinct()
        .order_by(datiTelemetrici.sensor_id)
        .all()
    )
    return jsonify([s[0] for s in sensori]), 200


# Endpoint GET: restituisce la configurazione degli alert (globale o per singolo sensor_id)
@api_telemetry.route('/api/config', methods=['GET'])
def ottieni_config():
    sensor_id = request.args.get('sensor_id', 'default').strip() or 'default'
    config = ottieni_crea_config(sensor_id=sensor_id, crea_se_manca=False)
    risposta = config.to_dict()
    risposta['sensor_id'] = sensor_id
    risposta['is_default'] = (config.sensor_id != sensor_id or sensor_id == 'default')
    return jsonify(risposta), 200


# Endpoint POST/PUT: aggiorna (o ripristina al Default) la configurazione degli alert
@api_telemetry.route('/api/config', methods=['POST', 'PUT'])
def aggiorna_config():
    dati = request.get_json(silent=True)
    if not isinstance(dati, dict) or not dati:
        return jsonify({'error': 'Dati mancanti nel payload JSON'}), 400

    sensor_id = str(dati.get('sensor_id', 'default')).strip() or 'default'

    # Se il frontend richiede il ripristino, elimina l'eccezione del sensore e restituisce il Default
    if leggi_booleano(dati.get('reset', False)):
        if sensor_id == 'default':
            return jsonify({'error': "Specifica un dispositivo valido da ripristinare al Default"}), 400

        migrazione_config()
        config_sensore = configurazioneAlert.query.filter_by(sensor_id=sensor_id).first()
        if config_sensore:
            db.session.delete(config_sensore)
            db.session.commit()

        default_cfg = ottieni_crea_config(sensor_id='default', crea_se_manca=False)
        risposta = default_cfg.to_dict()
        risposta['sensor_id'] = sensor_id
        risposta['is_default'] = True

        return jsonify({
            'messaggio': f"Soglie di '{sensor_id}' ripristinate al Default",
            'config': risposta,
        }), 200

    config = ottieni_crea_config(sensor_id=sensor_id, crea_se_manca=True)

    # Aggiorno i valori della configurazione se presenti nel payload.
    # Accetto sia "umiditaMax" (usato dal frontend) sia "umiditàMax" (nome storico).
    temp_max = leggi_float(dati, ('tempMax',))
    umidita_max = leggi_float(dati, ('umiditaMax', 'umiditàMax'))
    ram_max = leggi_float(dati, ('ramMax',))

    if 'tempMax' in dati and temp_max is None:
        return jsonify({'error': "Il campo 'tempMax' deve essere un numero"}), 400
    if ('umiditaMax' in dati or 'umiditàMax' in dati) and umidita_max is None:
        return jsonify({'error': "Il campo 'umiditaMax' deve essere un numero"}), 400
    if 'ramMax' in dati and ram_max is None:
        return jsonify({'error': "Il campo 'ramMax' deve essere un numero"}), 400

    if temp_max is not None:
        config.tempMax = temp_max
    if umidita_max is not None:
        config.umiditaMax = umidita_max
    if ram_max is not None:
        config.ramMax = ram_max
    if 'alertsEnabled' in dati:
        config.alertsEnabled = leggi_booleano(dati['alertsEnabled'])

    db.session.commit()

    return jsonify({
        'messaggio': f"Configurazione aggiornata con successo per '{sensor_id}'",
        'config': config.to_dict(),
    }), 200

    # Restituisco la configurazione aggiornata in formato JSON con stato 200
    return jsonify({
        'messaggio': f"Configurazione aggiornata con successo per '{sensor_id}'",
        'config': config.to_dict(),
    }), 200
    

# Endpoint DELETE: elimina le soglie personalizzate di un dispositivo riportandolo al Default
@api_telemetry.route('/api/config', methods=['DELETE'])
def ripristina_config():
    migrazione_config()
    sensor_id = request.args.get('sensor_id', '').strip()

    if not sensor_id or sensor_id == 'default':
        return jsonify({'error': "Specifica un dispositivo valido da ripristinare al Default"}), 400

    # Cerca ed elimina l'eventuale riga personalizzata del dispositivo
    config_sensore = configurazioneAlert.query.filter_by(sensor_id=sensor_id).first()
    if config_sensore:
        db.session.delete(config_sensore)
        db.session.commit()

    # Restituisce le soglie Default che il dispositivo tornerà a ereditare
    default_cfg = ottieni_crea_config(sensor_id='default', crea_se_manca=False)
    risposta = default_cfg.to_dict()
    risposta['sensor_id'] = sensor_id
    risposta['is_default'] = True

    return jsonify({
        'messaggio': f"Soglie di '{sensor_id}' ripristinate al Default",
        'config': risposta,
    }), 200


@api_telemetry.route('/api/telemetry/export', methods=['GET'])
def esporta_anomalie_csv():
    inizio = request.args.get('inizio')
    fine = request.args.get('fine')
    sensor_ids_raw = request.args.getlist('sensor_id')

    query = datiTelemetrici.query.filter(datiTelemetrici.status != 'OK')

    # Filtra per i dispositivi selezionati nella dashboard
    lista_sensori = []
    for item in sensor_ids_raw:
        lista_sensori.extend([s.strip() for s in item.split(',') if s.strip()])

    if lista_sensori:
        query = query.filter(datiTelemetrici.sensor_id.in_(lista_sensori))
    elif 'sensor_id' in request.args:
        # Se il parametro sensor_id è presente ma vuoto (nessuna checkbox spuntata)
        query = query.filter(datiTelemetrici.id == -1)

    if inizio:
        try:
            query = query.filter(
                datiTelemetrici.timestamp >= datetime.fromisoformat(inizio + "T00:00:00")
            )
        except ValueError:
            return jsonify({'error': "Data di inizio non valida"}), 400
    if fine:
        try:
            query = query.filter(
                datiTelemetrici.timestamp <= datetime.fromisoformat(fine + "T23:59:59")
            )
        except ValueError:
            return jsonify({'error': "Data di fine non valida"}), 400

    record = query.order_by(datiTelemetrici.timestamp.desc()).all()

    # Creazione del CSV in memoria
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Data/Ora', 'Dispositivo', 'Metrica', 'Stato', 'Valore'])

    for r in record:
        writer.writerow([
            r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            r.sensor_id,
            r.metric,
            r.status,
            r.value
        ])
    return Response(
        '\ufeff' + output.getvalue(),  # Il \ufeff serve per far riconoscere correttamente l’UTF-8 a Excel. Il delimitatore ; è quello che Excel italiano gestisce meglio.
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=anomalie.csv'}
    )