# CASCINA NASCOSTA - TIMBRATURE PWA

## Struttura GitHub

La cartella principale del progetto è:

    app/

Tutto il progetto è contenuto dentro questa cartella.

## QR del tablet aziendale

Aprire sul tablet:

    https://TUO-DOMINIO.onrender.com/qr

La pagina è pensata per essere lasciata sempre aperta sul tablet e mostra il QR di accesso alla timbratura.

## Render

Build Command:

    pip install -r requirements.txt

Start Command:

    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
