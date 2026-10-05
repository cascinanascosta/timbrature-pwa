# Timbrature PWA - Cascina Nascosta

Struttura del progetto:

    app/
        backend/
        requirements.txt
        render.yaml
        ...

Su Render, il repository va collegato alla root del progetto.
Il build command usa `app/requirements.txt` e lo start command entra in `app/`
prima di avviare `backend.main:app`.
