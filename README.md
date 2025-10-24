## Smoke Tests

Use these quick checks to verify the backend before diving deeper:

```bash
# 1. Backend health
curl http://localhost:8080/health

# 2. Explain sample document
curl http://localhost:8080/explain/EOB-001

# 3. Policy simulation
curl -X POST http://localhost:8080/simulate \
	-H "Content-Type: application/json" \
	-d '{"doc_id":"EOB-001","deductible_remaining":500,"coinsurance":0.2,"oop_remaining":1800}'

# 4. Compare two EOBs
curl "http://localhost:8080/compare?a=EOB-001&b=EOB-002"

# 5. Generate appeal packet
curl -X POST http://localhost:8080/appeal \
	-H "Content-Type: application/json" \
	-d '{"doc_id":"EOB-001"}'
```

When running the Streamlit UI in Codespaces, set the sidebar API base URL to the forwarded `8080` address (e.g., `https://<your-space>.<region>.codespaces.app:8080`).

## Bench

Produce a quick benchmark using the bundled sample documents:

```bash
python scripts/eval_bench.py
```

## Generate Sample Data

Refresh the synthetic claim corpus (adds EOB-003 through EOB-022) with deterministic output:

```bash
python scripts/synth_eob_gen.py --seed 42
```

## Profiles & Benefits UI

LumiClaim supports storing a per-session insurance plan profile (deductible, coinsurance, OOP, copays) and using it to pre-fill simulations.

Backend endpoints

- POST /profile/set
	- Body: JSON object with keys: session_id (required), plan_year_start (optional), plan_name (optional), deductible_individual, deductible_remaining, coinsurance, oop_max, oop_remaining, copays (object with primary/specialist/er numeric fields).
	- Validates numeric ranges and infers missing values where sensible (e.g., if `deductible_remaining` is missing but `deductible_individual` present, remaining is set to individual; coinsurance defaults to 0.2 if omitted).
	- Persists to: data/user_sessions/<session_id>/profile.json

	Example curl:

	```bash
	curl -X POST http://localhost:8080/profile/set \
		-H 'Content-Type: application/json' \
		-d '{
			"session_id": "session-123",
			"plan_name": "Acme PPO",
			"deductible_individual": 1500,
			"deductible_remaining": 500,
			"coinsurance": 0.2,
			"oop_max": 5000,
			"oop_remaining": 2000,
			"copays": {"primary": 20, "specialist": 40, "er": 200}
		}'
	```

- GET /profile/get?session_id=<session_id>
	- Returns the stored profile JSON if present.

Streamlit frontend (Benefits UI)

- The Upload tab includes a "Benefits (Plan profile)" section. Enter a `Session ID` and plan fields, then click "Save plan profile" to POST to `/profile/set`.
- Click "Load profile" to fetch the profile and populate simulation defaults (deductible remaining, coinsurance, OOP remaining).
- When a profile is loaded, a plan snapshot is shown with a donut chart representing OOP progress and chips for coinsurance, deductible remaining, and copays.
- In the Simulate panel you can toggle "Use plan profile" to autofill and disable manual inputs; the app posts the numeric fields to `/simulate` by default (the server will also accept `session_id` and infer missing fields server-side).

If you want CI to exercise OCR or table parsing features, install the Tesseract binary (for image OCR) and optional table tools (Ghostscript and Java for Camelot/Tabula) on the runner.
