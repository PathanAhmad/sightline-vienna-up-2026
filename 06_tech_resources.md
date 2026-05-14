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

### `pyproject.toml` (uv-friendly)
```toml
[project]
name = "trench-qc"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "pillow",
  "piexif",
  "exifread",
  "imagehash",
  "imagededup",
  "geopandas",
  "shapely",
  "pyproj",
  "folium",
  "ultralytics",      # YOLOv8
  "easyocr",
  "opencv-python-headless",
  "fastapi",
  "uvicorn",
  "streamlit",
  "jinja2",
  "anthropic",        # for VLM explanations
  "python-dotenv",
]
```

### EXIF + GPS extraction
```python
from PIL import Image, ExifTags
from PIL.ExifTags import GPSTAGS

def exif_dict(path):
    img = Image.open(path)
    raw = img._getexif() or {}
    return {ExifTags.TAGS.get(k, k): v for k, v in raw.items()}

def gps_of(path):
    ex = exif_dict(path)
    g = ex.get("GPSInfo")
    if not g: return None
    g = {GPSTAGS.get(k, k): v for k, v in g.items()}
    def dms(t): return t[0] + t[1]/60 + t[2]/3600
    lat = dms(g["GPSLatitude"]) * (-1 if g["GPSLatitudeRef"] == "S" else 1)
    lon = dms(g["GPSLongitude"]) * (-1 if g["GPSLongitudeRef"] == "W" else 1)
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

### YOLOv8 finetune on a tiny labelled set
```python
from ultralytics import YOLO
model = YOLO("yolov8n.pt")
model.train(data="data/dataset.yaml", epochs=80, imgsz=640, batch=16)
results = model("data/photos/sample.jpg")
```
Use **Roboflow** to label 30–50 images Friday night for classes: `duct, sand_bed, ruler, seal, pipe_end`. Don't over-engineer — 50 labelled images beats no labels.

### Claude vision for explanations
```python
import anthropic, base64
client = anthropic.Anthropic()
def describe(img_path):
    b64 = base64.b64encode(open(img_path, "rb").read()).decode()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": (
                    "Fiber-trench QC: in 1 paragraph, state whether this photo shows "
                    "(a) a clearly visible duct/conduit, (b) sand bedding around it, "
                    "(c) a depth ruler legible, (d) end seals on duct, (e) any privacy issues. "
                    "Return JSON with booleans + a one-line note."
                )},
            ],
        }],
    )
    return msg.content[0].text
```

> This is the cheapest path to a defensible "AI signal" — even with zero training data, you have plausibility from day 1, and YOLO adds determinism on top.

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
- [ ] Pre-install Python + uv + main libs locally (no installs on venue Wi-Fi)
- [ ] Anthropic / OpenAI API key set up with €20 credit minimum
- [ ] GitHub private repo seeded
- [ ] Read [02_challenge_1_dpp_erp.md](02_challenge_1_dpp_erp.md) and [03_challenge_2_construction_ai.md](03_challenge_2_construction_ai.md) on the train
- [ ] Decide initial challenge preference (see [07_strategy.md](07_strategy.md))
