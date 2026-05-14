# Challenge 1 — Product Passport meets ERP

**Source:** https://www.sustainista.net/challengedpp
**Domain expert (on-site whole weekend):** Hubert Forster
**Partners:** Wals Professional, Sustainista, OekoBusiness Wien, BEJ
**Prize:** €1,000

---

## The one-liner

> Battery passports become mandatory **18 Feb 2027** for EV/industrial batteries >2 kWh in the EU. DPP data is machine-readable; ERPs run the business. **Today these layers are separated. Your task is to connect them.**

You must ship a *functional ERP-integrated prototype*, not a slide deck. Data goes in → logic happens → an ERP-related decision or workflow is improved.

---

## What is a Digital Product Passport (DPP)?

A structured, machine-readable record (JSON / XML) attached to a product (often via QR code) that carries:
- Identity (GTIN, serial)
- Composition (materials, hazardous substances, recycled content)
- Carbon footprint & lifecycle data
- Supply-chain origin & due-diligence (DRC cobalt, OECD checks)
- Compliance certificates (CE, notified body)
- Repair, disassembly, end-of-life instructions
- State-of-health / cycle data (batteries)

Regulatory anchors:
- **EU Battery Regulation (2023/1542)** — mandatory passport from 18 Feb 2027
- **ESPR (Ecodesign for Sustainable Products Regulation)** — extends DPP across product categories
- **EU Central DPP Registry** — go-live planned **19 Jul 2026**
- **EN 18222 / EN 18223** standards series — public enquiry 2025, publication expected 2026
- Data model based on **Asset Administration Shell (AAS)** + Semantic Aspect Meta Models (SAMM), aligned with Catena-X (CX-Neptune release Sep 2026)

---

## The provided dataset

**Link:** https://docs.google.com/spreadsheets/d/1-fNplrm3W2oT-hlWjw9BXCWUPfoBfN_7/edit?gid=313695107#gid=313695107

**Product:** Volvo EX90 Twin Motor (MY2024) — 111 kWh NMC811 lithium-ion traction battery.

**Structure:** Single sheet, 12 category blocks (A–M):

| Block | Topic |
|---|---|
| A | General Battery Information |
| B | Carbon Footprint |
| C | Recycled Content |
| D | Responsible Sourcing |
| E | Electrical Characteristics |
| F | Conformity, Labelling & Waste Information |
| G | Detailed Composition & Disassembly |
| H | Authority Information |
| I | Individual Battery Performance & Durability |
| J | State of Health (SoH) |
| K | Expected Lifetime |
| L | Operational Data |
| M | Identification & Technical Metadata |

**Per-row columns:** `No. | Category | Data Point | Description | Access Level | Accessible to | Legal Basis | Volvo EX90 Data Value | Data Status (REAL/MOCK) | Source/Note`

**Notable real-data examples:**
- Cathode: NMC811 — Co 9.6 kg, Ni 50.2 kg, Li 7.4 kg per pack
- Carbon footprint: 65.8 kg CO₂e/kWh (Class B)
- Recycled content: currently 0 % (targets specified for 2031/2036)
- Cell mfg: CATL (Ningde, CN), 85 % renewable energy
- Module assembly: Charleston, SC, USA
- Raw-material origins: DRC (Co), Indonesia (Ni), Chile (Li), China (graphite)
- Traceability: blockchain via **Circulor**
- Notified body: TÜV Rheinland (0035)
- Cells: 238 in 2P7S × 17 modules; warranty 8 yr / 160k km to ≥70 % SoH

