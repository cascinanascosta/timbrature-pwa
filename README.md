# Timbrature PWA — Render Demo

Versione completa per demo online su Render con HTTPS e PostgreSQL.

## Struttura obbligatoria

Il repository deve contenere **anche la cartella `backend/`**:

```text
backend/
  main.py
  static/
    index.html
    app.js
    qr.html
    manifest.json
    sw.js
requirements.txt
render.yaml
```

## Deploy Render

1. Carica TUTTO il contenuto del progetto nel repository GitHub.
2. Verifica che `backend/main.py` sia visibile nella root del repository.
3. Su Render usa il Blueprint già creato e fai un Manual Sync/Deploy.
4. Render avvia `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`.

## Demo

Dipendente: `demo` / `demo123`

Admin: `admin` / `admin123`

## QR

`/qr` genera il QR sul server e lo rinnova ogni 30 secondi. Non usa la libreria QR JavaScript.

## Scanner

La PWA usa `html5-qrcode` nel browser per la fotocamera. La scansione deve essere eseguita dalla URL HTTPS di Render.

## Storico dipendente

Il mese precedente è visibile al dipendente solo dal giorno 1 al giorno 6 del mese corrente.
