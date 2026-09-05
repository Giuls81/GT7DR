"""
CI-ready / no GitHub / merge from Firestore / GitHub Avatar Hosting

MODIFICHE PRINCIPALI:
1. ChromeOptions configurato per headless Linux
2. Gestione automatica chromedriver
3. Merge da Firestore come stato precedente
4. AVATAR SU GITHUB:
   - Salva gli avatar nella cartella locale 'avatars/'
   - GitHub Action committerà e pusherà le nuove immagini
   - L'URL salvato su Firestore sarà: https://raw.githubusercontent.com/Giuls81/GT7DR/main/avatars/{psn}.png
5. Output locali dr.json/anomalies.json per debug
"""

import os
import time
import re
import json
import io

import requests
from datetime import datetime, timezone

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import firebase_admin
from firebase_admin import credentials, firestore

# ============================================================
#   LISTA PILOTI
# ============================================================

# Fonte di verita': il ruolo Discord "Piloti RKE", esposto da Odino su
# https://res.ragnarokesport.com/api/rke/piloti. Prima la lista stava scritta a
# mano qui, e in altri tre punti nel repo del sito: un pilota nuovo veniva
# scrapato solo se qualcuno si ricordava di aggiungerlo in tutti e quattro.
#
# La lista qui sotto resta come ripiego per quando l'endpoint non risponde: il
# lavoro settimanale non deve saltare perche' il VPS e' in manutenzione. Puo'
# essere indietro di qualche nome - va bene, e' il ripiego, non la fonte.

ROSTER_ENDPOINT = os.environ.get(
    "RKE_ROSTER_URL", "https://res.ragnarokesport.com/api/rke/piloti"
)

PILOTI_FALLBACK = [
    "RKE_MaxEpico1979",
    "RKE_Ekin",
    "RKE__Giuls",
    "RKE_Bazzo",
    "RKE_Cjcerbola",
    "RKE_Pepyx29",
    "RKE__Carra7",
    "RKE_Micky30",
    "RKE_Monty",
    "RKE_DAVIDE91",
    "RKE_BALDO44",
    "RKE_JigenBiker",
    "RKE_Rey",
    "RKE_87treviGT",
    "RKE_WUORDRALLYCAR",
    "RKE_Morna",
    "RKE_IannuzziJr",
    "RKE_Leon97",
    "RKE-DaviGameR",
]


def carica_piloti():
    """PSN dei piloti RKE dal ruolo Discord, con ripiego sulla lista statica.

    Nel `try` sta solo la rete: se ci finisse dentro anche la stampa, una
    console che non digerisce le emoji verrebbe scambiata per un endpoint giu'
    e lo scrape ripiegherebbe sulla lista vecchia senza motivo.
    """
    try:
        risposta = requests.get(ROSTER_ENDPOINT, timeout=20)
        risposta.raise_for_status()
        dati = risposta.json()
        psns = [p["psn"] for p in dati.get("piloti", []) if p.get("psn")]
        scartati = dati.get("scartati", [])
        if not psns:
            raise ValueError("roster vuoto")
        errore = None
    except Exception as e:
        psns, scartati, errore = [], [], e

    if errore is not None:
        print(f"[!] Roster non raggiungibile ({errore}), uso la lista statica "
              f"di {len(PILOTI_FALLBACK)} piloti")
        return PILOTI_FALLBACK[:]

    if scartati:
        # Hanno il ruolo ma nessun PSN nel nickname: non verranno scrapati.
        etichette = ", ".join(str(s.get("etichetta")) for s in scartati)
        print(f"[!] {len(scartati)} membri col ruolo senza PSN nel nickname: {etichette}")
    print(f"[i] Roster dal ruolo Discord: {len(psns)} piloti")
    return psns


PILOTI_LIST = carica_piloti()

ALL_PILOTI = PILOTI_LIST[:]
piloti = PILOTI_LIST[:]

# ============================================================
#   CONFIG
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Cartella locale dove vengono salvati gli avatar (che poi verranno committati su GitHub)
AVATAR_DIR = os.path.join(BASE_DIR, "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)

CSS_SELECTOR_AVATAR = "img.driver-photo"

FIREBASE_SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "firebase_key.json")
FIRESTORE_COLLECTION = "drivers"
APP_META_COLLECTION = "app_meta"
APP_META_DOC = "latest"

# URL base per gli avatar su GitHub (RAW)
GITHUB_RAW_BASE_URL = "https://raw.githubusercontent.com/Giuls81/GT7DR/main/avatars"

