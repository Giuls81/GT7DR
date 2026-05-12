"""
Retry mirato: scrappa SOLO i piloti senza dati validi in dr.json.
Riprova ciascuno fino a successo o MAX_RETRIES tentativi.
Aggiorna in-place solo le voci dei piloti scrappati con successo.
"""

import os
import re
import json
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AVATAR_DIR = os.path.join(BASE_DIR, "avatars")
DR_JSON = os.path.join(BASE_DIR, "dr.json")
GITHUB_RAW_BASE_URL = "https://raw.githubusercontent.com/Giuls81/GT7DR/main/avatars"

MAX_RETRIES = 8
SLEEP_BETWEEN_ATTEMPTS = 5

STAT_ALIASES = {
    "drPoints": ["dr points"],
    "wins": ["wins"],
    "races": ["races"],
    "top5": ["top 5", "top5"],
    "poles": ["pole positions", "pole position"],
}


def estrai_numero(text):
    if not text:
        return 0
    clean = str(text).replace(",", "").replace(".", "")
    m = re.search(r"(\d+)", clean)
    return int(m.group(1)) if m else 0


def norm_label(s):
    if not s:
        return ""
    s = s.strip().lower().replace(":", "")
    return re.sub(r"\s+", " ", s)


def read_stats_daily_only(driver):
    out = {}
    for lab in driver.find_elements(By.CSS_SELECTOR, "span.stat-label"):
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
            val = lab.find_element(By.XPATH, "following-sibling::span[contains(@class,'stat-value')]").text.strip()
            out[lab_txt] = val
        except Exception:
            continue
    return out


def pick(stats, aliases):
    for a in aliases:
        k = norm_label(a)
        if k in stats:
            return stats[k]
    return ""


def fallback_from_text(text):
    patterns = {
        "drPoints": r"DR\s*Points?[:：]?\s*([0-9\.,]+)",
        "wins": r"Wins?[:：]?\s*([0-9\.,]+)",
        "races": r"Races?[:：]?\s*([0-9\.,]+)",
        "top5": r"Top\s*5[:：]?\s*([0-9\.,]+)",
        "poles": r"Pole\s*Positions?[:：]?\s*([0-9\.,]+)",
    }
    out = {}
    for k, p in patterns.items():
        m = re.search(p, text or "", re.IGNORECASE)
        out[k] = estrai_numero(m.group(1)) if m else 0
    return out


def try_scrape_one(driver, psn):
    """Ritorna dict con dati validi o None se fallisce."""
    driver.get("https://gtsh-rank.com/profile/")
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.ID, "psnid")))

    inp = driver.find_element(By.ID, "psnid")
    inp.clear()
    inp.send_keys(psn)
    driver.find_element(By.XPATH, '//button[text()="GET"]').click()

    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.ID, "result")))
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.stat-label")))

    result_text = (driver.find_element(By.ID, "result").text or "").strip()
    if not result_text or "API not available" in result_text or "API unavailable" in result_text:
        print(f"  [{psn}] API not available")
        return None

    time.sleep(1)

    stats = read_stats_daily_only(driver)
    dr = estrai_numero(pick(stats, STAT_ALIASES["drPoints"]))
    wins = estrai_numero(pick(stats, STAT_ALIASES["wins"]))
    races = estrai_numero(pick(stats, STAT_ALIASES["races"]))
    top5 = estrai_numero(pick(stats, STAT_ALIASES["top5"]))
    poles = estrai_numero(pick(stats, STAT_ALIASES["poles"]))

    fb = fallback_from_text(result_text)
    dr = dr or fb["drPoints"]
    wins = wins or fb["wins"]
    races = races or fb["races"]
    top5 = top5 or fb["top5"]
    poles = poles or fb["poles"]

    if dr == 0 and wins == 0 and races == 0 and top5 == 0 and poles == 0:
        print(f"  [{psn}] tutti i valori sono 0")
        return None

    winrate = f"{(wins / races * 100):.1f}%" if races > 0 else "-"
    avatar_url = ""
    try:
        avatar_el = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "img.driver-photo"))
        )
        png = avatar_el.screenshot_as_png
        with open(os.path.join(AVATAR_DIR, f"{psn}.png"), "wb") as f:
            f.write(png)
        avatar_url = f"{GITHUB_RAW_BASE_URL}/{psn}.png"
    except Exception as e:
        print(f"  [{psn}] avatar fail: {e}")

    return {
        "psn": psn,
        "dr": dr,
        "drPoints": dr,
        "wins": wins,
        "races": races,
        "top5": top5,
        "poles": poles,
        "winrate": winrate,
        "avatarUrl": avatar_url,
    }


def update_dr_json(psn, new_entry):
    with open(DR_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    for i, item in enumerate(data):
        if item.get("psn") == psn:
            data[i] = new_entry
            break
    else:
        data.append(new_entry)
    with open(DR_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    with open(DR_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    targets = [d["psn"] for d in data if d.get("dr", 0) == 0]
    if not targets:
        print("Nessun pilota da riprovare. Esco.")
        return

    print(f"Piloti da riprovare ({len(targets)}): {targets}")

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    success = []
    fail = []
    try:
        for psn in targets:
            print(f"\n=== {psn} ===")
            got = None
            for attempt in range(1, MAX_RETRIES + 1):
                print(f"  tentativo {attempt}/{MAX_RETRIES}...")
                try:
                    got = try_scrape_one(driver, psn)
                except Exception as e:
                    print(f"  [{psn}] exception: {e}")
                    got = None
                if got is not None:
                    break
                time.sleep(SLEEP_BETWEEN_ATTEMPTS)

            if got is not None:
                update_dr_json(psn, got)
                print(f"  OK {psn}: DR={got['dr']} W={got['wins']} R={got['races']} T5={got['top5']} P={got['poles']} ({got['winrate']})")
                success.append(psn)
            else:
                print(f"  FAIL {psn}: nessun dato dopo {MAX_RETRIES} tentativi")
                fail.append(psn)
    finally:
        driver.quit()

    print(f"\n=== RIEPILOGO ===")
    print(f"OK   ({len(success)}): {success}")
    print(f"FAIL ({len(fail)}): {fail}")


if __name__ == "__main__":
    main()
