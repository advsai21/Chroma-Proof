# ChromaProof

SIH26231 - Digital Companion for Field Drug Testing (Ministry of Home Affairs).

A mobile/web companion for colorimetric field-test kits. It captures a photo of the test
result, classifies it as POSITIVE / NEGATIVE / INCONCLUSIVE, and creates a tamper-evident
record: timestamp, location, operator ID, SHA-256 hash of the image and an Ed25519 signature.

> Presumptive field screening only. Results require confirmatory laboratory analysis (GC/MS).

## Project structure

- `backend/` - FastAPI app (`main.py`): image analysis, signing, verification, SQLite storage
- `frontend/` - static HTML/CSS/JS client (`index.html`, `app.js`, `style.css`)
- `chromaproof.ipynb` - notebook

## Run the backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
uvicorn main:app --reload
```

The API runs at http://127.0.0.1:8000 and interactive docs are at http://127.0.0.1:8000/docs.

## Run the frontend

The frontend is static files, so there is no npm install step. Serve the folder:

```bash
cd frontend
npx serve .
# or: python -m http.server 3000
```

Open http://localhost:3000 and allow camera access.

`API_URL` (line 2 of `frontend/app.js`) points to the deployed backend by default. To use your
local backend, change it to `http://127.0.0.1:8000` (do not commit that change).

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/kits` | List supported reagent kits |
| POST | `/api/process` | Upload an image (multipart: `image`, `operator_id`, `kit_id`, `location`) and get a signed record |
| POST | `/api/verify` | Verify a stored record's signature by `record_id` |

Tested on Windows with Python 3.14.
