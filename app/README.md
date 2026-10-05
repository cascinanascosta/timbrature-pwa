# Timbrature PWA — Cascina Nascosta

App FastAPI per timbrature dipendenti con PostgreSQL persistente su Render.

## File
- `backend/main.py` — backend completo
- `backend/static/style.css` — interfaccia Cascina Nascosta
- `requirements.txt`
- `render.yaml`
- `runtime.txt`

## Render
1. Crea/collega il PostgreSQL e imposta `DATABASE_URL`.
2. Imposta `ADMIN_PASSWORD` negli Environment Variables.
3. Deploy dal repository.
4. Health check: `/health`.

## Area dipendente
- username + PIN
- timbra entrata/uscita
- storico personale
- dati persistenti

## Area admin
- login con `ADMIN_PASSWORD`
- aggiunta dipendente
- modifica nome, username, PIN e team
- disattivazione/riattivazione
- report mensile
- export Excel

## Excel
Il file contiene:
- `Timbrature`: Dipendente, Data, Entrata, Uscita, Totale ore
- turno spezzato: due righe con la stessa data, una per ogni coppia entrata/uscita
- nessuna riga di totale giornaliero
- `Riepilogo mensile`: totale mensile per dipendente
