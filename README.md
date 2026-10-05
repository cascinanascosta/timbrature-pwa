# Cascina Timbrature PWA

Versione con PostgreSQL persistente, gestione dipendenti/team dal back office,
timbrature con turno spezzato e export Excel mensile.

## Render
- Build: `pip install -r requirements.txt`
- Start: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Database: PostgreSQL tramite `DATABASE_URL`
- `ADMIN_PIN` è una variabile d'ambiente. Se non impostata, il valore locale predefinito è `1234`.

## Accessi iniziali
- Admin: PIN `1234` (cambialo su Render impostando `ADMIN_PIN`)
- Dipendente: Jacopo / PIN `1111`

Il database crea automaticamente i team `Sala` e `Cucina` e il dipendente Jacopo se non esistono.