DEBUG_WINS = False

# ============================================================
#   ALIAS LABEL
# ============================================================

STAT_ALIASES = {
    "drPoints": ["dr points"],
    "wins": ["wins"],
    "races": ["races"],
    "top5": ["top 5", "top5"],
    "poles": ["pole positions", "pole position"],
}

# ============================================================
#   HELPERS
# ============================================================

def estrai_numero(text):
    if not text:
        return 0
    clean = str(text).replace(",", "").replace(".", "")
    m = re.search(r"(\d+)", clean)
    return int(m.group(1)) if m else 0

def norm_label(s):
    if not s:
        return ""
    s = s.strip().lower()
    s = s.replace(":", "")
    s = re.sub(r"\s+", " ", s)
    return s

def pick_stat(stats_dict, aliases):
    for a in aliases:
        k = norm_label(a)
        if k in stats_dict:
            return stats_dict[k]
    return ""

# ============================================================
#   DEBUG
# ============================================================

def debug_all_wins(driver, psn):
    els = driver.find_elements(By.XPATH, "//span[contains(@class,'stat-label') and normalize-space()='Wins:']")
    print(f"[{psn}] Wins trovati: {len(els)}")
    for i, lab in enumerate(els, 1):
        try:
            val = lab.find_element(By.XPATH, "following-sibling::span[contains(@class,'stat-value')]").text.strip()
        except Exception:
            val = "?"
        try:
            h3 = lab.find_element(By.XPATH, "preceding::h3[1]").text.strip()
        except Exception:
            h3 = "(no h3)"
        print(f"[{psn}] Wins #{i} = {val} | sezione = {h3}")

# ============================================================
#   PARSE STATS
# ============================================================

def read_stats_daily_only(driver):
    out = {}
    labels = driver.find_elements(By.CSS_SELECTOR, "span.stat-label")

    for lab in labels:
        try:
            heading = lab.find_element(By.XPATH, "preceding::h3[1]").text
        except Exception:
            heading = ""

        if "daily race stats" not in (heading or "").strip().lower():
            continue

        try:
            lab_txt = norm_label(lab.text)
            if not lab_txt:
                continue

            val_span = lab.find_element(
                By.XPATH,
                "following-sibling::span[contains(@class,'stat-value')]",
            )
            out[lab_txt] = val_span.text.strip()
        except Exception:
            continue

    return out

def fallback_from_text(result_text):
    vals = {
        "drPoints": 0,
        "wins": 0,
        "races": 0,
        "top5": 0,
        "poles": 0,
    }

    patterns = {
        "drPoints": [r"DR\s*Points?[:：]?\s*([0-9\.,]+)", r"([0-9\.,]+)\s*DR\s*Points?"],
        "wins": [r"Wins?[:：]?\s*([0-9\.,]+)", r"([0-9\.,]+)\s*Wins?"],
        "races": [r"Races?[:：]?\s*([0-9\.,]+)", r"([0-9\.,]+)\s*Races?"],
        "top5": [r"Top\s*5[:：]?\s*([0-9\.,]+)", r"([0-9\.,]+)\s*Top\s*5"],
        "poles": [r"Pole\s*Positions?[:：]?\s*([0-9\.,]+)", r"([0-9\.,]+)\s*Pole\s*Positions?"],
    }

    for k, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, result_text or "", re.IGNORECASE)
            if m:
                vals[k] = estrai_numero(m.group(1))
                break

    return vals

def get_values_with_fallback(driver, psn):
    result_el = driver.find_element(By.ID, "result")
    result_text = result_el.text or ""

    stats = read_stats_daily_only(driver)

    dr_txt = pick_stat(stats, STAT_ALIASES["drPoints"])
    wins_txt = pick_stat(stats, STAT_ALIASES["wins"])
    races_txt = pick_stat(stats, STAT_ALIASES["races"])
    top5_txt = pick_stat(stats, STAT_ALIASES["top5"])
    poles_txt = pick_stat(stats, STAT_ALIASES["poles"])

    dr_points = estrai_numero(dr_txt)
    wins = estrai_numero(wins_txt)
    races = estrai_numero(races_txt)
    top5 = estrai_numero(top5_txt)
    poles = estrai_numero(poles_txt)

    print(f"  [{psn}] daily raw -> DR:'{dr_txt}' Wins:'{wins_txt}' Races:'{races_txt}' Top5:'{top5_txt}' Poles:'{poles_txt}'")
    print(f"  [{psn}] daily num -> DR={dr_points} Wins={wins} Races={races} Top5={top5} Poles={poles}")

    fb = fallback_from_text(result_text)

    if dr_points == 0 and fb["drPoints"] > 0:
        dr_points = fb["drPoints"]
    if wins == 0 and fb["wins"] > 0:
        wins = fb["wins"]
    if races == 0 and fb["races"] > 0:
        races = fb["races"]
    if top5 == 0 and fb["top5"] > 0:
        top5 = fb["top5"]
    if poles == 0 and fb["poles"] > 0:
        poles = fb["poles"]

    print(f"  [{psn}] final -> DR={dr_points} Wins={wins} Races={races} Top5={top5} Poles={poles}")

    return dr_points, wins, races, top5, poles, result_text

