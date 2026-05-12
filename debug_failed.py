"""
Debug v2: prova varianti dei PSN falliti + cattura browser console + #result finale.
"""
import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

URL = "https://gtsh-rank.com/profile/"

VARIANTS = {
    "RKE_WUORDRALLYCAR": [
        "RKE_WUORDRALLYCAR",
        "RKE_wuordrallycar",
        "wuordrallycar",
        "WuordRallyCar",
        "RKE_WuordRallyCar",
    ],
    "RKE_MORNA": [
        "RKE_MORNA",
        "RKE_Morna",
        "Morna",
        "MORNA",
    ],
    "RKE_DaviGamer": [
        "RKE_DaviGamer",
        "RKE_davigamer",
        "DaviGamer",
        "Davigamer",
    ],
}


def try_one(driver, psn):
    print(f"  -> '{psn}'")
    driver.get(URL)
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "psnid")))
    inp = driver.find_element(By.ID, "psnid")
    inp.clear()
    inp.send_keys(psn)
    driver.find_element(By.XPATH, '//button[text()="GET"]').click()

    # Aspetto fino a 15s che #result si popoli oppure compaia un h3
    deadline = time.time() + 15
    populated = False
    while time.time() < deadline:
        try:
            result_text = driver.find_element(By.ID, "result").text
            h3_count = len(driver.find_elements(By.TAG_NAME, "h3"))
            stat_count = len(driver.find_elements(By.CSS_SELECTOR, "span.stat-label"))
            if result_text.strip() or h3_count > 0 or stat_count > 0:
                populated = True
                break
        except Exception:
            pass
        time.sleep(0.5)

    # Stato finale
    try:
        result_text = driver.find_element(By.ID, "result").text
    except Exception:
        result_text = "(no #result)"
    stat_count = len(driver.find_elements(By.CSS_SELECTOR, "span.stat-label"))
    body_text = driver.find_element(By.TAG_NAME, "body").text
    has_api_err = "API not available" in body_text or "API unavailable" in body_text

    # Browser console
    try:
        logs = driver.get_log('browser')
    except Exception:
        logs = []
    relevant = [l for l in logs if l.get('level') in ('SEVERE', 'WARNING') or 'Error' in l.get('message', '') or 'Failed' in l.get('message', '')]

    print(f"     populated={populated} | #result(50)={result_text[:50]!r} | stat_labels={stat_count} | api_err={has_api_err}")
    for l in relevant[:5]:
        print(f"     CONSOLE [{l.get('level')}]: {l.get('message', '')[:200]}")

    return populated and stat_count > 0


def main():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    opts.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    drv = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    try:
        for canonical, variants in VARIANTS.items():
            print(f"\n=== {canonical} ===")
            for v in variants:
                try:
                    ok = try_one(drv, v)
                    if ok:
                        print(f"  *** WORKING VARIANT: '{v}' ***")
                        break
                except Exception as e:
                    print(f"  -> '{v}' exception: {type(e).__name__}: {e}")
                time.sleep(2)
    finally:
        drv.quit()


if __name__ == "__main__":
    main()
