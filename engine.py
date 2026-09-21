"""engine.py — motore generico: PROFILA QUALSIASI AZIENDA e produce data/<slug>.json.

Giro notturno (GitHub Actions). Chiave KIMI come secret (env KIMI_API_KEY).
Tetto di spesa: config.json -> budget_monthly_usd. Zero LLM se la chiave manca
(fallback a regole: i dati restano veri, il "capire" e' limitato).
"""
import json, os, re, time, urllib.request, datetime

def now(): return datetime.datetime.utcnow().isoformat()+"Z"
def month(): return datetime.datetime.utcnow().strftime("%Y-%m")

# ---------- budget guard ----------
def load_spent():
    try: return json.load(open("data/.budget.json"))
    except Exception: return {"month": month(), "spent": 0.0}

def add_spent(usd):
    b = load_spent()
    if b["month"] != month(): b = {"month": month(), "spent": 0.0}
    b["spent"] += usd
    json.dump(b, open("data/.budget.json", "w"))

def budget_left(cfg):
    b = load_spent()
    if b["month"] != month(): return cfg["budget_monthly_usd"]
    return max(0.0, cfg["budget_monthly_usd"] - b["spent"])

# ---------- rete ----------
def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "radar-bot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def site_text(url, limit=9000):
    try:
        html = http_get(url)
        txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
        txt = re.sub(r"<[^>]+>", " ", txt)
        return re.sub(r"\s+", " ", txt)[:limit]
    except Exception as e:
        return ""

