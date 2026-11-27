from flask import Blueprint, request, jsonify, Response
from sqlalchemy import inspect, text
from database import db
from tabelleTelemetria import datiTelemetrici, configurazioneAlert
import csv
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Creo un Blueprint, cioè un gruppo di rotte API separato dal file principale dell'app.
api_telemetry = Blueprint('api_telemetry', __name__)

# Soglie usate la prima volta che viene creata la configurazione di default:
# temperatura 60 °C, umidità 70 %, RAM 90 %.
TEMP_MAX_DEFAULT = 60.0
UMIDITA_MAX_DEFAULT = 70.0
RAM_MAX_DEFAULT = 90.0

# Il database salva le date in UTC (il fuso orario di riferimento),
# mentre la dashboard mostra le date italiane.
FUSO_ITALIA = ZoneInfo('Europe/Rome')

# Evita di controllare la migrazione del database a ogni richiesta.
migrazioneEseguita = False


# Converte una data italiana (YYYY-MM-DD) nel limite UTC corrispondente.
# In questo modo il filtro date del CSV usa lo stesso giorno mostrato nella
# tabella della dashboard, anche quando il record cade a cavallo della mezzanotte.
# Esempio: la mezzanotte italiana corrisponde alle 23:00 UTC del giorno prima
# (o alle 22:00 durante l'ora legale).
def data_italiana_a_utc(data_str, fine=False):
    giorno = datetime.fromisoformat(data_str)
    if fine:
        giorno = giorno.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        giorno = giorno.replace(hour=0, minute=0, second=0, microsecond=0)
    return giorno.replace(tzinfo=FUSO_ITALIA).astimezone(timezone.utc).replace(tzinfo=None)


# Aggiunge la colonna sensor_id se il database SQLite è stato creato con una
# versione precedente dell'app, quella senza soglie per singolo sensore.
def migrazione_config():
    global migrazioneEseguita
    if migrazioneEseguita:
        return

    inspector = inspect(db.engine)
    if 'alert_config' in inspector.get_table_names():
        colonne = [col['name'] for col in inspector.get_columns('alert_config')]
        if 'sensor_id' not in colonne:
            # Rimuovo eventuali righe duplicate: ogni sensore deve avere una sola configurazione.
            db.session.execute(text("DELETE FROM alert_config WHERE id NOT IN (SELECT MIN(id) FROM alert_config)"))
            db.session.execute(text("ALTER TABLE alert_config ADD COLUMN sensor_id VARCHAR(50)"))
            # Le vecchie righe non hanno sensor_id: le assegno alla configurazione "default".
            db.session.execute(text("UPDATE alert_config SET sensor_id = 'default' WHERE sensor_id IS NULL OR sensor_id = ''"))
            # Creo un indice univoco per impedire due configurazioni dello stesso sensore.
            db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_alert_config_sensor_id ON alert_config (sensor_id)"))
            db.session.commit()

    migrazioneEseguita = True


# Restituisce la configurazione degli alert per un sensore specifico.
# Se il sensore non ha una configurazione propria, usa quella di default.
# Con crea_se_manca=True crea una configurazione dedicata copiando i valori di default.
def ottieni_crea_config(sensor_id='default', crea_se_manca=False):
    migrazione_config()

    target_id = str(sensor_id).strip() if sensor_id else 'default'
    if not target_id:
        target_id = 'default'

    # 1. Recupero o creo la configurazione base "default".
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

    # 2. Cerco una configurazione personalizzata per il singolo sensore.
    config_sensore = configurazioneAlert.query.filter_by(sensor_id=target_id).first()
    if config_sensore:
        return config_sensore

    # 3. Se sto salvando (POST/PUT), creo una configurazione dedicata copiando i valori di default.
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

    # Altrimenti uso le soglie di default.
    return default_cfg


# Calcola lo stato del dato confrontandolo con le soglie: "OK", "WARNING" o "CRITICAL".
def calcola_status(metric, value, config):
    # Se gli avvisi sono disattivati per questo dispositivo, nessun dato va in allarme.
    if not config.alertsEnabled:
        return 'OK'

    if metric == 'temperatura':
        # Con tempMax 60 °C: da 60 a 64.9 è WARNING, da 65 in su è CRITICAL.
        if value >= config.tempMax + 5.0:
            return 'CRITICAL'
        if value >= config.tempMax:
            return 'WARNING'

    elif metric == 'umidita':
        # Con umiditaMax 70 %: da 70 a 79.9 è WARNING, da 80 in su è CRITICAL.
        # La soglia critica non supera mai il 100 %.
        soglia_critica = min(config.umiditaMax + 10.0, 100.0)
        if value >= soglia_critica:
            return 'CRITICAL'
        if value >= config.umiditaMax:
            return 'WARNING'

    elif metric == 'utilizzo_ram':
        # Con ramMax 90 %: da 90 a 94.9 è WARNING, da 95 in su è CRITICAL.
        # La soglia critica non supera mai il 100 %.
        soglia_critica = min(config.ramMax + 5.0, 100.0)
        if value >= soglia_critica:
            return 'CRITICAL'
        if value >= config.ramMax:
            return 'WARNING'

    return 'OK'


