# TelemetryBinder — appunti personali

> **Uso personale.** Questo file è il mio foglio di studio, non la relazione da consegnare. Non va committato né pushato su GitHub.

L'idea in una frase: **simulo tre sensori, mando i dati con MQTT a HiveMQ, un worker Python li passa a Flask, Flask li salva in SQLite e la dashboard Node-RED li mostra, li filtra e permette di configurare le soglie.**

Se il professore parte da “che cosa hai fatto?”, questa è la risposta da tenere pronta. Poi, a seconda di dove vuole andare, si apre il dettaglio.

---

## 1. La mappa del progetto

```text
┌─────────────────────────────┐
│  Node-RED — Simulatore_IoT  │
│  genera 9 valori ogni 5 s   │
└──────────────┬──────────────┘
               │ MQTT publish
               ▼
┌─────────────────────────────┐
│  HiveMQ — broker MQTT       │
│  topic telemetry/#          │
└──────────────┬──────────────┘
               │ MQTT subscribe
               ▼
┌─────────────────────────────┐
│  mqtt-worker — Python       │
│  inoltra i JSON all'API     │
└──────────────┬──────────────┘
               │ HTTP POST
               ▼
┌─────────────────────────────┐        ┌─────────────────────────────┐
│  API Flask — porta 5000     │◀───────│  Dashboard Node-RED         │
│  valida, calcola lo stato   │  HTTP  │  Control Room — porta 1880  │
│  salva e legge SQLite       │        │  gauge, grafici, tabella    │
└──────────────┬──────────────┘        └─────────────────────────────┘
               │
               ▼
┌─────────────────────────────┐
│  SQLite3                    │
│  db_data/telemetry.db       │
└─────────────────────────────┘
```

I quattro container sono:

| Container | Immagine / build | A cosa serve | Porta |
|---|---|---|---|
| `telemetry-hivemq` | `hivemq/hivemq-ce:latest` | broker MQTT | 1883 |
| `telemetry-api` | build `./backend` | API Flask + SQLite | 5000 |
| `telemetry-mqtt-worker` | build `./worker` | da MQTT a HTTP | — |
| `telemetry-nodered` | `nodered/node-red:latest` | simulatore + dashboard | 1880 |

La cosa importante: **i container si parlano usando i nomi dei servizi**, non `localhost`.

- il nodo `http request` dentro Node-RED usa `http://api:5000`;
- dentro il worker il broker è `hivemq:1883` e l'API è `http://api:5000`;
- i template della dashboard, invece, usano `http://<host-del-browser>:5000`, perché il `fetch` parte dal browser e non dal container.