# ============================================================
#   FIREBASE
# ============================================================

def init_firestore():
    """Inizializza Firestore. Ritorna None se fallisce."""
    if not os.path.exists(FIREBASE_SERVICE_ACCOUNT_FILE):
        print(f"ATTENZIONE: manca {FIREBASE_SERVICE_ACCOUNT_FILE}. Salto Firebase.")
        return None
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_FILE)
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        print(f"ATTENZIONE: init Firebase fallita: {e}")
        return None

def load_old_data_from_firestore(db, psn_list):
    """
    Legge da Firestore la collection 'drivers' per tutti i PSN in psn_list.
    """
    old_by_psn = {}
    if db is None:
        print("Firestore non disponibile, nessun dato vecchio caricato.")
        return old_by_psn

    try:
        for psn in psn_list:
            doc_ref = db.collection(FIRESTORE_COLLECTION).document(psn)
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                old_by_psn[psn] = {
                    "dr": int(data.get("dr", data.get("drPoints", 0)) or 0),
                    "drPoints": int(data.get("drPoints", data.get("dr", 0)) or 0),
                    "wins": int(data.get("wins", 0) or 0),
                    "races": int(data.get("races", 0) or 0),
                    "top5": int(data.get("top5", 0) or 0),
                    "poles": int(data.get("poles", 0) or 0),
                    "winrate": str(data.get("winrate", "-")),
                    "avatarUrl": str(data.get("avatarUrl", "")),
                }
                print(f"[FIRESTORE] Caricati dati vecchi per {psn}: DR={old_by_psn[psn]['drPoints']}")
            else:
                print(f"[FIRESTORE] Nessun dato vecchio per {psn}")
    except Exception as e:
        print(f"Errore lettura dati vecchi da Firestore: {e}")

    return old_by_psn

def upload_to_firestore(db, final_results):
    """Carica i risultati finali su Firestore (drivers + app_meta/latest)."""
    if db is None:
        print("Firestore non disponibile, salto upload.")
        return

    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        batch = db.batch()

        for item in final_results:
            psn = item.get("psn", "")
            if not psn:
                continue

            doc_ref = db.collection(FIRESTORE_COLLECTION).document(psn)
            payload = {
                "psn": psn,
                "dr": int(item.get("dr", 0) or 0),
                "drPoints": int(item.get("drPoints", 0) or 0),
                "wins": int(item.get("wins", 0) or 0),
                "races": int(item.get("races", 0) or 0),
                "top5": int(item.get("top5", 0) or 0),
                "poles": int(item.get("poles", 0) or 0),
                "winrate": str(item.get("winrate", "-")),
                # AvatarUrl: se presente, usiamo URL GitHub. Altrimenti vuoto o vecchio.
                "avatarUrl": item.get("avatarUrl", ""),
                "updatedAt": now_iso,
            }
            batch.set(doc_ref, payload, merge=True)

        meta_ref = db.collection(APP_META_COLLECTION).document(APP_META_DOC)
        batch.set(meta_ref, {"updatedAt": now_iso}, merge=True)

        batch.commit()
        print("Upload Firestore OK (drivers + app_meta/latest).")
    except Exception as e:
        print(f"Errore upload Firestore: {e}")

