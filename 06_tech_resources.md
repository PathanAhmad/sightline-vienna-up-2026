# Tech resources & code starters

A pre-flight reference so you don't burn Friday googling.

---

## Challenge 1 — DPP + ERP

### Battery passport dataset (provided)
- **Google Sheet:** https://docs.google.com/spreadsheets/d/1-fNplrm3W2oT-hlWjw9BXCWUPfoBfN_7
- Volvo EX90 — 111 kWh NMC811 pack
- 12 category blocks (A–M), access-level field per row, "REAL vs MOCK" status field

### Pull the sheet into Python
```python
import pandas as pd
SHEET_ID = "1-fNplrm3W2oT-hlWjw9BXCWUPfoBfN_7"
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=313695107"
df = pd.read_csv(url)
df.columns = [c.strip() for c in df.columns]
df = df[df["Data Status"].fillna("").str.contains("REAL")]
```

### weclapp REST starter
```python
import os, requests
BASE = "https://YOURTENANT.weclapp.com/webapp/api/v1"
HEADERS = {"AuthenticationToken": os.environ["WECLAPP_TOKEN"]}

def list_articles():
    r = requests.get(f"{BASE}/article", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["result"]

def create_article(name, sku, custom):
    body = {
        "name": name,
        "articleNumber": sku,
        "customAttributes": custom,   # list of {attributeDefinitionId, ...}
    }
    return requests.post(f"{BASE}/article", json=body, headers=HEADERS).json()
```

Pre-register: https://www.weclapp.com/en/register/?partnercode=P2289 — do this **Thursday night** so the trial is warmed up.

### Odoo XML-RPC starter (Odoo 17)
```python
import xmlrpc.client
url, db, user, pwd = "https://YOUR.odoo.com", "yourdb", "you@example.com", "APIKEY"
common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, user, pwd, {})
models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

# Add a passport JSON to a product via a custom field (or x_dpp_payload)
models.execute_kw(db, uid, pwd, "product.template", "create", [{
    "name": "Volvo EX90 Battery Pack",
    "default_code": "BATT-EX90-NMC811",
    "x_dpp_payload": json.dumps(passport_dict),
}])
```

### Reference data models
- Battery Pass Project model: https://github.com/batterypass/BatteryPassDataModel
- Catena-X / Tractus-X: open-source AAS submodels, digital twin registry — good prior art if asked
- EU Battery Regulation 2023/1542 — the legal anchor

---

## Challenge 2 — Construction photo AI

### Project skeleton
```
trench-qc/
  data/photos/             # ÖGIG sample photos drop here
  data/route.geojson
  src/
    ingest.py
    geomatch.py
    checks/
      duct.py
      bedding.py
      ruler_ocr.py
      seal.py
      privacy.py
      forensics.py
    classify.py
    report.py
  app.py                   # streamlit
  pyproject.toml
```

### `pyproject.toml` (uv-friendly — actual)

The committed [pyproject.toml](pyproject.toml) at the repo root is the source of truth. It deliberately ships a lean set, with the rationale below for what was cut from earlier drafts:

```toml
[project]
name = "vienna-up"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
  "pillow",
  "pillow-heif",            # iPhone photos are HEIC; Claude API needs JPEG
  "imagehash",              # pHash dedup; 50 MB total deps
  "geopandas",              # 1.0+ uses pyogrio — no Fiona/GDAL pain on Windows
  "folium",
  "streamlit",
  "anthropic",              # VLM as the QC engine, not a sidecar
  "numpy",
  "opencv-python-headless",
]
```

