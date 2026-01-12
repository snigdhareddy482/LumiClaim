
import os
import sys
import requests
import json
import time
from dotenv import load_dotenv
load_dotenv(override=True)

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

# 2. Check Groq
groq_key = os.getenv("GROQ_API_KEY")
if not groq_key:
    print_result("Groq Config", False, "GROQ_API_KEY environment variable is NOT set.")
else:
    print_result("Groq Config", True, "GROQ_API_KEY is detected.")

try:
    from groq import Groq
    print_result("Groq Library", True, "groq package is installed.")
    
    if groq_key:
        try:
            client = Groq(api_key=groq_key)
            # Simple generation test
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": "Hello"}],
                model="llama-3.3-70b-versatile",
            )
            if chat_completion.choices[0].message.content:
                 print_result("Groq API", True, "Successfully generated text from Groq API.")
            else:
                 print_result("Groq API", False, "Connected but received empty response.")
        except Exception as e:
             print_result("Groq API", False, f"API Call Failed: {e}")
except ImportError:
    print_result("Groq Library", False, "groq package is NOT installed.")


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