def cleanup_removed_drivers(db, active_psns):
    """Cancella da Firestore i piloti non più presenti in active_psns."""
    if db is None:
        return

    try:
        print("\n🔍 Avvio pulizia piloti rimossi...")
        drivers_ref = db.collection(FIRESTORE_COLLECTION)
        docs = drivers_ref.stream()

        deleted_count = 0
        for doc in docs:
            if doc.id not in active_psns:
                print(f"  🗑️ Rimozione pilota obsoleto: {doc.id}")
                drivers_ref.document(doc.id).delete()
                deleted_count += 1
        
        if deleted_count > 0:
            print(f"✅ Pulizia completata: rimossi {deleted_count} piloti.")
        else:
            print("✨ Nessun pilota obsoleto trovato.")
            
    except Exception as e:
        print(f"⚠️ Errore durante la pulizia: {e}")


# ============================================================
#   ANOMALIE
# ============================================================

def build_anomaly_report(old_by_psn, final_results):
    anomalies = []
    for p in final_results:
        psn = p.get("psn", "")
        if not psn:
            continue

        old = old_by_psn.get(psn, {})
        old_wins = int(old.get("wins", 0) or 0)
        old_races = int(old.get("races", 0) or 0)

        wins = int(p.get("wins", 0) or 0)
        races = int(p.get("races", 0) or 0)
        top5 = int(p.get("top5", 0) or 0)
        poles = int(p.get("poles", 0) or 0)

        reasons = []

        if wins < old_wins:
            reasons.append(f"wins scese: {old_wins} -> {wins}")

        if races > 0 and wins > races:
            reasons.append(f"wins > races: {wins} > {races}")

        if races > 0 and top5 > races:
            reasons.append(f"top5 > races: {top5} > {races}")

        if races > 0 and poles > races:
            reasons.append(f"poles > races: {poles} > {races}")

        if old_races > 0 and races == 0:
            reasons.append(f"races azzerate: {old_races} -> 0")

        if reasons:
            anomalies.append({
                "psn": psn,
                "reasons": reasons,
                "old": {"wins": old_wins, "races": old_races},
                "new": {"wins": wins, "races": races, "top5": top5, "poles": poles},
            })

    return anomalies

# ============================================================
#   RUN
# ============================================================

# Configurazione Chrome per CI headless Linux
options = webdriver.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")
options.add_argument("--disable-gpu")

# Usa webdriver-manager per gestire chromedriver automaticamente
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)

print("=== AGGIORNAMENTO DR PILOTI (Daily Race Stats) ===\n")
print(f"Avatar Mode: GitHub Hosting ({GITHUB_RAW_BASE_URL})\n")

# Inizializza Firestore e carica dati vecchi
db = init_firestore()
old_by_psn = load_old_data_from_firestore(db, ALL_PILOTI)

new_results = {}
count_ok = 0
count_skip = 0

for psn in piloti:
    print("=================================")
    print(f"Lettura dati per: {psn}")
    skip_update = False
    
    current_avatar_url = ""

    try:
        driver.get("https://gtsh-rank.com/profile/")

        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "psnid")))

        input_field = driver.find_element(By.ID, "psnid")
        input_field.clear()
        input_field.send_keys(psn)

        get_button = driver.find_element(By.XPATH, '//button[text()="GET"]')
        get_button.click()

        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "result")))
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.stat-label")))

        result_el = driver.find_element(By.ID, "result")
        result_text_raw = (result_el.text or "").strip()

        if (not result_text_raw) or ("API not available" in result_text_raw) or ("API unavailable" in result_text_raw):
            print(f"  ⚠️  API non disponibile o result vuoto per {psn}")
            print(f"  ⏭️  SKIP: NON aggiorno questo pilota, mantengo dati vecchi da Firestore")
            skip_update = True
        else:
            time.sleep(1)

            if DEBUG_WINS:
                debug_all_wins(driver, psn)

            dr_points, wins, races, top5, poles, _ = get_values_with_fallback(driver, psn)

            if dr_points == 0 and wins == 0 and races == 0 and top5 == 0 and poles == 0:
                print(f"  ⚠️  Tutti valori 0 per {psn}, lettura fallita")
                print(f"  ⏭️  SKIP: NON aggiorno questo pilota, mantengo dati vecchi da Firestore")
                skip_update = True
            else:
                winrate = f"{(wins / races * 100):.1f}%" if races > 0 else "-"

        # GESTIONE AVATAR - Salva LOCALE per poi pushare su GitHub
        try:
            avatar_el = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, CSS_SELECTOR_AVATAR))
            )
            png_bytes = avatar_el.screenshot_as_png
            
            # Salvataggio locale
            local_target = os.path.join(AVATAR_DIR, f"{psn}.png")
            with open(local_target, "wb") as f_img:
                f_img.write(png_bytes)
            
            # Costruisci URL GitHub Raw
            current_avatar_url = f"{GITHUB_RAW_BASE_URL}/{psn}.png"
            print(f"  📸 Avatar salvato localmente -> URL futuro: {current_avatar_url}")
                
        except Exception as e_avatar:
            print(f"  ⚠️  Impossibile acquisire avatar per {psn}: {e_avatar}")

        if not skip_update:
            count_ok += 1
            new_results[psn] = {
                "psn": psn,
                "dr": int(dr_points),
                "drPoints": int(dr_points),
                "wins": int(wins),
                "races": int(races),
                "top5": int(top5),
                "poles": int(poles),
                "winrate": winrate,
                "avatarUrl": current_avatar_url
            }
            print(f"  ✅ AGGIORNATO {psn}: DR={dr_points} Wins={wins} Races={races} Top5={top5} Poles={poles} Win%={winrate}")
        else:
            count_skip += 1
            print(f"  🔄 Uso dati vecchi da Firestore per {psn}")

    except Exception as e:
        count_skip += 1
        print(f"  ❌ Errore per {psn}: {e}")
        print(f"  🔄 Uso dati vecchi da Firestore per {psn}")

    print("  ⏸️  Pausa 3 secondi...\n")
    time.sleep(3)

