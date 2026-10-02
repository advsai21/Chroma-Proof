# ChromaProof - Role 1: Vision & Classification
# Prototype only. Rules are DEMO rules, not validated toxicology.
# Card design: 4 ArUco markers (ids 0-3) at the corners + white/gray/black patches
# + a circular "reagent window". Everything is located in a fixed canonical layout.

# %%
# Colab already ships OpenCV. If import fails, run:  !pip -q install opencv-python-headless numpy
import json
import cv2
import numpy as np

CLASSIFIER_VERSION = "ChromaProof-CV-v3.0-card"

# ---------------- canonical card layout (pixels in the 600x400 rectified card) ----------------
CARD_W, CARD_H = 600, 400
BOX, QUIET, MK = 80, 10, 60                      # marker box, white quiet zone, marker size
MARKER_ORIGINS = {0: (20, 20), 1: (500, 20), 2: (500, 300), 3: (20, 300)}   # TL, TR, BR, BL
PATCH_CENTERS = {"white": (180, 130), "gray": (260, 130), "black": (340, 130)}
PATCH_HALF = 22
ROI_CENTER, ROI_R, ROI_SAMPLE_R = (300, 270), 40, 30
ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

# ---------------- configuration (tune these on your own sample images) ----------------
CFG = {
    "blur_min": 60.0,               # variance of Laplacian on rectified card
    "glare_max_frac": 0.03,         # max fraction of saturated pixels in ROI/patches
    "white_range": (150, 252),      # measured white patch must lie here (exposure check)
    "min_patch_contrast": 60.0,     # white - black (measured)
    "roi_max_std": 22.0,            # reagent window must be roughly uniform
    "expected_patches": {"white": 240.0, "gray": 128.0, "black": 25.0},  # printed card values
    "ref_pos_rgb": (110, 40, 130),  # DEMO "positive" colour (purple)
    "ref_neg_rgb": (225, 215, 170), # DEMO "negative" colour (pale yellow)
    "max_ref_dist": 45.0,           # farther than this from both references -> Inconclusive
    "min_margin": 0.25,             # |d_neg-d_pos|/(d_neg+d_pos) below this -> Inconclusive
}


def rgb_to_lab(rgb):
    px = np.uint8([[np.clip(rgb, 0, 255)]])
    l, a, b = cv2.cvtColor(px, cv2.COLOR_RGB2LAB)[0, 0].astype(float)
    return np.array([l * 100 / 255, a - 128, b - 128])