# Legge il primo campo presente tra le chiavi indicate e lo converte in float.
# Se il campo non c'è o non contiene un numero, restituisce None.
def leggi_float(dati, chiavi):
    for chiave in chiavi:
        if chiave in dati:
            try:
                return float(dati[chiave])
            except (TypeError, ValueError):
                return None
    return None


# Converte in booleano anche i valori che arrivano come stringa ('true', 'false', ...).
# Le stringhe 'true', '1', 'yes', 'on', 'si' e 'sì' valgono True; le altre stringhe valgono False.
def leggi_booleano(valore):
    if isinstance(valore, bool):
        return valore
    if isinstance(valore, str):
        return valore.strip().lower() in ('true', '1', 'yes', 'on', 'si', 'sì')
    return bool(valore)


# Endpoint POST: riceve un dato dal sensore e lo salva nel database.
@api_telemetry.route('/api/telemetry', methods=['POST'])
def ricevi_dati():
    # Leggo il JSON inviato dal sensore.
    # silent=True evita che Flask risponda con una pagina HTML di errore se il JSON non è valido:
    # in quel caso dati vale None e rispondo con un errore JSON.
    dati = request.get_json(silent=True)

    # Controllo che ci siano tutti i campi richiesti.
    if not isinstance(dati, dict) or 'sensor_id' not in dati or 'metric' not in dati or 'value' not in dati:
        return jsonify({'error': 'Dati mancanti nel payload JSON'}), 400

    sensor_id = str(dati['sensor_id']).strip()
    metric = str(dati['metric']).strip().lower()

    # Normalizzo il nome della metrica: "umidità" diventa "umidita",
    # così nel database c'è un solo nome per la stessa misura.
    if metric == 'umidità':
        metric = 'umidita'

    # Controllo che sensor_id e metric non siano vuoti.
    if not sensor_id or not metric:
        return jsonify({'error': "I campi 'sensor_id' e 'metric' non possono essere vuoti"}), 400

    # Converto il valore in numero; se non è possibile, restituisco un errore.
    try:
        value = float(dati['value'])
    except (TypeError, ValueError):
        return jsonify({'error': "Il campo 'value' deve essere un numero"}), 400

    # Calcolo lo stato usando le soglie del dispositivo (o quelle di default) e lo switch "Avvisi attivi".
    config = ottieni_crea_config(sensor_id=sensor_id, crea_se_manca=False)
    status = calcola_status(metric, value, config)

    # Creo il record da salvare nel database.
    nuovoDato = datiTelemetrici(
        sensor_id=sensor_id,
        metric=metric,
        value=value,
        status=status,
    )

    # Salvo il record nel database.
    db.session.add(nuovoDato)
    db.session.commit()

    return jsonify({'messaggio': 'Dati ricevuti e salvati con successo', 'status': status}), 201


# Endpoint GET: restituisce tutti i dati salvati nel database.
@api_telemetry.route('/api/telemetry', methods=['GET'])
def ottieni_dati():
    # Filtro per sensore usando il parametro nell'URL (es. /api/telemetry?sensor_id=sensore_server_1).
    sensor_id = request.args.get('sensor_id')

    if sensor_id:
        # Prendo solo i dati del sensore richiesto, dal più vecchio al più recente.
        # L'ordine crescente serve perché la dashboard usa l'ultimo record come valore attuale.
        dati = (
            datiTelemetrici.query
            .filter_by(sensor_id=sensor_id)
            .order_by(datiTelemetrici.id.asc())
            .all()
        )
    else:
        # Nessun filtro: prendo tutti i dati, dal più vecchio al più recente.
        dati = datiTelemetrici.query.order_by(datiTelemetrici.id.asc()).all()

    # Converto ogni record in un dizionario JSON da restituire al frontend.
    return jsonify([r.to_dict() for r in dati]), 200


# Endpoint GET: restituisce l'elenco dei sensori presenti nel database.
@api_telemetry.route('/api/sensors', methods=['GET'])
def elenco_sensori():
    sensori = (
        db.session.query(datiTelemetrici.sensor_id)
        .distinct()
        .order_by(datiTelemetrici.sensor_id)
        .all()
    )
    return jsonify([s[0] for s in sensori]), 200


