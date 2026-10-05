# Timbrature PWA - Cascina Nascosta

## Struttura
- `render.yaml` è nella root del repository per essere letto automaticamente da Render.
- `app/` contiene l'applicazione.
- `app/backend/main.py` contiene il backend FastAPI.
- `app/requirements.txt` contiene le dipendenze.

## Render
Build command:
`pip install -r app/requirements.txt`

Start command:
`cd app && uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