**Cut on purpose:**
- `piexif`, `exifread` — `PIL.ExifTags` reads GPS cleanly in Pillow 12+
- `imagededup` — pulls torch (~2.5 GB), redundant with `imagehash` for our scale
- `shapely`, `pyproj` — installed transitively by geopandas; no need to list
- `ultralytics`, `easyocr` — 3–6 GB + CUDA roulette; 30-image / 4-class training in <4 h is below the practical floor (Ultralytics' own small-data guidance + 2025 hackathon postmortems agree). VLM handles "is X present" better; YOLO-World zero-shot is a Plan-B if we genuinely need bounding boxes.
- `fastapi`, `uvicorn`, `jinja2` — Streamlit is one process; only add if Saturday we split front/back
- `python-dotenv` — Streamlit reads `.env` natively via `st.secrets`

### EXIF + GPS extraction (Pillow 12 API, HEIC-safe)
```python
import pillow_heif
from PIL import Image
from PIL.ExifTags import IFD, GPS

pillow_heif.register_heif_opener()  # HEIC support for iPhone photos

def gps_of(path):
    exif = Image.open(path).getexif()
    g = exif.get_ifd(IFD.GPSInfo)
    if not g or GPS.GPSLatitude not in g:
        return None
    def dms(t): return float(t[0]) + float(t[1]) / 60 + float(t[2]) / 3600
    lat = dms(g[GPS.GPSLatitude]) * (-1 if g[GPS.GPSLatitudeRef] == "S" else 1)
    lon = dms(g[GPS.GPSLongitude]) * (-1 if g[GPS.GPSLongitudeRef] == "W" else 1)
    return (lat, lon)
```

### Geo-match to nearest segment
```python
import geopandas as gpd
from shapely.geometry import Point

route = gpd.read_file("data/route.geojson").to_crs(4326)
def match_segment(lat, lon):
    p = Point(lon, lat)
    route["d"] = route.distance(p)
    return route.loc[route["d"].idxmin()]
```

If the GeoJSON is in EPSG:31287 (Austrian Lambert), `to_crs(4326)` once then both sides agree.

### Perceptual hash for duplicate detection
```python
import imagehash, glob
from PIL import Image
hashes = {}
for p in glob.glob("data/photos/*.jpg"):
    h = imagehash.phash(Image.open(p))
    for q, hq in hashes.items():
        if h - hq < 6:        # Hamming distance threshold
            print(f"DUPLICATE: {p} ~ {q}")
    hashes[p] = h
```

### Error Level Analysis (ELA) sanity check
```python
from PIL import Image, ImageChops
def ela(path, quality=90):
    orig = Image.open(path).convert("RGB")
    orig.save("_tmp.jpg", "JPEG", quality=quality)
    re = Image.open("_tmp.jpg")
    diff = ImageChops.difference(orig, re)
    return diff   # bright regions = recompression-sensitive = likely edited
```

### YOLO — skipped (with a Plan B)

We are **not** training a custom YOLO model. Reasons (all from research, not vibes):
- 30 hand-labeled images / 4 classes is below the practical small-data floor; Ultralytics' own guidance is "hundreds per class," and freeze-backbone-with-augmentation still overfits hard on demo-day off-distribution photos.
- 3–6 GB install + Windows CUDA roulette eats setup time we don't have.
- Demo failure risk is asymmetric: a YOLO that fires false-positives on the judge's chosen photo loses the room.

**Plan B if Saturday we genuinely need a bounding box** (e.g. auto-cropping the ruler so the VLM can read tick marks): use **YOLO-World** zero-shot — text-prompted detection, no training, no labeling. Pre-cache the weights Thursday if we want it on the table.

### Claude vision — the QC engine (Haiku 4.5 default, Batch + caching)

Cost reality per [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) for 500 photos:

| Model | Standard | Batch API (50% off) |
|---|---|---|
| Haiku 4.5 | ~$1.20 | ~**$0.60** |
| Sonnet 4.6 | ~$3.40 | ~$1.70 |
| Opus 4.7 | ~$8 | ~$4 |

**Default Haiku 4.5.** Escalate to Sonnet only on photos where Haiku returns "ambiguous." Use the **Batch API** for the full pass (non-realtime). Cache the system prompt + few-shot + ÖGIG rule list (identical across all 500 calls) — cache reads cost 0.1× input.

```python
import anthropic, base64, pillow_heif
from PIL import Image
from io import BytesIO

pillow_heif.register_heif_opener()  # iPhone HEIC support

client = anthropic.Anthropic()

QC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "duct_visible":          {"type": "string", "enum": ["yes", "no", "occluded"]},
        "bedding_sand_visible":  {"type": "string", "enum": ["yes", "no", "occluded"]},
        "ruler_legible":         {"type": "string", "enum": ["yes", "no", "occluded"]},
        "end_seals_present":     {"type": "string", "enum": ["yes", "no", "occluded"]},
        "estimated_depth_cm":    {"type": ["integer", "null"]},  # ÖGIG spec: 30–40 cm
        "note":                  {"type": "string", "maxLength": 200},
    },
    "required": ["duct_visible", "bedding_sand_visible", "ruler_legible",
                 "end_seals_present", "estimated_depth_cm", "note"],
}

SYSTEM = (
    "You are a fiber-trench QC inspector for ÖGIG. ÖGIG's spec requires trench depth "
    "30–40 cm with sand bedding around the duct and end seals on every duct. "
    "Evaluate the photo against this checklist. If a detail is occluded or unclear, "
    "say 'occluded' rather than guessing."
)

def qc(img_path: str) -> dict:
    img = Image.open(img_path).convert("RGB")             # HEIC → RGB
    img.thumbnail((1092, 1092))                            # ≤1568 image tokens
    buf = BytesIO(); img.save(buf, "JPEG", quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode()

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": [
                # Anthropic's own guidance: image BEFORE text
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": "Return JSON matching the QC schema."},
            ],
        }],
        # Structured Outputs: strict schema, no regex parsing
        # https://platform.claude.com/docs/en/build-with-claude/structured-outputs
    )
    return msg.content[0].text  # JSON string per schema
```

**Throughput:** prefer one image per request in parallel (better isolation, easier retries) over multi-image batching, unless cross-photo comparison is needed. For the full 500-photo pass, use the [Batch API](https://platform.claude.com/docs/en/build-with-claude/batch-processing).

**HEIC gotcha:** Anthropic API does **not** accept HEIC. iPhone photos must be converted to JPEG before upload — the `pillow-heif` opener above + `.convert("RGB")` + JPEG save handles it.

### Folium map output
```python
import folium
m = folium.Map(location=[48.21, 16.37], zoom_start=14)
for seg in segments:
    color = {"complete": "green", "partial": "orange", "missing": "red"}[seg.status]
    folium.PolyLine(seg.coords, color=color, weight=6,
                    tooltip=f"{seg.id}: {seg.status}").add_to(m)
m.save("report/map.html")
```

### HTML report (Jinja2)
Each segment block → status badge, photo thumbnails, signals table, AI explanation. Wrap the Folium map in an `<iframe>` at the top. PDF export = browser print-to-PDF, don't waste time on a PDF lib.

---

## Cross-challenge essentials

### Environment
- Python 3.11 via `uv` (faster than venv)
- `.env` for API keys (Anthropic, OpenAI, weclapp token)
- Git from minute zero — local + a private GitHub repo

### Demo recording fallback
Record a 90-second screen capture of your working flow **by Saturday night**. If anything blows up during the live pitch Sunday, you fall back to video. Quick is fine — OBS or QuickTime / Win+G.

### Pitch deck
- Slide 1: problem in one number (€42 M / 18 Feb 2027)
- Slide 2: what we built (one screenshot)
- Slide 3: how it works (3-step arrow diagram)
- Slide 4: who pays (persona + price)
- Slide 5: scale story
- Optional slide 6: team

Keep it to 5–6 slides. Demo eats the time, slides are bumper rails.

---

## Pre-Friday checklist (do tonight / Friday morning)

- [ ] Join the Slack
- [ ] Pre-register weclapp **and** Odoo (free trials)
- [ ] Pre-install Python + uv + main libs locally — `uv sync` at repo root (no installs on venue Wi-Fi)
- [ ] Anthropic / OpenAI API key set up with €20 credit minimum
- [ ] GitHub private repo seeded
- [ ] Read [02_challenge_1_dpp_erp.md](02_challenge_1_dpp_erp.md) and [03_challenge_2_construction_ai.md](03_challenge_2_construction_ai.md) on the train
- [ ] Decide initial challenge preference (see [07_strategy.md](07_strategy.md))
