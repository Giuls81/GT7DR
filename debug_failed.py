"""Debug v3: provo varianti con trattino e altre alternative per i 2 PSN ancora KO."""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

URL = "https://gtsh-rank.com/profile/"

VARIANTS = {
    "RKE_DaviGamer": [
        "RKE-DaviGamer",
        "RKE-davigamer",
        "RKE-DAVIGAMER",
        "RKE_DAVIGAMER",
        "Davi-Gamer",
        "DaviGamer97",
        "RKE_Davi-Gamer",
    ],
    "RKE_WUORDRALLYCAR": [
        "RKE-WUORDRALLYCAR",
        "RKE-WuordRallyCar",
        "RKE-wuordrallycar",
        "RKE_Wuordrallycar",
    ],
}


def try_one(driver, psn):
    print(f"  -> '{psn}'", end=" ")
    driver.get(URL)
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "psnid")))
    inp = driver.find_element(By.ID, "psnid")
    inp.clear()
    inp.send_keys(psn)
    driver.find_element(By.XPATH, '//button[text()="GET"]').click()
    deadline = time.time() + 12
    populated = False
    while time.time() < deadline:
        try:
            result_text = driver.find_element(By.ID, "result").text
            stat_count = len(driver.find_elements(By.CSS_SELECTOR, "span.stat-label"))
            if result_text.strip() or stat_count > 0:
                populated = True
                break
        except Exception:
            pass
        time.sleep(0.5)
    try:
        result_text = driver.find_element(By.ID, "result").text
    except Exception:
        result_text = ""
    stat_count = len(driver.find_elements(By.CSS_SELECTOR, "span.stat-label"))
    api_err = "API not available" in result_text or "API unavailable" in result_text
    if populated and stat_count > 0 and not api_err:
        print(f"OK | stats={stat_count} | {result_text[:80]!r}")
        return True
    elif api_err:
        print(f"API ERR | {result_text[:80]!r}")
    else:
        print(f"empty (stats={stat_count})")
    return False


def main():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    drv = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    try:
        for canonical, variants in VARIANTS.items():
            print(f"\n=== {canonical} ===")
            for v in variants:
                try:
                    if try_one(drv, v):
                        print(f"  *** WORKING VARIANT: '{v}' ***")
                        break
                except Exception as e:
                    print(f"  exception: {type(e).__name__}: {e}")
                time.sleep(1)
    finally:
        drv.quit()


if __name__ == "__main__":
    main()
