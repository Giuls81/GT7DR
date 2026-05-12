import os
import firebase_admin
from firebase_admin import credentials, firestore

# Local list from scrape_dr.py
PILOTI_LIST = [
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
    "RKE_DaviGamer",
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FIREBASE_KEY = os.path.join(BASE_DIR, "firebase_key.json")
COLLECTION = "drivers"

def main():
    if not os.path.exists(FIREBASE_KEY):
        print(f"ERRORE: {FIREBASE_KEY} non trovato.")
        return

    cred = credentials.Certificate(FIREBASE_KEY)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    docs = db.collection(COLLECTION).stream()
    firestore_piloti = sorted([doc.id for doc in docs])
    
    local_set = set(PILOTI_LIST)
    firestore_set = set(firestore_piloti)

    with open("comparison_result.txt", "w", encoding="utf-8") as f:
        f.write("--- CONFRONTO PILOTI ---\n\n")
        
        f.write(f"PILOTI LOCALI ({len(PILOTI_LIST)}):\n")
        for p in sorted(PILOTI_LIST):
            f.write(f"  {p}\n")
            
        f.write(f"\nPILOTI FIRESTORE ({len(firestore_piloti)}):\n")
        for p in firestore_piloti:
            f.write(f"  {p}\n")
            
        f.write("\n--- DIFFERENZE ---\n")
        
        missing_in_firestore = local_set - firestore_set
        if missing_in_firestore:
            f.write("\n[+] Presenti in LOCALE ma NON in Firestore (verranno creati):\n")
            for p in sorted(missing_in_firestore):
                f.write(f"  + {p}\n")
        else:
            f.write("\n[OK] Tutti i locali sono già in Firestore.\n")

        extra_in_firestore = firestore_set - local_set
        if extra_in_firestore:
            f.write("\n[-] Presenti in FIRESTORE ma NON in locale (da cancellare o rinominare?):\n")
            for p in sorted(extra_in_firestore):
                f.write(f"  - {p}\n")
        else:
            f.write("\n[OK] Nessun pilota extra in Firestore.\n")

if __name__ == "__main__":
    main()