**Access-level stratification** (this is key — it's a *real* policy hook to build against):
- L1 public · L2 restricted · L3 authority-only · L4 individual

This is gold — the access tiering is itself something an ERP can enforce (who-sees-what when scanning a QR).

---

## Provided ERP environments (pick one)

### weclapp (recommended — partner-aligned)
- **Register:** https://www.weclapp.com/en/register/?partnercode=P2289
- REST + JSON, OpenAPI/Swagger spec, supports webhooks
- Key entities: `Article`, `Customer`, `Supplier`, `PurchaseOrder`, `Inventory`, `customAttributes` (use these for passport fields)
- Wals Professional (the partner) literally builds weclapp ↔ fulfillment / Power Automate plugins — so going weclapp wins us mentor sympathy
- Rate-limited; cache master data, use webhooks not polling, exp-backoff on 429

### Odoo (open-source alternative)
- **Register:** https://www.odoo.com
- XML-RPC (mature) + JSON-RPC + experimental REST in v17+
- Webhooks landed natively in v17 (Community & Enterprise)
- For custom DPP submodel: write a small Odoo module with `product.template` extension, or expose a custom REST controller

> **Tactical call:** weclapp gets you Wals Professional's attention; Odoo is more familiar to most devs and easier to self-host for the demo. If we go weclapp, plan ~2 hrs to learn the API quirks.

---

## Eligible ERP workflows (pick one or combine)

1. Procurement & supplier evaluation
2. Product master data & materials
3. Inventory / stock management
4. Returns, repair, refurbishment
5. Compliance & audit workflows
6. Recycling & end-of-life decisions
7. Sustainability reporting / CO₂ analysis
8. Any realistic ERP process you can defend

**Constraint:** focus on **1–2 business objects max** (product, supplier, purchase order, inventory, return, recycling record). Don't try to model everything.

---

## Suggested ideas from the brief (jumping-off points)

| Bucket | Concrete idea |
|---|---|
| Procurement | Supplier-risk intelligence — passport data → flags risky suppliers, missing declarations |
| Procurement | CO₂-aware sourcing — recommend lower-impact alternative when ordering |
| Compliance | Passport-completeness assistant — pre-audit gap scan against EU registry schema |
| Service / circular | Repair-vs-refurbish-vs-recycle decision tool using composition + repairability |
| Service / circular | Recycling value estimator — material weights × spot prices → recovery value |
| Reporting | Product-level ESG dashboards / CSRD-feeders |

---

## Deliverables (must have all three)

1. **ERP-integrated prototype** — actual data flow, actual ERP, not a mock
2. **Business model** — user, buyer, pricing, growth story
3. **3-minute demo** — problem → live solution → business case

## Demo skeleton (3 min)
- **0:00–0:30** Problem & who feels it
- **0:30–2:00** Live working prototype using the DPP/Battery Passport data
- **2:00–3:00** ERP workflow we slot into, buyer persona, value, growth

---

## Saturday tech checkpoint

The Sustainista team does an integration check **late Saturday afternoon/evening**. Working ERP integration must be visible by then — not optional.

---

## Evaluation rubric (from organizer site, applies to both challenges)

| Weight | Criterion |
|---|---|
| 30 % | Technology Quality & AI Execution |
| 20 % | Problem Fit & Solution Relevance |
| 15 % | Design, UX & Process Logic |
| 15 % | Business Model & Implementation Potential |
| 10 % | Impact, Sustainability & Responsible AI |
| 10 % | Pitch, Demo & Documentation Quality |

> Tech quality is the biggest single bucket. The brief is also explicit: a mock as the *primary* solution is **not acceptable**.

---

## Buyer / user personas (lifted from the brief)

| Persona | Pain | Why they pay |
|---|---|---|
| Compliance managers | Audit-ready passport info | Reduces risk / manual docs |
| Procurement teams | Better supplier/material decisions | Sourcing quality, sustainability |
| Sustainability managers | Product-level ESG inputs | Saves time, accuracy |
| ERP consultants | New DPP integration services | Consulting revenue |
| Manufacturers | Operationalize passport rules | Regulation → manageable process |
| Repair/service teams | Product data for repair calls | Less waste |
| Recyclers | Material/component data | Better recovery value |

---

## What "good" looks like at demo time

A QR scan (or simulated scan) → fetches DPP record → ERP automatically:
- Creates/updates an article with proper material breakdown
- Routes a workflow (e.g., "this return is repairable because section G says so" / "this supplier is flagged because section D shows missing cobalt origin certificate")
- Logs a decision tied to that passport version

Bonus credibility: **respect the access-level tiering** so authority-only fields don't leak to a public scan.

---

## Open-source references worth knowing

- **Battery Pass Project data model:** https://github.com/batterypass/BatteryPassDataModel
- **Eclipse Tractus-X** (Catena-X reference implementation) — open-source AAS submodels, digital twin registry
- **CIRPASS** (ended Mar 2024) — foundational EU project, still good context: https://cirpassproject.eu/
