"""ChromaProof API - FastAPI + SQLite. Run: cd backend && uvicorn main:app --reload
Presumptive screening only. DEV signing key; production key custody is NOT implemented."""
import hashlib, io, json, os, sqlite3, uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

import cv2, numpy as np
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from vision import process_image

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(HERE, "chromaproof.db"))
KEY_PATH = os.getenv("KEY_PATH", os.path.join(HERE, "keys", "dev_ed25519_private.pem"))
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"
NOTICE = ("PRESUMPTIVE RESULT ONLY. Laboratory confirmation (e.g. GC/MS) is required. Prototype: not validated "
          "for operational use; a valid signature proves integrity only, not correctness or admissibility.")
CANONICAL_VERSION = "2"

app = FastAPI(title="ChromaProof API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ Role 3: crypto
class Crypto:
    SIGNED = ["record_id", "operator_id", "timestamp_utc", "kit_id", "result", "confidence", "classifier_version",
              "explanation", "image_sha256", "location", "calibration", "key_id", "canonical_version"]

    def __init__(self):
        pem = os.getenv("SIGNING_KEY_PEM")                 # use this on Render (ephemeral disk)
        if pem:
            self.priv = serialization.load_pem_private_key(pem.replace("\\n", "\n").encode(), None)
        elif os.path.exists(KEY_PATH):
            with open(KEY_PATH, "rb") as f:
                self.priv = serialization.load_pem_private_key(f.read(), None)
        else:                                              # first run: create + persist a DEV key
            self.priv = ed25519.Ed25519PrivateKey.generate()
            os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
            with open(KEY_PATH, "wb") as f:
                f.write(self.priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()))
            try: os.chmod(KEY_PATH, 0o600)
            except OSError: pass
        self.pub = self.priv.public_key()
        raw = self.pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.public_key_hex = raw.hex()
        self.key_id = "KEY-ED25519-" + hashlib.sha256(raw).hexdigest()[:12].upper()

    @staticmethod
    def sha256(b: bytes) -> str: return hashlib.sha256(b).hexdigest()

    def canonical(self, rec: dict) -> bytes:
        body = {k: rec.get(k) for k in self.SIGNED}
        return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    def sign(self, rec: dict) -> str: return self.priv.sign(self.canonical(rec)).hex()

    def verify(self, rec: dict, sig_hex: str, image: Optional[bytes]) -> Tuple[str, str]:
        """Trusts ONLY the server's own public key, never a key stored in the record."""
        if not sig_hex: return "INVALID", "Missing signature."
        if image is not None and self.sha256(image) != rec.get("image_sha256"):
            return "TAMPERED", "Image hash mismatch: the image changed after signing."
        if rec.get("key_id") != self.key_id:
            return "INVALID", f"Unknown signing key ({rec.get('key_id')}); not the trusted server key."
        try:
            self.pub.verify(bytes.fromhex(sig_hex), self.canonical(rec))
        except (InvalidSignature, ValueError):
            return "TAMPERED", "Signature mismatch: record content changed after signing."
        return "VALID", "Hash and Ed25519 signature match (integrity only; not proof the test was correct)."

crypto = Crypto()


# ------------------------------------------------------------------ kits (DEMO references, unvalidated)
KITS = {
    "cobalt_thiocyanate": dict(name="Cobalt Thiocyanate (Scott Reagent)", pos=(36.0, 3.0, -48.0), neg=(55.0, 45.0, 12.0)),
    "marquis": dict(name="Marquis Reagent", pos=(21.0, 28.0, -18.0), neg=(82.0, 0.0, 8.0)),
    "duquenois_levine": dict(name="Duquenois-Levine Reagent", pos=(30.0, 31.0, -30.0), neg=(75.0, 2.0, 22.0)),
}


