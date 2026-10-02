# ChromaProof

SIH26231 - Digital Companion for Field Drug Testing. A phone-first companion for existing colourimetric
test kits: guided capture, **reference-card calibration**, quality gate, uncertainty-aware presumptive result,
and an **Ed25519-signed, tamper-evident record** with search, verification and PDF/JSON export.

> **Presumptive screening only.** Results require confirmatory laboratory analysis (GC/MS). Prototype: kit colour
> references are DEMO values (not validated), and a valid signature proves integrity only - not correct chemistry,
> operator identity or court admissibility.

## Structure
- `backend/main.py` - FastAPI: API, signing/verification (Role 3), SQLite storage, PDF/JSON reports
- `backend/vision.py` - card detection (4 ArUco markers), blur/glare/exposure gate, calibration, classifier (Role 1)
- `frontend/` - static PWA (no build step): capture, history, verify, offline queue
- `tools/make_samples.py` - generates synthetic samples + printable `PRINT_reference_card.png` into `sample_data/`
- `tests/test_core.py` - vision, signing, tamper (record/image/DB edit), PDF, rejection tests

## Run
```bash
cd backend
python -m venv venv && venv\Scripts\activate      # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload                          # http://127.0.0.1:8000/docs
```
Frontend (second terminal): `cd frontend && python -m http.server 3000`, then open
`http://localhost:3000/?api=http://127.0.0.1:8000` (the `?api=` param avoids editing `app.js`).

Samples: `python tools/make_samples.py` (from repo root) then upload files from `sample_data/`.
Tests: from repo root `pip install -r backend/requirements.txt && python -m unittest tests.test_core -v`.

## Images the pipeline accepts
A photo containing the printed reference card (`sample_data/PRINT_reference_card.png`, print matte) with all 4
corner markers visible. Photos without the card are **rejected with retake guidance** - no silent guessing.

## Signing key
- First run creates a **DEV** key at `backend/keys/dev_ed25519_private.pem` (git-ignored) and reuses it.
- Hosting on Render (ephemeral disk): set env `SIGNING_KEY_PEM` to the PEM (newlines as `\n`) so the key and
  `key_id` survive restarts. Records signed by another key verify as INVALID (unknown key).
- Verification trusts only the server's own public key, never a key stored in the record.
- Production key custody (HSM/KMS, rotation, roles) is NOT implemented. Set `DEMO_MODE=0` for deployments.

## API
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health`, `/api/kits`, `/api/pubkey` | status, kit list, trusted public key |
| POST | `/api/process` | multipart `image, operator_id, kit_id, location` -> signed record, or 422 with `reasons[]` |
| GET | `/api/records?result=&operator=&date=&kit_id=` | search/filter history |
| GET | `/api/records/{id}`, `/image`, `/report.json`, `/report.pdf` | detail, image, exports |
| POST | `/api/verify` | `{record_id, simulate_tamper}` -> VALID / TAMPERED / INVALID with reason |

## Known limitations (say these in the demo)
Synthetic/demo data only; thresholds tuned on synthetic images; no assay-specific validation; server-clock
timestamps and device GPS are unverified; demo login only (no auth/roles); SQLite on ephemeral disk loses data on
redeploy; offline queue is basic (retry on reconnect, no conflict handling).