Questa distinzione torna spesso: `api` è il nome del servizio nella rete Docker; `localhost` (o l'IP del computer) è il punto di vista del browser.

---

## 2. Cosa succede quando il simulatore genera un dato

Questo è il percorso completo, con i nomi dei nodi.

1. Nel tab **`Simulatore_IoT`** c'è un nodo `inject` che parte una volta all'avvio e poi ripete ogni **5 secondi**.
2. L'inject chiama la funzione **`function 3`**.
3. `function 3` crea **9 messaggi**: 3 sensori × 3 metriche (temperatura, umidità, RAM).
4. I 9 messaggi finiscono nel nodo **`mqtt out`**, che pubblica sul topic `telemetry/sensors` usando il broker **`HiveMQ Docker`** (`hivemq:1883`).
5. HiveMQ riceve i messaggi.
6. Il container **`mqtt-worker`** è iscritto a `telemetry/#`; per ogni messaggio:
   - legge il JSON;
   - se manca `sensor_id`, prova a ricavarlo dal topic;
   - fa una `POST` a `http://api:5000/api/telemetry`.
7. L'API Flask:
   - controlla che `sensor_id`, `metric` e `value` ci siano;
   - converte `value` in numero;
   - cerca la configurazione del sensore (o usa quella `default`);
   - calcola lo stato `OK`, `WARNING` o `CRITICAL`;
   - salva il record in SQLite.
8. Il dato è nel database. La dashboard non lo vede ancora: lo vedrà al prossimo giro di lettura.

I tre sensori simulati e i loro intervalli:

| Sensore | Temperatura | Umidità | RAM |
|---|---:|---:|---:|
| `sensore_server_1` | 18–27 °C | 40–60 % | 20–85 % |
| `sensore_server_2` | 18–27 °C | 40–60 % | 15–80 % |
| `sensore_edge_1` | 5–45 °C | 20–80 % | 30–90 % |

`sensore_edge_1` è quello più “variabile”: serve a far vedere che le soglie per singolo sensore hanno senso.

Se ti chiedono **“il simulatore scrive nel database?”**, la risposta è **no**. Il simulatore pubblica solo su MQTT. A scrivere è il worker che chiama l'API; l'API è l'unica che parla con SQLite.

---

## 3. Cosa succede quando apri la dashboard

La dashboard del progetto è:

**<http://localhost:1880/ui>**

La scheda che vedi si chiama **`Control Room`**. È divisa in tre gruppi:

| Gruppo | Cosa contiene |
|---|---|
| **Server Monitor** | 3 gauge a lancetta, 3 grafici a linee, filtro dispositivi |
| **Configuration & Alerts** | selettore dispositivo, 3 soglie, switch avvisi, salva, ripristina |
| **Anomaly Logs** | filtro date, pulsante CSV, tabella delle anomalie |

### 3.1 Il giro di aggiornamento

1. Nel tab **`Dashboard_Grafica`** c'è un `inject` che parte una volta e poi ripete ogni **10 secondi**.
2. L'inject manda un messaggio al nodo **`http request`**, che fa una `GET` a `http://api:5000/api/telemetry`.
3. La risposta (un array JSON con tutti i record) arriva alla funzione **`function 4`**.
4. `function 4`:
   - tiene solo i sensori selezionati nelle checkbox (`flow.get('tb_sensor_filter')`);
   - separa i record per metrica: temperatura, umidità, RAM;
   - prende l'ultimo valore di ogni metrica per i gauge;
   - tiene solo i record con stato diverso da `OK` per la tabella;
   - applica il filtro date (`flow.get('tb_log_start')` e `flow.get('tb_log_end')`);
   - converte i timestamp in ora italiana (`Europe/Rome`);
   - restituisce 4 uscite: temperatura, umidità, RAM, tabella.
5. Le 3 uscite numeriche vanno ai 3 `ui_gauge` e ai 3 `ui_chart`; la quarta va alla `ui_table`.

Quindi la dashboard **non legge direttamente SQLite**: legge l'API. L'API legge SQLite. Questo passaggio in più è voluto, perché tiene la logica in un solo punto (Flask) e lascia Node-RED fare solo la parte visiva.

### 3.2 I filtri

**Filtro dispositivi**

- Il template **`Filtri Monitoraggio`** chiama `GET /api/sensors`.
- Crea una checkbox per ogni sensore, tutte selezionate all'inizio.
- Quando spunti o togli una checkbox, manda un messaggio `tb/filter/sensors` con la lista degli ID selezionati.
- Il messaggio arriva a **`tb_set_sensor_filter`**, che salva la lista in `flow.tb_sensor_filter` e rimanda un messaggio di refresh alla `GET`.
- Lo stesso messaggio arriva anche al template **`Filtri Log`**, che si segna la lista per il CSV.

**Filtro date**

- Il template **`Filtri Log`** ha due campi `date`: “Da” e “A”.
- Quando cambi una data, manda `tb/filter/log` con `{start, end}` in formato `YYYY-MM-DD`.
- **`tb_set_log_filter`** salva i valori in `flow.tb_log_start` e `flow.tb_log_end` e rimanda il refresh alla `GET`.
- `function 4` usa quei valori per filtrare la tabella.
- Il pulsante **Azzera** svuota le date e rifà il giro.

**Pulsante Esporta CSV**

- Prende le date correnti e la lista dei sensori selezionati.
- Apre `/api/telemetry/export?inizio=...&fine=...&sensor_id=...`.
- Il backend genera il CSV e il browser lo scarica.

### 3.3 Il pannello di configurazione

Il template **`Configuration & Alerts`** non passa da un nodo della dashboard: usa direttamente `fetch` verso l'API.

- All'avvio chiama `GET /api/config?sensor_id=default` e `GET /api/sensors`.
- Il menu a tendina permette di scegliere `Default` o un sensore specifico.
- Quando cambi dispositivo, chiama `GET /api/config?sensor_id=...`.
- **Salva configurazione** fa una `POST /api/config` con `sensor_id`, `tempMax`, `umiditaMax`, `ramMax`, `alertsEnabled`.
- **Avvisi attivi** fa subito una `POST` con il solo `alertsEnabled`.
- **Ripristina Default** fa una `POST` con `reset: true` (oppure si può usare `DELETE /api/config?sensor_id=...`).

Il badge “Usa soglie Default” o “Soglie personalizzate attive” arriva dal campo `is_default` della risposta.

---

## 4. Come sono organizzati i flussi Node-RED

In Node-RED bisogna distinguere due cose che hanno lo stesso aspetto ma non sono la stessa cosa:

1. i **tab dell'editor**, quelli in alto quando apri `http://localhost:1880`;
2. i **tab della dashboard**, quelli che vede l'utente nel browser su `http://localhost:1880/ui`.

Nel progetto il tab dell'editor **`Simulatore_IoT`** contiene la sorgente dei dati. Il tab dell'editor **`Dashboard_Grafica`** contiene i widget e la logica della dashboard. Il tab della dashboard si chiama **`Control Room`** e mostra il risultato di `Dashboard_Grafica`.

### 4.1 `Simulatore_IoT`: da dove nascono i dati

- `inject`: parte una volta e ripete ogni 5 secondi.
- `function 3`: genera i valori casuali per i tre sensori e le tre metriche.
- `mqtt out`: pubblica su `telemetry/sensors` con il broker `HiveMQ Docker`.

Non ci sono nodi `ui_*`, quindi questo tab non produce nulla di visibile nella dashboard. È un flusso “di servizio”: genera i dati e li manda al broker, poi il suo compito finisce lì.

### 4.2 `Dashboard_Grafica`: come nasce la Control Room

- `inject` ogni 10 secondi: fa partire la lettura.
- `http request`: `GET http://api:5000/api/telemetry`.
- `function 4`: filtra, separa, prende gli ultimi valori, prepara la tabella.
- 3 `ui_gauge`: temperatura, umidità, RAM.
- 3 `ui_chart`: storico temperatura, umidità, RAM.
- `ui_table`: log delle anomalie.
- `ui_template` **Filtri Monitoraggio**: checkbox dispositivi.
- `ui_template` **Filtri Log**: date e pulsante CSV.
- `ui_template` **Configuration & Alerts**: pannello soglie.
- `ui_template` **Global CSS**: stile della Control Room.
- `tb_set_sensor_filter` e `tb_set_log_filter`: salvano i filtri nelle flow variable e fanno ripartire la GET.

Non ci sono nodi `mqtt out` o `mqtt in`: questo tab non genera e non riceve MQTT. Riceve HTTP dall'API. I widget che vedi in `Control Room` sono definiti qui.

### 4.3 Perché sono separati

Perché hanno due responsabilità diverse:

- il simulatore **produce** dati;
- la dashboard **mostra** dati e permette di configurarli.

Se mettessi tutto nello stesso flusso, sarebbe più difficile capire dove nasce un dato e dove viene salvato. Così invece il percorso è chiaro: sorgente → broker → worker → API → database → dashboard.

E c'è un vantaggio pratico: puoi fermare il simulatore e la dashboard continua a mostrare gli ultimi dati; puoi fermare la dashboard e il worker continua a salvare i dati. Sono indipendenti.

In due righe: **`Simulatore_IoT` produce i dati; `Dashboard_Grafica` li consuma e li rende visibili. Non si parlano direttamente: in mezzo ci sono HiveMQ, il worker, Flask e SQLite.**

### 4.4 Perché `Control Room` e `Dashboard_Grafica` hanno nomi diversi

`Dashboard_Grafica` è il nome del tab nell'editor. `Control Room` è il nome del tab nella dashboard. Sono due impostazioni diverse dello stesso flusso: nell'editor vedi i nodi, nel browser vedi il risultato. Non sono due progetti separati.

---

## 5. Perché c'è un worker Python in mezzo

Questa è una delle domande più probabili, perché il Word dice che Node-RED serve per i “flussi di ricezione e filtraggio”. La risposta deve essere chiara.

Il progetto è a microservizi:

- **HiveMQ** riceve i messaggi MQTT;
- **mqtt-worker** è il consumatore MQTT;
- **Flask** è l'unico punto che valida, calcola le soglie e scrive nel database;
- **Node-RED** è la dashboard e il simulatore.

Perché non mettere un nodo `mqtt in` dentro Node-RED e farlo scrivere direttamente nel database?

- Node-RED dovrebbe conoscere la struttura del database e la logica delle soglie.
- La logica sarebbe duplicata o spostata dentro Node-RED.
- Il backend Flask perderebbe il ruolo di unico punto di validazione.
- Sarebbe più difficile testare e modificare le soglie.

Con il worker:

- il worker fa una cosa sola: prendere i messaggi MQTT e passarli all'API;
- l'API fa una cosa sola: validare, calcolare lo stato, salvare;
- Node-RED fa una cosa sola: mostrare e configurare.

Questo è il senso dei microservizi. Se il professore preferisce un nodo `mqtt in` in Node-RED, è una scelta architetturale alternativa, non un errore: si potrebbe aggiungere un ramo MQTT-in per il monitoraggio, ma la persistenza resterebbe affidata all'API.

**Attenzione:** il worker non ha una coda di retry. Se l'API è giù, i messaggi vengono persi. Se il worker è giù, i messaggi pubblicati in quel momento vengono persi. È un limite noto del progetto didattico.

---

## 6. Cosa fa il backend

I file principali:

| File | Cosa fa |
|---|---|
| `backend/main.py` | crea l'app Flask, configura SQLite, abilita CORS, crea le tabelle |
| `backend/database.py` | inizializza SQLAlchemy |
| `backend/tabelleTelemetria.py` | definisce i modelli `telemetry_records` e `alert_config` |
| `backend/endpoint_API.py` | tutte le rotte API, la logica delle soglie, la migrazione, il CSV |
| `backend/requirements.txt` | dipendenze Python |
| `backend/Dockerfile` | immagine del backend |

### 6.1 Le due tabelle

**`telemetry_records`**

| Colonna | Tipo | Note |
|---|---|---|
| `id` | INTEGER | chiave primaria |
| `sensor_id` | VARCHAR(50) | es. `sensore_server_1` |
| `metric` | VARCHAR(50) | `temperatura`, `umidita`, `utilizzo_ram` |
| `value` | VARCHAR(50) | il valore, salvato come stringa |
| `status` | VARCHAR(50) | `OK`, `WARNING`, `CRITICAL` |
| `timestamp` | DATETIME | salvato in UTC |

Il valore è salvato come stringa perché il modello storico usa `String(50)`. L'API lo converte in `float` prima di calcolare lo stato, quindi il dato è numerico nella logica. Se volessi, potresti migrare la colonna a `Float`, ma non è necessario per il progetto.

**`alert_config`**

| Colonna | Tipo | Note |
|---|---|---|
| `id` | INTEGER | chiave primaria |
| `sensor_id` | VARCHAR(50) | unico; `default` è il fallback |
| `tempMax` | FLOAT | soglia temperatura |
| `umiditàMax` | FLOAT | nome storico della colonna; in Python è `umiditaMax` |
| `ramMax` | FLOAT | soglia RAM |
| `alertsEnabled` | BOOLEAN | avvisi attivi/disattivi |

Il nome `"umiditàMax"` con l'accento è un residuo storico del database. Nel codice Python e nel JSON si usa `umiditaMax` senza accento per evitare problemi di encoding. La mappatura è fatta nel modello:

```python
umiditaMax = db.Column('umiditàMax', db.Float, ...)
```

Questa è una domanda che può uscire: “perché nel database c'è l'accento e nel codice no?”. Perché il database è nato con quel nome e non volevo rompere i dati esistenti; il codice usa un nome più comodo e fa la mappatura.

### 6.2 Le rotte API

| Metodo | Rotta | Cosa fa |
|---|---|---|
| POST | `/api/telemetry` | riceve un dato, calcola lo stato, salva |
| GET | `/api/telemetry` | restituisce i record, opzionalmente filtrati per `sensor_id` |
| GET | `/api/sensors` | restituisce l'elenco dei sensori distinti |
| GET | `/api/config` | restituisce la configurazione (`default` o per sensore) |
| POST/PUT | `/api/config` | salva o aggiorna la configurazione |
| DELETE | `/api/config` | ripristina un sensore al default |
| GET | `/api/telemetry/export` | genera il CSV delle anomalie |

La `GET /api/telemetry` ordina per `id` crescente. Serve perché `function 4` prende l'ultimo elemento dell'array come “valore attuale”: senza ordinamento, il gauge potrebbe mostrare un valore vecchio.

### 6.3 Come viene calcolato lo stato

Lo stato viene calcolato **all'ingresso**, non quando la dashboard legge.

| Metrica | `WARNING` | `CRITICAL` |
|---|---|---|
| Temperatura | valore ≥ `tempMax` | valore ≥ `tempMax` + 5 |
| Umidità | valore ≥ `umiditaMax` | valore ≥ min(`umiditaMax` + 10, 100) |
| RAM | valore ≥ `ramMax` | valore ≥ min(`ramMax` + 5, 100) |

Se `alertsEnabled` è `false` per quel sensore, tutti i nuovi record vengono salvati come `OK`.

Esempio con `tempMax = 30`:

- 29 → `OK`
- 30 → `WARNING`
- 35 → `CRITICAL`

### 6.4 Soglie globali e soglie per sensore

- La riga con `sensor_id = 'default'` contiene le soglie globali.
- Ogni sensore può avere una riga propria.
- Se un sensore non ha una riga propria, usa il `default`.
- Quando salvi una configurazione per un sensore, viene creata (o aggiornata) la sua riga.
- Quando premi **Ripristina Default**, la riga del sensore viene cancellata e torna a usare il `default`.

Nel database attuale ci sono:

- `default`: 60 °C, 70 %, 90 %;
- `sensore_edge_1`: 69 °C, 60 %, 12 %.

La seconda è un esempio di configurazione personalizzata. Serve a far vedere che le soglie possono essere diverse da quelle globali.

**Punto importante:** cambiare le soglie non riscrive i record già salvati. I vecchi record mantengono lo stato con cui sono stati registrati. Le nuove soglie valgono per i dati che arrivano dopo il salvataggio. Se volessi ricalcolare lo storico, servirebbe un job di migrazione, che non è implementato.

---

## 7. Cosa succede quando esporti il CSV

Il pulsante **Esporta CSV** sta nel template `Filtri Log`.

1. Prende le date “Da” e “A” e le converte in `YYYY-MM-DD`.
2. Prende la lista dei sensori selezionati nelle checkbox.
3. Apre:

```text
/api/telemetry/export?inizio=2026-11-01&fine=2026-11-30&sensor_id=sensore_server_1,sensore_edge_1
```

4. Il backend:
   - filtra solo i record con `status != 'OK'`;
   - filtra per `sensor_id`, se presente;
   - converte le date italiane in limiti UTC;
   - ordina per timestamp decrescente;
   - scrive il CSV.

Il CSV:

- contiene **solo le anomalie** (`WARNING` e `CRITICAL`), non i dati `OK`;
- usa il punto e virgola (`;`) come separatore;
- è UTF-8 con BOM, così Excel italiano legge bene le accentate;
- mostra data e ora nel fuso **Europe/Rome**, coerente con la tabella;
- se non ci sono anomalie o non hai selezionato nessun dispositivo, contiene solo l'intestazione.

Perché il CSV usa l'ora italiana? Perché il database salva in UTC, ma la tabella della dashboard mostra l'ora italiana. Se il CSV mostrasse UTC, scaricheresti un file con orari diversi da quelli che vedi a schermo. Il backend converte al momento dell'esportazione.

Perché il filtro date è stato corretto? Prima il CSV usava la mezzanotte UTC, mentre la tabella usava la mezzanotte italiana. Un record alle 23:30 UTC del 25 novembre è le 00:30 del 26 in Italia: poteva finire nel giorno sbagliato. Ora il backend converte le date italiane in UTC e il CSV è coerente con la tabella.

---

## 8. Perché il gauge della temperatura arriva a 100

Prima il gauge della temperatura andava da 0 a 60. Il problema: `sensore_edge_1` ha `tempMax = 69`. Se la temperatura superava 60, la lancetta andava a fondo scala e non si capiva più quanto fosse sopra la soglia.

Ora:

- gauge temperatura: **0–100**;
- grafico temperatura: **0–100**.

Perché 100 e non 69?

- 100 è il valore massimo che puoi impostare come soglia nel pannello di configurazione (i campi hanno `min=0`, `max=100`).
- Con il fondo scala a 100, qualunque soglia valida (60, 69, 80, 100) resta dentro la scala.
- 69 è una soglia specifica, non il fondo scala dello strumento. Se il gauge finisse a 69, un valore di 74 (che è `CRITICAL`, perché 69 + 5 = 74) sarebbe fuori scala.

La frase da dire: **“Il gauge è uno strumento di visualizzazione, non è la configurazione dell'allarme. La soglia vera è nel pannello Configuration & Alerts; il fondo scala è 100 perché è il massimo impostabile.”**

Se ti chiedono “il gauge potrebbe adattarsi automaticamente alla soglia?”, la risposta è: **con il nodo standard `ui_gauge` no**, perché `min` e `max` sono proprietà fisse del nodo. Per farlo servirebbe un gauge custom con `ui_template` e SVG, oppure una logica che aggiorni dinamicamente il widget. È una possibile evoluzione, non è quella attuale.

---

## 9. Cosa ho cambiato in questa versione

Queste sono le modifiche fatte durante la revisione. Servono anche a capire “cosa è stato fatto” rispetto alla versione precedente.

1. **Gauge temperatura e grafico temperatura portati a 100.**
   - Prima: 0–60.
   - Ora: 0–100.
   - Motivo: coprire qualunque soglia impostabile, compresa `sensore_edge_1` con 69.

2. **README riscritto.**
   - Questo file è un foglio di studio personale, non la relazione da consegnare.
   - Non è stato committato né pushato.

3. **CSV corretto sul fuso orario.**
   - Il filtro date ora usa `Europe/Rome`.
   - Il CSV mostra l'ora italiana, non UTC.
   - Un record a cavallo della mezzanotte finisce nel giorno giusto.

4. **GET `/api/telemetry` ordinata per id crescente.**
   - Così `function 4` prende davvero l'ultimo record come valore attuale.

5. **Validazione di `sensor_id` e `metric`.**
   - Se sono vuoti, l'API risponde `400` invece di salvare un record senza senso.

6. **CORS aggiornato con `DELETE`.**
   - Il pannello usa `POST` con `reset: true`, ma l'API supporta anche `DELETE`; ora il browser non blocca la preflight.

7. **Rimosso un `return` duplicato irraggiungibile** in `endpoint_API.py`.

8. **Commento di `docker-compose.yml` corretto.**
   - Prima diceva che Node-RED era “opzionale” e si avviava con un profilo.
   - In realtà Node-RED parte con `docker compose up -d`; ora il commento è coerente.
   - Rimosso il volume `nodered_data` inutilizzato.

9. **Commento del simulatore corretto.**
   - Diceva che Node-RED avrebbe fatto 9 chiamate HTTP; ora dice correttamente che pubblica 9 messaggi MQTT.

10. **`.gitignore` aggiornato** con `nodered_data/.npm/`.

11. **Nessun commit e nessun push.**

---

## 10. I punti da avere pronti

Se la discussione parte da “cosa hai fatto?”, questi sono i concetti che devono venire fuori senza esitazione.

**`Simulatore_IoT` è la sorgente.** Ogni 5 secondi genera 9 messaggi (3 sensori × 3 metriche) e li pubblica su MQTT. Non conosce il database e non scrive nulla: il suo compito finisce quando il messaggio arriva a HiveMQ.

**`Dashboard_Grafica` è la control room.** Ogni 10 secondi legge i dati dall'API, li filtra e aggiorna gauge, grafici e tabella. Contiene anche i filtri e il pannello di configurazione. Non genera dati e non scrive nel database: mostra solo quello che l'API le restituisce.

**I due flussi sono separati perché hanno due responsabilità diverse.** In mezzo ci sono HiveMQ, il worker, Flask e SQLite. Così puoi fermare il simulatore e la dashboard continua a mostrare gli ultimi dati, oppure fermare la dashboard e il worker continua a salvare.

**La ricezione MQTT è affidata al worker Python.** Nel tab `Dashboard_Grafica` non c'è un nodo `mqtt in`. Il worker prende i messaggi, Flask valida e salva, Node-RED mostra. È una scelta a microservizi: la logica di validazione e soglie resta in un solo punto. Se il professore preferisce un nodo MQTT-in in Node-RED, si può aggiungere un ramo di monitoraggio, ma la persistenza resterebbe nell'API.

**Il database è SQLite3.** È leggero, non richiede un server separato ed è un file solo. SQLAlchemy permette di cambiare database, ma la scelta richiesta è SQLite3.

**La dashboard del progetto è Node-RED Dashboard 1.x.** Usa `ui_template`, `ui_gauge`, `ui_chart`, `ui_table` ed è su `/ui`. Dashboard 2.0 è presente nell'installazione per altri tab didattici, ma non fa parte di TelemetryBinder.

**Il gauge della temperatura va da 0 a 100.** 100 è il massimo impostabile come soglia; così la scala copre anche `sensore_edge_1` con 69 e qualunque soglia futura. La soglia vera è nel pannello di configurazione; il gauge è solo la scala.

**Il filtro dispositivi** parte da `Filtri Monitoraggio`: chiama `/api/sensors`, crea le checkbox e manda gli ID selezionati a `tb_set_sensor_filter`. La lista finisce in `flow.tb_sensor_filter`, fa ripartire la GET e viene usata da `function 4`. La stessa lista arriva a `Filtri Log` per il CSV.

**Il filtro date** parte da `Filtri Log`: manda `{start, end}` in `YYYY-MM-DD` a `tb_set_log_filter`, che salva `flow.tb_log_start` e `flow.tb_log_end` e fa ripartire la GET. `function 4` converte i timestamp in `Europe/Rome` e confronta le date. Il CSV fa la conversione inversa: date italiane → UTC per il database.

**Lo stato viene calcolato all'ingresso, nell'API.** Per ogni sensore prende la configurazione (default o personalizzata) e applica le soglie: `WARNING` al superamento, `CRITICAL` al superamento maggiorato. Se `alertsEnabled` è falso, tutto è `OK`.

**Cambiare le soglie non riscrive lo storico.** I nuovi dati usano le nuove soglie; i record già salvati mantengono lo stato con cui sono stati registrati. Non c'è un ricalcolo.

**Il CSV contiene solo le anomalie.** Filtra per data e per dispositivi selezionati, usa `;` e BOM UTF-8, e mostra l'ora italiana. Non contiene i dati `OK`.

**Se un servizio è giù, il sistema non recupera i messaggi persi.** Il worker non ha una coda di retry: se l'API è giù, la POST fallisce e il messaggio va perso; se il worker è giù, i messaggi pubblicati in quel momento vanno persi. È un limite noto del progetto didattico.

**Le altre schede Node-RED sono esercizi didattici.** La scheda del progetto è `Control Room`; le altre non fanno parte di TelemetryBinder. Il CSS globale è “scoped” con `.tb-panel` e `body:has(.tb-panel)`.

**Per aggiungere un sensore** basta pubblicare un messaggio MQTT con un nuovo `sensor_id`: il worker lo passa all'API, l'API lo salva e il sensore compare in `/api/sensors`. **Per aggiungere una metrica** serve invece modificare `function 3`, `calcola_status`, `function 4` e aggiungere un gauge/grafico.

---

## 11. Come mostrare il progetto

Un ordine che funziona:

1. **`docker compose ps`**
   - fai vedere i 4 container attivi.

2. **Apri `http://localhost:1880/ui`**
   - mostra la scheda `Control Room`;
   - indica i 3 gauge a lancetta e i 3 grafici;
   - spunta/deseleziona un dispositivo e fai vedere che i dati cambiano;
   - apri `Configuration & Alerts`, cambia una soglia e salva;
   - apri `Anomaly Logs`, scegli una data e mostra la tabella;
   - premi `Esporta CSV` e apri il file.

3. **Apri l'editor Node-RED `http://localhost:1880`**
   - vai sul tab `Simulatore_IoT` e spiega inject → function 3 → mqtt out;
   - vai sul tab `Dashboard_Grafica` e spiega inject → HTTP GET → function 4 → widget;
   - fai vedere i filtri e il pannello di configurazione;
   - ricorda che `Control Room` è il tab della dashboard, non dell'editor.

4. **Mostra i log del worker**
   ```bash
   docker compose logs -f mqtt-worker
   ```
   - fai vedere i messaggi MQTT che arrivano e il relativo `status`.

5. **Mostra l'API**
   ```bash
   curl http://localhost:5000/api/sensors
   curl http://localhost:5000/api/config
   ```
   - spiega che la dashboard usa queste rotte.

6. **Mostra il database**
   - il file è `db_data/telemetry.db`;
   - le tabelle sono `telemetry_records` e `alert_config`.

7. **Mostra `docker-compose.yml`**
   - spiega i 4 servizi, le porte e i volumi.

8. **Mostra i file del backend**
   - `main.py`, `endpoint_API.py`, `tabelleTelemetria.py`.

Se ti chiedono “fammi vedere che il dato passa davvero da MQTT”, apri i log del worker mentre il simulatore gira: vedrai i messaggi `telemetry/sensors` e i `POST` all'API.

---

## 12. Errori da evitare

- **Non dire che Node-RED salva nel database.** Non lo fa. A salvare è il worker, che chiama l'API.
- **Non dire che la dashboard legge direttamente SQLite.** Legge l'API.
- **Non dire che il fondo scala del gauge è la soglia.** Il fondo scala è 100; la soglia è nel pannello di configurazione.
- **Non dire che il progetto usa Dashboard 2.0.** La dashboard del progetto è Dashboard 1.x su `/ui`. Dashboard 2.0 c'è nell'installazione, ma per altri tab didattici.
- **Non dire MySQL.** È SQLite3.
- **Non dire che il CSV contiene tutti i dati.** Contiene solo le anomalie.
- **Non dire che cambiare le soglie aggiorna i vecchi record.** Non li aggiorna.
- **Non dire che il simulatore scrive nel database.** Pubblica solo su MQTT.
- **Non dire che il worker è Node-RED.** È un servizio Python separato.
- **Non confondere `Control Room` con `Dashboard_Grafica`.** Uno è il tab della dashboard, l'altro è il tab dell'editor.
- **Non dire che `Simulatore_IoT` è una scheda della dashboard.** È un tab dell'editor, senza widget `ui_*`.
- **Non dire che i grafici mostrano tutto lo storico.** Mostrano circa l'ultima ora; lo storico completo è nel database, mentre il CSV contiene solo le anomalie.

---

## 13. Comandi e verifiche rapide

Avvio:

```bash
docker compose up -d --build
```

Stato:

```bash
docker compose ps
```

Log:

```bash
docker compose logs -f
docker compose logs -f mqtt-worker
```

API:

```bash
curl http://localhost:5000/api/sensors
curl http://localhost:5000/api/config
curl http://localhost:5000/api/telemetry
```

CSV:

```bash
curl -o anomalie.csv "http://localhost:5000/api/telemetry/export?inizio=2026-11-01&fine=2026-11-30&sensor_id=sensore_server_1"
```

Arresto:

```bash
docker compose down
```

Reset del database:

```bash
docker compose down
docker compose run --rm api rm -f /data/telemetry.db
docker compose up -d
```

---

## 14. Glossario minimo

| Termine | Significato |
|---|---|
| **MQTT** | protocollo publish/subscribe leggero, usato per i sensori |
| **Broker** | il server MQTT che riceve e distribuisce i messaggi (HiveMQ) |
| **Topic** | il “canale” su cui si pubblica o ci si iscrive (`telemetry/sensors`) |
| **Publish/Subscribe** | chi pubblica non conosce chi riceve; il broker fa da intermediario |
| **QoS** | garanzia di consegna MQTT; nel progetto è quella di default |
| **Worker** | servizio che ascolta MQTT e inoltra i dati all'API |
| **API REST** | insieme di rotte HTTP con cui la dashboard parla con Flask |
| **JSON** | formato dei messaggi e delle risposte API |
| **SQLite3** | database su file, senza server separato |
| **SQLAlchemy** | libreria Python che mappa le tabelle in classi |
| **Flask** | framework Python del backend |
| **Node-RED** | ambiente visuale a nodi per flussi e dashboard |
| **Flow / tab** | in Node-RED, un tab dell'editor; nel progetto `Simulatore_IoT` e `Dashboard_Grafica` |
| **Nodo** | blocco di Node-RED (`inject`, `function`, `mqtt out`, `ui_gauge`, …) |
| **`inject`** | nodo che genera un messaggio, anche a intervalli regolari |
| **`function`** | nodo con codice JavaScript |
| **`ui_gauge`** | widget gauge di Dashboard 1.x |
| **`ui_chart`** | widget grafico di Dashboard 1.x |
| **`ui_table`** | widget tabella di Dashboard 1.x |
| **`ui_template`** | widget HTML/JavaScript di Dashboard 1.x |
| **Flow variable** | variabile condivisa nel tab, `flow.set()` / `flow.get()` |
| **CORS** | regole che permettono al browser di chiamare l'API su un'altra porta |
| **Docker** | container |
| **Docker Compose** | file che descrive e avvia più container |
| **Volume** | cartella condivisa tra host e container |
| **UTC** | fuso orario di riferimento del database |
| **Europe/Rome** | fuso usato dalla dashboard e dal CSV |
| **BOM** | marcatore UTF-8 per Excel |
| **CSV** | file di testo con valori separati da `;` |

---

## 15. Limiti e cose da migliorare

- Nessuna autenticazione su Node-RED e sull'API; nessun HTTPS.
- Nessuna coda di retry: se API o worker sono giù, i messaggi MQTT vengono persi.
- `GET /api/telemetry` restituisce tutti i record; con lo storico grande diventa pesante.
- I grafici mostrano solo l'ultima ora; lo storico completo è nel database.
- Il gauge ha fondo scala fisso 100; un gauge dinamico richiederebbe un template custom.
- Cambiare le soglie non ricalcola i record storici.
- Non ci sono test automatici.
- L'istanza Node-RED contiene anche tab didattici e Dashboard 2.0, che non fanno parte del progetto.
- `value` è salvato come stringa; si potrebbe migrare a `Float`.
- SQLite è un file singolo: va bene per il progetto, non per un uso multiutente intenso.
- Il file del database è creato dal container come `root`; per cancellarlo può servire `sudo` o il comando con `docker compose run`.

---

## 16. Checklist finale

- [x] 4 container attivi: HiveMQ, API, worker, Node-RED.
- [x] Dashboard 1.x su `/ui`, scheda `Control Room`.
- [x] Simulatore MQTT ogni 5 secondi.
- [x] Worker MQTT → API.
- [x] Flask + SQLite3.
- [x] Soglie globali e per sensore.
- [x] Switch avvisi.
- [x] Gauge a lancetta.
- [x] Grafici a linee.
- [x] Filtro dispositivi.
- [x] Filtro date.
- [x] CSV delle anomalie.
- [x] Flusso Node-RED nel repository.
- [x] README personale (questo file).
- [x] Nessun commit/push.
