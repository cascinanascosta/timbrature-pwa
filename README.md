# Timbrature PWA — Render Demo

Versione predisposta per una demo online su Render con HTTPS e PostgreSQL.

## Demo locale

`run_windows.bat` continua a funzionare in locale. Se non imposti `DATABASE_URL`, viene usato SQLite.

## Deploy Render

1. Crea un repository GitHub vuoto.
2. Carica tutti i file di questa cartella nella root del repository.
3. Vai su Render e collega GitHub.
4. Usa **New → Blueprint** e seleziona il repository.
5. Render leggerà `render.yaml`, creerà il Web Service e il database PostgreSQL demo.
6. Al termine avrai un URL `https://...onrender.com` con HTTPS.

Render supporta FastAPI con Uvicorn e `$PORT`; il file `render.yaml` è già configurato in questo modo.

## Credenziali demo

Dipendente:
- username: `demo`
- password: `demo123`

Admin:
- username: `admin`
- password: `admin123`

**Cambiare queste credenziali prima di qualsiasi uso reale.**

## QR

Apri:
`https://TUO-SERVIZIO.onrender.com/qr`

Il QR viene generato lato server e cambia ogni 30 secondi. Non dipende da una libreria QR JavaScript esterna.

## Scanner

La PWA usa `html5-qrcode` per la fotocamera. Il telefono deve aprire la PWA tramite HTTPS; su Render questo è disponibile automaticamente.

## Regola storico

Il dipendente vede il mese precedente solo dal giorno 1 al giorno 6 del mese corrente. Dal giorno 7 non lo vede più. L'admin mantiene lo storico completo.

## Limiti demo Render

Il Web Service Free va in sleep dopo 15 minuti senza traffico e può impiegare circa un minuto per riattivarsi. Il PostgreSQL Free è da considerare temporaneo: Render indica una scadenza di 30 giorni e 1 GB di storage. Non usare questa configurazione per dati reali del personale.