# ------------------------------------------------------------------ storage
def db():
    c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS records_v2(record_id TEXT PRIMARY KEY, operator_id TEXT, timestamp_utc TEXT,
                 kit_id TEXT, result TEXT, body TEXT, signature_hex TEXT, image BLOB, sync_status TEXT)""")
    return c

def public(row) -> dict:
    return {**json.loads(row["body"]), "signature_hex": row["signature_hex"], "sync_status": row["sync_status"],
            "public_key_hex": crypto.public_key_hex}

def get_row(rid):
    r = db().execute("SELECT * FROM records_v2 WHERE record_id=?", (rid,)).fetchone()
    if not r: raise HTTPException(404, "Record not found.")
    return r


# ------------------------------------------------------------------ routes
@app.get("/api/health")
def health(): return {"ok": True, "key_id": crypto.key_id, "demo_mode": DEMO_MODE}

@app.get("/api/kits")
def kits(): return [{"id": k, "name": v["name"]} for k, v in KITS.items()]

@app.get("/api/pubkey")
def pubkey(): return {"key_id": crypto.key_id, "public_key_hex": crypto.public_key_hex, "note": "DEV KEY - non-production"}

@app.post("/api/process")
async def process_capture(image: UploadFile = File(...), operator_id: str = Form("OFFICER-4021"),
                          kit_id: str = Form("cobalt_thiocyanate"), location: str = Form("GPS: unavailable")):
    data = await image.read()
    if len(data) > 10 * 1024 * 1024: raise HTTPException(413, "Image too large (max 10 MB).")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None: raise HTTPException(400, "File is not a valid image.")
    if min(img.shape[:2]) < 200: raise HTTPException(400, "Image too small (min 200 px).")
    if kit_id not in KITS: raise HTTPException(400, f"Unknown kit_id: {kit_id}")
    if not operator_id.strip(): raise HTTPException(400, "operator_id required.")

    k = KITS[kit_id]
    r = process_image(img, ref_pos_lab=k["pos"], ref_neg_lab=k["neg"])
    if r["quality_status"] != "PASS":
        return JSONResponse(status_code=422, content={"detail": " ".join(r["quality_reasons"]),
                                                      "reasons": r["quality_reasons"], "status": "RETAKE"})
    now = datetime.now(timezone.utc)
    rec = {"record_id": f"CP-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}", "operator_id": operator_id.strip()[:64],
           "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "timestamp_source": "server clock",
           "kit_id": kit_id, "result": r["result"].upper(), "confidence": r["confidence"],
           "confidence_note": "relative colour-margin cue, NOT a probability", "classifier_version": r["classifier_version"],
           "explanation": r["explanation"], "image_sha256": crypto.sha256(data), "location": location[:200],
           "calibration": "reference-card (white/gray/black patches)", "key_id": crypto.key_id,
           "canonical_version": CANONICAL_VERSION, "notice": NOTICE}
    sig = crypto.sign(rec)
    with db() as c:
        c.execute("INSERT INTO records_v2 VALUES (?,?,?,?,?,?,?,?,?)", (rec["record_id"], rec["operator_id"],
                  rec["timestamp_utc"], kit_id, rec["result"], json.dumps(rec), sig, data, "SYNCED"))
    return {"status": "SUCCESS", "record": {**rec, "signature_hex": sig, "sync_status": "SYNCED",
                                           "public_key_hex": crypto.public_key_hex}}

@app.get("/api/records")
def list_records(result: Optional[str] = None, operator: Optional[str] = None, date: Optional[str] = None,
                 kit_id: Optional[str] = None):
    q, a = "SELECT * FROM records_v2 WHERE 1=1", []
    for col, val, op in (("result", result and result.upper(), "="), ("kit_id", kit_id, "="),
                         ("operator_id", operator and f"%{operator}%", "LIKE"), ("timestamp_utc", date and f"{date}%", "LIKE")):
        if val: q += f" AND {col} {op} ?"; a.append(val)
    return [public(r) for r in db().execute(q + " ORDER BY timestamp_utc DESC LIMIT 200", a)]

@app.get("/api/records/{rid}")
def one(rid: str): return public(get_row(rid))

@app.get("/api/records/{rid}/image")
def image(rid: str): return Response(get_row(rid)["image"], media_type="image/jpeg")

class VerifyReq(BaseModel):
    record_id: str
    simulate_tamper: bool = False

@app.post("/api/verify")
def verify(req: VerifyReq):
    row = get_row(req.record_id); rec = json.loads(row["body"])
    if req.simulate_tamper:                                  # in-memory only; DB untouched
        rec["result"] = "NEGATIVE" if rec["result"] == "POSITIVE" else "POSITIVE"
    status, msg = crypto.verify(rec, row["signature_hex"], row["image"])
    return {"status": status, "valid": status == "VALID", "message": msg, "signer_key": rec.get("key_id"),
            "trusted_key": crypto.key_id, "simulated_tamper": req.simulate_tamper,
            "scope": "Integrity only; not proof of correct chemistry, operator identity or admissibility."}

@app.get("/api/records/{rid}/report.json")
def report_json(rid: str):
    row = get_row(rid); status, msg = crypto.verify(json.loads(row["body"]), row["signature_hex"], row["image"])
    return {"record": public(row), "verification": {"status": status, "message": msg, "trusted_key": crypto.key_id},
            "notice": NOTICE}

@app.get("/api/records/{rid}/report.pdf")
def report_pdf(rid: str):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    row = get_row(rid); rec = json.loads(row["body"])
    status, msg = crypto.verify(rec, row["signature_hex"], row["image"])
    st, buf = getSampleStyleSheet(), io.BytesIO()
    cells = [[k, Paragraph(str(rec.get(k, "")), st["BodyText"])] for k in
             ["record_id", "operator_id", "timestamp_utc", "kit_id", "result", "confidence", "classifier_version",
              "explanation", "location", "calibration", "image_sha256", "key_id"]]
    cells += [["signature", Paragraph(row["signature_hex"][:64] + "...", st["BodyText"])],
              ["verification", Paragraph(f"<b>{status}</b> - {msg}", st["BodyText"])]]
    t = Table(cells, colWidths=[38 * mm, 130 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke)]))
    thumb = io.BytesIO(cv2.imencode(".jpg", cv2.resize(cv2.imdecode(np.frombuffer(row["image"], np.uint8), 1),
                                                       (400, 320)))[1].tobytes())
    SimpleDocTemplate(buf, pagesize=A4, title=f"ChromaProof {rid}").build([
        Paragraph("ChromaProof - Presumptive Field Test Record", st["Title"]),
        Paragraph(f"<font color='red'><b>{NOTICE}</b></font>", st["BodyText"]), Spacer(1, 8), t, Spacer(1, 8),
        RLImage(thumb, width=70 * mm, height=56 * mm)])
    return Response(buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{rid}.pdf"'})