# Endpoint GET: restituisce la configurazione degli alert (globale o per singolo sensor_id).
@api_telemetry.route('/api/config', methods=['GET'])
def ottieni_config():
    # Leggo il sensore richiesto; se non c'è o è vuoto uso "default".
    sensor_id = request.args.get('sensor_id', 'default').strip() or 'default'
    config = ottieni_crea_config(sensor_id=sensor_id, crea_se_manca=False)
    risposta = config.to_dict()
    risposta['sensor_id'] = sensor_id
    risposta['is_default'] = (config.sensor_id != sensor_id or sensor_id == 'default')
    return jsonify(risposta), 200


# Endpoint POST/PUT: aggiorna (o ripristina al Default) la configurazione degli alert.
@api_telemetry.route('/api/config', methods=['POST', 'PUT'])
def aggiorna_config():
    # Leggo il JSON inviato dalla dashboard.
    dati = request.get_json(silent=True)
    if not isinstance(dati, dict) or not dati:
        return jsonify({'error': 'Dati mancanti nel payload JSON'}), 400

    sensor_id = str(dati.get('sensor_id', 'default')).strip() or 'default'

    # Se il frontend richiede il ripristino, elimina l'eccezione del sensore e restituisce il Default.
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

    # Controllo che i valori inviati siano numeri validi.
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


# Endpoint DELETE: elimina le soglie personalizzate di un dispositivo riportandolo al Default.
@api_telemetry.route('/api/config', methods=['DELETE'])
def ripristina_config():
    migrazione_config()
    sensor_id = request.args.get('sensor_id', '').strip()

    if not sensor_id or sensor_id == 'default':
        return jsonify({'error': "Specifica un dispositivo valido da ripristinare al Default"}), 400

    # Cerco ed elimino l'eventuale riga personalizzata del dispositivo.
    config_sensore = configurazioneAlert.query.filter_by(sensor_id=sensor_id).first()
    if config_sensore:
        db.session.delete(config_sensore)
        db.session.commit()

    # Restituisco le soglie Default che il dispositivo tornerà a ereditare.
    default_cfg = ottieni_crea_config(sensor_id='default', crea_se_manca=False)
    risposta = default_cfg.to_dict()
    risposta['sensor_id'] = sensor_id
    risposta['is_default'] = True

    return jsonify({
        'messaggio': f"Soglie di '{sensor_id}' ripristinate al Default",
        'config': risposta,
    }), 200


# Endpoint GET: esporta in CSV i dati con stato diverso da "OK".
@api_telemetry.route('/api/telemetry/export', methods=['GET'])
def esporta_anomalie_csv():
    inizio = request.args.get('inizio')
    fine = request.args.get('fine')
    sensor_ids_raw = request.args.getlist('sensor_id')

    query = datiTelemetrici.query.filter(datiTelemetrici.status != 'OK')

    # Filtro per i dispositivi selezionati nella dashboard.
    lista_sensori = []
    for item in sensor_ids_raw:
        lista_sensori.extend([s.strip() for s in item.split(',') if s.strip()])

    if lista_sensori:
        query = query.filter(datiTelemetrici.sensor_id.in_(lista_sensori))
    elif 'sensor_id' in request.args:
        # Se il parametro sensor_id è presente ma vuoto (nessuna checkbox spuntata).
        query = query.filter(datiTelemetrici.id == -1)

    # Converto le date italiane in UTC per confrontarle con i timestamp salvati nel database.
    if inizio:
        try:
            query = query.filter(datiTelemetrici.timestamp >= data_italiana_a_utc(inizio))
        except ValueError:
            return jsonify({'error': "Data di inizio non valida"}), 400
    if fine:
        try:
            query = query.filter(datiTelemetrici.timestamp <= data_italiana_a_utc(fine, fine=True))
        except ValueError:
            return jsonify({'error': "Data di fine non valida"}), 400

    record = query.order_by(datiTelemetrici.timestamp.desc()).all()

    # Creazione del CSV in memoria.
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Data/Ora', 'Dispositivo', 'Metrica', 'Stato', 'Valore'])

    for r in record:
        writer.writerow([
            # Converto il timestamp UTC nell'ora italiana mostrata nella dashboard.
            r.timestamp.replace(tzinfo=timezone.utc).astimezone(FUSO_ITALIA).strftime("%Y-%m-%d %H:%M:%S"),
            r.sensor_id,
            r.metric,
            r.status,
            r.value
        ])
    return Response(
        '\ufeff' + output.getvalue(),  # Il \ufeff serve per far riconoscere correttamente l'UTF-8 a Excel. Il delimitatore ; è quello che Excel italiano gestisce meglio.
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=anomalie.csv'}
    )