# ---------------- card detection + rectification ----------------
def find_card(img_bgr):
    """Return the card warped to 600x400 (BGR) or None if all 4 markers are not found."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    detector = cv2.aruco.ArucoDetector(ARUCO_DICT, cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return None
    found = {int(i): c.reshape(4, 2) for i, c in zip(ids.flatten(), corners)}
    if not all(k in found for k in MARKER_ORIGINS):
        return None
    src, dst = [], []
    for mid, (ox, oy) in MARKER_ORIGINS.items():
        x0, y0 = ox + QUIET, oy + QUIET
        dst += [(x0, y0), (x0 + MK, y0), (x0 + MK, y0 + MK), (x0, y0 + MK)]
        src += found[mid].tolist()
    H, _ = cv2.findHomography(np.float32(src), np.float32(dst), 0)
    if H is None:
        return None
    return cv2.warpPerspective(img_bgr, H, (CARD_W, CARD_H))


def _patch(rgb, c, half=PATCH_HALF):
    x, y = c
    q = half // 2
    return rgb[y - q:y + q, x - q:x + q].reshape(-1, 3)


def _roi_pixels(rgb):
    mask = np.zeros(rgb.shape[:2], np.uint8)
    cv2.circle(mask, ROI_CENTER, ROI_SAMPLE_R, 255, -1)
    return rgb[mask > 0]


# ---------------- main entry point (this is the Role 1 -> Role 2 contract) ----------------
def process_image(img_bgr, cfg=CFG, ref_pos_lab=None, ref_neg_lab=None):
    out = {"quality_status": "RETAKE", "quality_reasons": [], "result": "Inconclusive",
           "confidence": 0.0, "explanation": "", "classifier_version": CLASSIFIER_VERSION,
           "features": {}}
    if img_bgr is None or getattr(img_bgr, "size", 0) == 0:
        out["quality_reasons"].append("Image could not be read. Capture or upload again.")
        out["explanation"] = "No valid image."
        return out

    card = find_card(img_bgr)
    if card is None:
        out["quality_reasons"].append(
            "Reference card not found (or image too blurry). Keep all 4 corner markers sharp, visible and in frame.")
        out["explanation"] = "Calibration impossible without the reference card."
        return out

    rgb = cv2.cvtColor(card, cv2.COLOR_BGR2RGB)
    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    reasons, feats = [], {}

    # --- quality gate ---
    feats["blur_score"] = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if feats["blur_score"] < cfg["blur_min"]:
        reasons.append("Image is blurry. Hold the phone steady and tap to focus.")

    meas = {k: np.median(_patch(rgb, c), axis=0) for k, c in PATCH_CENTERS.items()}
    white_v, black_v = float(meas["white"].mean()), float(meas["black"].mean())
    feats["white_patch"], feats["black_patch"] = white_v, black_v
    lo, hi = cfg["white_range"]
    if white_v < lo:
        reasons.append("Too dark. Move to better light.")
    elif white_v > hi:
        reasons.append("Overexposed. Reduce direct light.")
    if white_v - black_v < cfg["min_patch_contrast"]:
        reasons.append("Low contrast on reference patches. Improve lighting and retake.")

    roi_px = _roi_pixels(rgb).astype(float)
    sat_pts = [_patch(rgb, c) for c in PATCH_CENTERS.values()] + [roi_px.astype(np.uint8)]
    sat = np.concatenate(sat_pts)
    feats["glare_frac"] = float((sat.min(axis=1) >= 250).mean())
    if feats["glare_frac"] > cfg["glare_max_frac"]:
        reasons.append("Glare detected on the card/reagent window. Tilt the phone or shade the light.")

    feats["roi_std"] = float(roi_px.std(axis=0).mean())
    if feats["roi_std"] > cfg["roi_max_std"]:
        reasons.append("Reagent window is not uniform (shadow, reflection or occlusion). Retake.")

    out["features"] = feats
    if reasons:
        out["quality_reasons"] = reasons
        out["explanation"] = "Image failed the quality gate; no classification attempted."
        return out
    out["quality_status"] = "PASS"

    # --- calibration: per-channel linear fit measured -> expected (white/gray/black) ---
    exp = cfg["expected_patches"]
    xs = np.array([meas[k] for k in ("white", "gray", "black")])      # 3x3
    ys = np.array([exp[k] for k in ("white", "gray", "black")])
    roi_med = np.median(roi_px, axis=0)
    corrected = np.zeros(3)
    for ch in range(3):
        a, b = np.polyfit(xs[:, ch], ys, 1)
        if a <= 0:
            out["quality_status"] = "RETAKE"
            out["quality_reasons"] = ["Calibration failed (patch values inconsistent). Retake."]
            out["explanation"] = "Calibration sanity check failed."
            return out
        corrected[ch] = np.clip(a * roi_med[ch] + b, 0, 255)
    feats["roi_raw_rgb"] = roi_med.round(1).tolist()
    feats["roi_calibrated_rgb"] = corrected.round(1).tolist()

    # --- classification: nearest demo reference in LAB, with uncertainty gate ---
    lab = rgb_to_lab(corrected)
    if ref_pos_lab is not None and ref_neg_lab is not None:      # per-kit references (LAB)
        pos, neg = np.array(ref_pos_lab, float), np.array(ref_neg_lab, float)
        max_dist = 0.6 * float(np.linalg.norm(pos - neg))
    else:
        pos, neg, max_dist = rgb_to_lab(cfg["ref_pos_rgb"]), rgb_to_lab(cfg["ref_neg_rgb"]), cfg["max_ref_dist"]
    d_pos = float(np.linalg.norm(lab - pos))
    d_neg = float(np.linalg.norm(lab - neg))
    margin = abs(d_neg - d_pos) / max(d_neg + d_pos, 1e-6)
    feats.update(d_pos=round(d_pos, 1), d_neg=round(d_neg, 1), margin=round(margin, 3))
    out["confidence"] = round(float(margin), 3)   # uncertainty cue, NOT a probability

    if min(d_pos, d_neg) > max_dist:
        out["result"] = "Inconclusive"
        out["explanation"] = "Colour is far from both demo reference colours (unfamiliar colour)."
    elif margin < cfg["min_margin"]:
        out["result"] = "Inconclusive"
        out["explanation"] = "Colour lies between the two reference colours (borderline)."
    elif d_pos < d_neg:
        out["result"] = "Positive"
        out["explanation"] = "Calibrated colour is closest to the demo positive reference."
    else:
        out["result"] = "Negative"
        out["explanation"] = "Calibrated colour is closest to the demo negative reference."
    out["explanation"] += " Presumptive demo result only; laboratory confirmation required."
    return out


# ---------------- synthetic sample generator (so you can test with NO real kit images) ----------------
def render_card(reagent_rgb):
    card = np.full((CARD_H, CARD_W, 3), 235, np.uint8)               # RGB
    for mid, (ox, oy) in MARKER_ORIGINS.items():
        cv2.rectangle(card, (ox, oy), (ox + BOX, oy + BOX), (255, 255, 255), -1)
        m = cv2.aruco.generateImageMarker(ARUCO_DICT, mid, MK)
        card[oy + QUIET:oy + QUIET + MK, ox + QUIET:ox + QUIET + MK] = m[..., None]
    vals = CFG["expected_patches"]
    for k, (x, y) in PATCH_CENTERS.items():
        v = int(vals[k])
        cv2.rectangle(card, (x - PATCH_HALF, y - PATCH_HALF), (x + PATCH_HALF, y + PATCH_HALF), (v, v, v), -1)
    cv2.circle(card, ROI_CENTER, ROI_R + 4, (60, 60, 60), -1)
    cv2.circle(card, ROI_CENTER, ROI_R, tuple(int(c) for c in reagent_rgb), -1)
    return card


def photograph(card_rgb, gain=(1, 1, 1), blur=0, glare=False, with_card=True, seed=0):
    rng = np.random.default_rng(seed)
    canvas = np.full((800, 1000, 3), (90, 80, 70), np.float32)
    canvas += rng.normal(0, 4, canvas.shape)
    quad = np.float32([[180, 150], [820, 110], [860, 620], [140, 660]])
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [CARD_W, 0], [CARD_W, CARD_H], [0, CARD_H]]), quad)
    if with_card:
        warp = cv2.warpPerspective(card_rgb, M, (1000, 800)).astype(np.float32)
        mask = cv2.warpPerspective(np.full((CARD_H, CARD_W), 255, np.uint8), M, (1000, 800)) > 0
        canvas[mask] = warp[mask]
    canvas *= np.float32(gain)
    if glare and with_card:
        c = M @ np.array([ROI_CENTER[0], ROI_CENTER[1], 1.0])
        layer = np.zeros((800, 1000), np.float32)
        cv2.circle(layer, (int(c[0] / c[2]), int(c[1] / c[2])), 40, 1.0, -1)
        layer = cv2.GaussianBlur(layer, (0, 0), 6)
        canvas += 400 * layer[..., None]
    canvas = np.clip(canvas, 0, 255).astype(np.uint8)
    if blur:
        canvas = cv2.GaussianBlur(canvas, (0, 0), blur)
    return cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR)


SCENARIOS = {
    "good_positive":      dict(reagent=(112, 45, 128), expect="Positive"),
    "good_negative":      dict(reagent=(224, 214, 172), expect="Negative"),
    "warm_light_positive": dict(reagent=(112, 45, 128), gain=(1.15, 1.0, 0.8), expect="Positive"),
    "dim_light_negative": dict(reagent=(224, 214, 172), gain=(0.75, 0.75, 0.75), expect="Negative"),
    "borderline_colour":  dict(reagent=(168, 128, 150), expect="Inconclusive"),
    "unfamiliar_green":   dict(reagent=(40, 160, 60), expect="Inconclusive"),
    "blurred":            dict(reagent=(112, 45, 128), blur=6, expect="RETAKE"),
    "glare":              dict(reagent=(112, 45, 128), glare=True, expect="RETAKE"),
    "no_card":            dict(reagent=(112, 45, 128), with_card=False, expect="RETAKE"),
}


def run_scenarios(verbose=True):
    ok = True
    for name, s in SCENARIOS.items():
        kw = {k: v for k, v in s.items() if k not in ("reagent", "expect")}
        img = photograph(render_card(s["reagent"]), **kw)
        r = process_image(img)
        got = "RETAKE" if r["quality_status"] == "RETAKE" else r["result"]
        passed = got == s["expect"]
        ok &= passed
        if verbose:
            print(f"{'PASS' if passed else 'FAIL'} {name:20s} expect={s['expect']:12s} got={got:12s} "
                  f"conf={r['confidence']}  {r['quality_reasons'] or r['explanation'][:50]}")
    return ok


# %%
if __name__ == "__main__":
    print("all scenarios ok:", run_scenarios())
    # Save a demo image + show the JSON contract Role 2 will consume
    img = photograph(render_card((112, 45, 128)))
    cv2.imwrite("demo_positive.jpg", img)
    print(json.dumps(process_image(img), indent=2))
