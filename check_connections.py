
import os
import sys
import requests
import json
import time

def print_result(name, success, message):
    status = "[PASS]" if success else "[FAIL]"
    print(f"{status} | {name}: {message}")

print("--- LumiClaim Connectivity Diagnostic ---\n")

# 1. Check Backend Connectivity
try:
    resp = requests.get("http://127.0.0.1:8080/")
    if resp.status_code == 200:
        print_result("Backend Health", True, "LumiClaim backend is UP and accepting requests.")
    else:
        print_result("Backend Health", False, f"Backend returned status {resp.status_code}")
except requests.exceptions.ConnectionError:
    print_result("Backend Health", False, "Could not connect to http://127.0.0.1:8080. Is uvicorn running?")
except Exception as e:
    print_result("Backend Health", False, f"Error: {e}")

# 2. Check Gemini
gemini_key = os.getenv("GEMINI_API_KEY")
if not gemini_key:
    # Try looking in .env file if it exists, though python doesn't load it by default
    # We'll just report the environment variable state
    print_result("Gemini Config", False, "GEMINI_API_KEY environment variable is NOT set.")
else:
    print_result("Gemini Config", True, "GEMINI_API_KEY is detected.")

try:
    import google.generativeai as genai
    print_result("Gemini Library", True, "google-generativeai package is installed.")
    
    if gemini_key:
        try:
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            # Simple generation test
            response = model.generate_content("Hello, are you there?")
            if response and response.text:
                 print_result("Gemini API", True, "Successfully generated text from Gemini API.")
            else:
                 print_result("Gemini API", False, "Connected but received empty response.")
        except Exception as e:
             print_result("Gemini API", False, f"API Call Failed: {e}")
except ImportError:
    print_result("Gemini Library", False, "google-generativeai package is NOT installed.")


# 3. Check Elasticsearch
use_elastic = os.getenv("USE_ELASTIC", "false").lower() in ("true", "1", "yes")
elastic_url = os.getenv("ELASTIC_URL", "http://localhost:9200")

if use_elastic:
    print(f"\nElasticsearch is ENABLED (USE_ELASTIC=True). Checking {elastic_url}...")
    try:
        resp = requests.get(elastic_url, timeout=2)
        if resp.status_code == 200:
            print_result("Elasticsearch", True, f"Connected to {elastic_url}.")
        else:
            print_result("Elasticsearch", False, f"Responded with status {resp.status_code}.")
    except Exception as e:
        print_result("Elasticsearch", False, f"Connection failed: {e}")
else:
    print_result("Elasticsearch", True, "DISABLED (USE_ELASTIC is not set). Backend will fallback to local search.")

print("\n--- Diagnostic Complete ---")