driver.quit()

# ============================================================
#   MERGE con dati vecchi da Firestore
# ============================================================

final_results = []

for psn in ALL_PILOTI:
    if psn in new_results:
        # Abbiamo dati nuovi (o API ok)
        
        # Se l'avatar URL è vuoto, proviamo a mantenere quello vecchio se esiste
        res = new_results[psn]
        if not res["avatarUrl"]:
             old = old_by_psn.get(psn, {})
             res["avatarUrl"] = old.get("avatarUrl", "")
             
        final_results.append(res)
        continue

    if psn in old_by_psn:
        # Usa dati vecchi da Firestore (incluso avatar vecchio)
        old = old_by_psn[psn]
        final_results.append({
            "psn": psn,
            "dr": old["dr"],
            "drPoints": old["drPoints"],
            "wins": old["wins"],
            "races": old["races"],
            "top5": old["top5"],
            "poles": old["poles"],
            "winrate": old["winrate"],
            "avatarUrl": old.get("avatarUrl", ""),
        })
        print(f"[MERGE] {psn}: usati dati vecchi da Firestore")
        continue

    # Nessun dato vecchio né nuovo => default 0
    final_results.append({
        "psn": psn,
        "dr": 0,
        "drPoints": 0,
        "wins": 0,
        "races": 0,
        "top5": 0,
        "poles": 0,
        "winrate": "-",
        "avatarUrl": "",
    })
    print(f"[MERGE] {psn}: nessun dato disponibile, uso default 0")

# ============================================================
#   OUTPUT LOCALE (debug)
# ============================================================

with open("dr.json", "w", encoding="utf-8") as f:
    json.dump(final_results, f, indent=2, ensure_ascii=False)

print("\n📄 Creato dr.json locale (output debug)")

# ============================================================
#   ANOMALIES REPORT
# ============================================================

anomalies = build_anomaly_report(old_by_psn, final_results)

with open("anomalies.json", "w", encoding="utf-8") as f:
    json.dump(anomalies, f, indent=2, ensure_ascii=False)

print(f"📄 Creato anomalies.json locale (output debug)")
print(f"⚠️  Anomalie trovate: {len(anomalies)}")
for a in anomalies[:20]:
    print(f"   {a['psn']} | {' ; '.join(a['reasons'])}")

upload_to_firestore(db, final_results)

# Pulizia automatica dei piloti rimossi dalla lista
cleanup_removed_drivers(db, ALL_PILOTI)

print("\n=== RIEPILOGO ESECUZIONE ===")
print(f"✅ Aggiornati con successo: {count_ok}")
print(f"⚠️  Saltati (skip/errore):  {count_skip}")
print("============================\n")

# Se troppi piloti falliscono (es. più del 50%), usciamo con errore per allertare GitHub Actions
if len(ALL_PILOTI) > 0:
    success_rate = count_ok / len(ALL_PILOTI)
    if success_rate < 0.5:
        print(f"❌ ERRORE CRITICO: Solo il {success_rate:.0%} dei piloti è stato aggiornato.")
        print("Probabile problema di layout o bot detection. Verificare i log.")
        import sys
        sys.exit(1)

print("✅ Operazione completata correttamente.")
