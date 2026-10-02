"""Run from repo root:  python -m unittest tests.test_core -v   (needs requirements installed)"""
import os, sys, tempfile, unittest
os.environ.update(DB_PATH=tempfile.mktemp(), KEY_PATH=os.path.join(tempfile.mkdtemp(), "k.pem"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import cv2
from fastapi.testclient import TestClient
import main
from vision import photograph, render_card, run_scenarios

def jpg(img): return cv2.imencode(".jpg", img)[1].tobytes()
def post(c, img, kit="marquis"):
    return c.post("/api/process", files={"image": ("a.jpg", jpg(img), "image/jpeg")},
                  data={"operator_id": "T-1", "kit_id": kit})

class Core(unittest.TestCase):
    c = TestClient(main.app)
    def test_vision_scenarios(self): self.assertTrue(run_scenarios(verbose=False))
    def test_flow_and_tamper(self):
        r = post(self.c, photograph(render_card((80, 30, 110)))); self.assertEqual(r.status_code, 200, r.text)
        rid = r.json()["record"]["record_id"]
        self.assertEqual(self.c.post("/api/verify", json={"record_id": rid}).json()["status"], "VALID")
        v = self.c.post("/api/verify", json={"record_id": rid, "simulate_tamper": True}).json()
        self.assertEqual(v["status"], "TAMPERED")
        self.assertEqual(self.c.get(f"/api/records/{rid}/report.pdf").content[:4], b"%PDF")
        self.assertEqual(self.c.get(f"/api/records/{rid}/report.json").json()["verification"]["status"], "VALID")
        self.assertTrue(any(x["record_id"] == rid for x in self.c.get("/api/records").json()))
    def test_db_edit_detected(self):
        r = post(self.c, photograph(render_card((80, 30, 110)))); rid = r.json()["record"]["record_id"]
        import sqlite3, json
        con = sqlite3.connect(main.DB_PATH); row = con.execute("SELECT body FROM records_v2 WHERE record_id=?", (rid,)).fetchone()
        b = json.loads(row[0]); b["operator_id"] = "EVIL"
        con.execute("UPDATE records_v2 SET body=? WHERE record_id=?", (json.dumps(b), rid)); con.commit()
        self.assertEqual(self.c.post("/api/verify", json={"record_id": rid}).json()["status"], "TAMPERED")
    def test_image_swap_detected(self):
        r = post(self.c, photograph(render_card((80, 30, 110)))); rid = r.json()["record"]["record_id"]
        import sqlite3
        con = sqlite3.connect(main.DB_PATH); con.execute("UPDATE records_v2 SET image=? WHERE record_id=?", (b"x", rid)); con.commit()
        self.assertEqual(self.c.post("/api/verify", json={"record_id": rid}).json()["status"], "TAMPERED")
    def test_bad_images_rejected(self):
        for img in (photograph(render_card((80, 30, 110)), with_card=False), photograph(render_card((80, 30, 110)), blur=6)):
            r = post(self.c, img); self.assertEqual(r.status_code, 422); self.assertTrue(r.json()["reasons"])
        self.assertEqual(self.c.post("/api/process", files={"image": ("a.jpg", b"notimage", "image/jpeg")}).status_code, 400)
    def test_key_persists(self):
        k = main.Crypto().key_id; self.assertEqual(k, main.crypto.key_id)

if __name__ == "__main__": unittest.main()
