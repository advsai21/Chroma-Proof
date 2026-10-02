"""Generate synthetic demo images + a printable reference card. Run from repo root: python tools/make_samples.py"""
import os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from vision import photograph, render_card
from main import KITS

def lab_to_rgb(lab):
    px = np.uint8([[[np.clip(lab[0] * 255 / 100, 0, 255), np.clip(lab[1] + 128, 0, 255), np.clip(lab[2] + 128, 0, 255)]]])
    return tuple(int(v) for v in cv2.cvtColor(px, cv2.COLOR_LAB2RGB)[0, 0])

out = os.path.join(os.path.dirname(__file__), "..", "sample_data"); os.makedirs(out, exist_ok=True)
def save(name, img): cv2.imwrite(os.path.join(out, name), img)

save("PRINT_reference_card.png", cv2.cvtColor(render_card((200, 200, 200)), cv2.COLOR_RGB2BGR))
for kid, k in KITS.items():
    pos, neg = np.array(k["pos"]), np.array(k["neg"])
    save(f"{kid}_positive.jpg", photograph(render_card(lab_to_rgb(pos))))
    save(f"{kid}_negative.jpg", photograph(render_card(lab_to_rgb(neg))))
    save(f"{kid}_borderline.jpg", photograph(render_card(lab_to_rgb((pos + neg) / 2))))
base = lab_to_rgb(np.array(KITS["marquis"]["pos"]))
save("bad_blurred.jpg", photograph(render_card(base), blur=6))
save("bad_glare.jpg", photograph(render_card(base), glare=True))
save("bad_no_card.jpg", photograph(render_card(base), with_card=False))
save("warm_light_positive.jpg", photograph(render_card(base), gain=(1.15, 1.0, 0.8)))
print("samples written to", os.path.abspath(out))