# ---------- LLM (Kimi) ----------
def kimi(messages, model="kimi-k3", max_tokens=1200, budget=1.0):
    """Chiama Kimi; stima costo e lo scrive nel contatore. Ritorna None se no key/budget."""
    key = os.environ.get("KIMI_API_KEY", "")
    if not key: return None
    cfg = json.load(open("config.json"))
    if budget_left(cfg) < budget: return "BUDGET_EXAUSTED"
    body = {"model": model, "messages": messages, "temperature": 0.2,
            "response_format": {"type": "json_object"}, "max_tokens": max_tokens}
    req = urllib.request.Request("https://api.moonshot.ai/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode())
    except Exception as e:
        return None
    u = out.get("usage", {})
    cost = (u.get("prompt_tokens", 0) / 1e6) * 3.0 + (u.get("completion_tokens", 0) / 1e6) * 15.0
    add_spent(cost)
    return out["choices"][0]["message"]["content"]

PROMPT_PROFILE = """Sei il profilatore di un radar B2B. Leggi il testo del sito e rispondi SOLO con JSON:
{{"type": "T1|T2|T3", "hs_codes": ["es. 090111"], "description": "cosa fa, max 25 parole",
  "note": "mercato/obiettivo dichiarato"}}
T1 = commodity di filiera standardizzata (caffe', pasta, plastica...). T2 = custom di filiera
(macchinari, impianti, progetti per il core business del cliente). T3 = custom indiretto
(workwear, merchandising, gadget, servizi di corredo). hs_codes: fino a 2 codici HS6 plausibili
SOLO se T1, altrimenti lista vuota.
SITO: {text}"""


PROMPT_FULL = """Sei il motore di un radar B2B. Dati profilo e sito, produci SOLO JSON con:
{{"dove_andare":[{{"m":"paese","s":0-100,"f":"ora|fase 2|selettivo"}}] max 5,
 "segmenti":[{{"n":"nome","v":0-100}}] max 5,
 "clienti":[{{"n":"nome azienda","s":"segmento","v":0-100}}] max 8: compratori plausibili,
 "competitors":[{{"n":"nome","paese":"..","nota":".."}}] max 6,
 "strategia":"3 leve + piano 90 giorni, max 180 parole"}}
Regole: nomi REALI di aziende esistenti se li conosci con certezza; se non sicuro, usa nomi
descrittivi tipo "es. distributore specializzato X" e metti l'incertezza nella nota.
Punteggi s sensati (0-100). Lingua: italiano.
PROFILO: {profile}
SITO: {text}"""

def generate_full(c, prof, text):
    path = "data/%s.gen.json" % c["slug"]
    if os.path.exists(path):
        try: return json.load(open(path))
        except Exception: pass
    cfg = json.load(open("config.json"))
    if budget_left(cfg) < 0.3:
        return {"_budget": "esaurito"}
    r = kimi([{"role": "user", "content": PROMPT_FULL.format(
        profile=json.dumps(prof, ensure_ascii=False), text=(text or "")[:6000])}],
        max_tokens=2500, budget=1.0)
    if r == "BUDGET_EXAUSTED": return {"_budget": "esaurito"}
    if not r: return {}
    try:
        d = json.loads(r)
        json.dump(d, open(path, "w"), ensure_ascii=False)
        return d
    except Exception:
        return {}

def classify_rules(text):
    t = text.lower()
    if any(w in t for w in ["caffè", "caffe", "grano", "pasta", "polimeri", "fertilizz", "riso", "zucchero"]):
        return {"type": "T1", "hs_codes": [], "description": "commodity (classificazione a regole)", "note": ""}
    if any(w in t for w in ["workwear", "divise", "merchandising", "gadget", "abbigliamento da lavoro"]):
        return {"type": "T3", "hs_codes": [], "description": "custom indiretto (a regole)", "note": ""}
    return {"type": "T2", "hs_codes": [], "description": "custom di filiera (a regole)", "note": ""}

# ---------- dati scambio (T1) ----------
def comtrade(reporter, codes, year):
    url = ("https://comtradeapi.un.org/public/v1/preview/C/A/HS?period=%d&reporterCode=%s"
           "&partnerCode=0&cmdCode=%s&flowCode=M" % (year, reporter, codes))
    try: return json.loads(http_get(url)).get("data", [])
    except Exception: return []

def trade_block(reporter, codes):
    y = datetime.datetime.now().year - 1
    rows = comtrade(reporter, codes, y)
    tot_q = sum(d.get("netWgt") or 0 for d in rows)
    tot_v = sum(d.get("cifvalue") or 0 for d in rows)
    if not tot_q: return None
    out = {"anno": y, "tot_ktons": round(tot_q / 1e6, 1), "tot_bn_eur": round(tot_v / 1e9, 3), "codes": {}}
    for d in rows:
        q = d.get("netWgt") or 0; v = d.get("cifvalue") or 0
        out["codes"][d.get("cmdCode", "?")] = {"qty_kg": q, "unit_value": round(v / q, 4) if q else None}
    return out

# ---------- main ----------
def process(c, cfg):
    prof_path = "data/%s.profile.json" % c["slug"]
    prof = None
    if os.path.exists(prof_path):
        prof = json.load(open(prof_path))
    else:
        text = site_text(c.get("url", ""))
        r = kimi([{"role": "user", "content": PROMPT_PROFILE.format(text=text[:8000] or "(sito non raggiungibile)")}]) if text or True else None
        if r == "BUDGET_EXAUSTED":
            prof = classify_rules(""); prof["note"] = "budget LLM esaurito: profilo a regole"
        elif r:
            try: prof = json.loads(r)
            except Exception: prof = classify_rules(text)
        else:
            prof = classify_rules(text)
        json.dump(prof, open(prof_path, "w"), ensure_ascii=False)
    if c.get("curated") and os.path.exists("data/%s.json" % c["slug"]):
        prev = json.load(open("data/%s.json" % c["slug"]))
        prev["updated"] = now()
        prev["budget"] = {"month": load_spent().get("month"), "spent_usd": round(load_spent()["spent"], 3), "cap_usd": cfg["budget_monthly_usd"]}
        json.dump(prev, open("data/%s.json" % c["slug"], "w"), ensure_ascii=False, indent=1)
        print("curated-refresh", c["slug"]); return
    text = site_text(c.get("url", ""))
    gen = generate_full(c, prof, text)
    out = {"updated": now(), "name": c["name"], "type": prof.get("type", "T2"),
           "profile": prof, "cosa_e_cambiato": [], "dove_andare": [],
           "segmenti": gen.get("segmenti", []), "clienti": gen.get("clienti", []),
           "competitors": gen.get("competitors", []),
           "strategy": gen.get("strategia", ""),
           "generated_by": "kimi-k3", "verification": "da verificare",
           "mode_note": "motore generico v2 (contenuto generato, da verificare)"}
    if gen.get("_budget"):
        out["cosa_e_cambiato"].append({"tag": "azione", "text": "Tetto LLM mensile raggiunto: contenuto a regole/gratuito. Ricarica o attendi il mese prossimo."})
    if gen.get("dove_andare"):
        out["dove_andare"] = gen["dove_andare"]
        out["cosa_e_cambiato"].append({"tag": "azione", "text": "Contenuto generato dal motore (mercati, segmenti, clienti, competitor, strategia): etichetta 'da verificare' finche' le fonti non sono controllate."})
    codes = ",".join(prof.get("hs_codes") or [])
    if prof.get("type") == "T1" and codes:
        tb = trade_block(c.get("market_reporter", "380"), codes)
        if tb:
            out["mercato"] = tb
            uv = [x["unit_value"] for x in tb["codes"].values() if x.get("unit_value")]
            if uv:
                out["cosa_e_cambiato"].append({"tag": "dato", "text":
                    "Mercato %s: %.1f kt, EUR %.2f mld, prezzo medio %.2f EUR/kg (Comtrade reale)"
                    % (c.get("market_reporter", "380"), tb["tot_ktons"], tb["tot_bn_eur"], sum(uv)/len(uv))})
            out["insights"] = ["Profilo %s: %s" % (prof.get("type"), prof.get("description", ""))]
    else:
        out["cosa_e_cambiato"].append({"tag": "azione", "text":
            "Tipo %s rilevato. Modulo dati specifico per questo tipo in arrivo al prossimo giro; "
            "profilo salvato in data/%s.profile.json" % (prof.get("type"), c["slug"])})
    b = load_spent()
    out["budget"] = {"month": b["month"], "spent_usd": round(b["spent"], 3), "cap_usd": cfg["budget_monthly_usd"]}
    json.dump(out, open("data/%s.json" % c["slug"], "w"), ensure_ascii=False, indent=1)
    print("ok", c["slug"], prof.get("type"), "spent", round(b["spent"], 3))

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    cfg = json.load(open("config.json"))
    comps = json.load(open("companies.json"))
    for c in comps["companies"]:
        try: process(c, cfg)
        except Exception as e: print("ERR", c["slug"], e)
