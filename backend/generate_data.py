"""
generate_data.py - Generates realistic medical claims using 2024 Medicare Fee Schedule data.
"""

import json
import random
import uuid
import sys
from datetime import datetime, timedelta
from pathlib import Path

# --- REAL DATA LIBRARY (Based on 2024 CMS MPFS) ---
# Prices are approximate 2024 National Unadjusted Rates
# --- REAL DATA LIBRARY (Loaded from CSV) ---
import csv

CPT_LIBRARY = []
csv_path = Path("backend/data/cpt_codes_2024.csv")
if csv_path.exists():
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
             try:
                 CPT_LIBRARY.append({
                     "cpt": row["cpt"],
                     "desc": row["description"],
                     "allowed": float(row["allowed_amount"])
                 })
             except ValueError:
                 continue
else:
    # Fallback if CSV missing
    CPT_LIBRARY = [
        {"cpt": "99213", "desc": "Office/outpatient visit, est patient, 20-29 min", "allowed": 92.05},
        {"cpt": "99214", "desc": "Office/outpatient visit, est patient, 30-39 min", "allowed": 129.80},
    ]

PROVIDERS = [
    "North Texas Orthopedics", "Denton Regional Med Center", "City Hopsital ER", 
    "Quest Diagnostics", "LabCorp", "Dr. Smith Family Practice", "Urgent Care Plus"
]

def generate_session_data(session_id: str, count: int = 5):
    """Generate 'count' synthetic claims and inject them into the session."""
    
    # Locate session directory
    # We assume we are running from project root
    session_dir = Path(f"data/user_sessions/{session_id}")
    if not session_dir.exists():
        print(f"Error: Session {session_id} not found in data/user_sessions/")
        return

    extracted_dir = session_dir / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    
    claims_struct_path = session_dir / "claims_struct.json"
    
    existing_claims = []
    if claims_struct_path.exists():
        try:
            existing_claims = json.loads(claims_struct_path.read_text(encoding="utf-8"))
        except:
            pass

    new_rows = []
    
    print(f"Generating {count} claims for session {session_id}...")
    
    for i in range(count):
        doc_uuid = f"GEN-{uuid.uuid4().hex[:8].upper()}"
        date_svc = (datetime.now() - timedelta(days=random.randint(1, 90))).strftime("%Y-%m-%d")
        provider = random.choice(PROVIDERS)
        
        # Create 1-4 line items for this document
        num_lines = random.randint(1, 4)
        doc_total_billed = 0.0
        doc_total_allowed = 0.0
        
        doc_rows = []
        
        for ln in range(num_lines):
            item = random.choice(CPT_LIBRARY)
            
            # Logic: Billed is usually 2x-5x Allowed (ChargeMaster inflation)
            billed = round(item["allowed"] * random.uniform(2.0, 5.0), 2)
            allowed = round(item["allowed"], 2)
            
            # Logic: Insurer pays 80%, Patient 20% (assuming deductible met for simplicity, or random)
            # Let's mix it up
            scenario = random.choice(["deductible", "coinsurance", "copay", "denied"])
            
            insurer_paid = 0.0
            patient_resp = 0.0
            notes = []
            
            if scenario == "deductible":
                patient_resp = allowed
                notes.append("Deductible applied")
            elif scenario == "coinsurance":
                patient_resp = round(allowed * 0.20, 2)
                insurer_paid = round(allowed * 0.80, 2)
            elif scenario == "copay":
                patient_resp = 25.00
                if allowed < 25: patient_resp = allowed
                insurer_paid = max(0.0, allowed - patient_resp)
            elif scenario == "denied":
                patient_resp = billed # Ouch
                allowed = 0.0
                insurer_paid = 0.0
                notes.append("Denied: Medical Necessity")

            row = {
                "doc_id": doc_uuid,
                "line_id": str(ln + 1),
                "page": 1,
                "cell_id": "gen",
                "description": item["desc"],
                "cpt": item["cpt"],
                "billed": billed,
                "allowed": allowed,
                "insurer_paid": insurer_paid,
                "patient_resp": patient_resp,
                "date": date_svc,
                "provider": provider,
                "adjustments": [{"reason": "Contractual Adj", "amount": billed - allowed}] if allowed > 0 else [],
                "modifiers": []
            }
            new_rows.append(row)
            doc_rows.append(row)
            
            doc_total_billed += billed
        
        # Create a stub doc file so it shows in the UI list if we had that view
        doc_meta = {
            "doc_id": doc_uuid,
            "filename": f"Generated_Claim_{doc_uuid}.pdf",
            "upload_date": datetime.now().isoformat(),
            "preview": {"rows": doc_rows}
        }
        (extracted_dir / f"{doc_uuid}.json").write_text(json.dumps(doc_meta, indent=2), encoding="utf-8")
        
    # Append to main list
    all_claims = existing_claims + new_rows
    claims_struct_path.write_text(json.dumps(all_claims, indent=2), encoding="utf-8")
    
    print(f"✅ Successfully added {len(new_rows)} line items across {count} documents.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backend/generate_data.py <session_id> [count]")
        # Try to find current session from data/user_sessions if only 1 exists
        try:
             sessions = list(Path("data/user_sessions").glob("*"))
             if sessions:
                 latest = max(sessions, key=lambda p: p.stat().st_mtime)
                 print(f"No session_id provided. Using latest: {latest.name}")
                 generate_session_data(latest.name, 5)
             else:
                 print("No sessions found.")
        except Exception as e:
            print(f"Error auto-detecting session: {e}")
    else:
        sid = sys.argv[1]
        cnt = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        generate_session_data(sid, cnt)
