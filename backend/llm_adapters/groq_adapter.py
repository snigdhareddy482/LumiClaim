import base64
import json
import os
import io
from typing import Any, Dict, List, Optional

from groq import Groq
from dotenv import load_dotenv

# Ensure env vars are loaded
load_dotenv(override=True)

class NotConfigured(RuntimeError):
    """Raised when the Groq adapter cannot run due to missing setup."""

class QuotaExceededError(RuntimeError):
    """Raised when the Groq API returns a rate limit error (429)."""

def _get_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    return Groq(api_key=api_key)

def _encode_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode('utf-8')

def extract_text_from_image(image_bytes: bytes) -> str:
    """Uses Groq Vision (Llama 3.2) to OCR an image."""
    client = _get_client()
    if not client:
        return ""

    try:
        base64_image = _encode_image(image_bytes)
        
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all text from this image exactly as it appears. output raw text only."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                            },
                        },
                    ],
                }
            ],
            model="llama-3.2-11b-vision-preview",
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        if "429" in str(e):
             print(f"[GROQ QUOTA] Hit 429 limit: {e}")
             raise QuotaExceededError("Groq API Quota Exceeded") from e
        print(f"[GROQ OCR] Failed: {e}")
        return ""

def extract_structured_eob_text(text: str) -> List[Dict[str, Any]]:
    """Extract EOB data as structured JSON list from raw text using Groq."""
    client = _get_client()
    if not client:
        return []

    prompt = """
    You are an expert OCR data extractor for Medical EOBs.
    Extract meaningful claim line items from this text.
    Find procedure codes (CPT), billed amounts, dates, and patient responsibility.
    
    Structure the output as a JSON list of objects.
    Keys: date, cpt, description, billed, allowed, insurer_paid, patient_resp.
    All numeric fields should be floats (0.0 if missing).
    
    Return ONLY valid JSON. No markdown formatting.
    """

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", # Use text model for reasoning on text
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        
        content = completion.choices[0].message.content
        # Ensure it's a list
        data = json.loads(content)
        if isinstance(data, dict):
            # Groq sometimes wraps in a root key even if asked for list depending on model 
            # But we asked for list structure in prompt.
            # Llama 3 often likes {"data": [...]}
            for key in data:
                 if isinstance(data[key], list):
                     return data[key]
            return [data] # fallback
        return data
        
    except Exception as e:
        if "429" in str(e):
             print(f"[GROQ QUOTA] Hit 429 limit: {e}")
             raise QuotaExceededError("Groq API Quota Exceeded") from e
        print(f"[GROQ JSON TEXT] Failed: {e}")
        return []

def verbalize(persona: str, level: str, payload: Dict[str, Any]) -> str:
    """Return a concise summary using Groq."""
    client = _get_client()
    if not client:
        return ""
        
    context = json.dumps(payload, cls=json.JSONEncoder)
    prompt = f"Explain this medical bill to a {persona} at a {level} reading level. Keep it short and reassuring.\n\nData: {context}"
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return completion.choices[0].message.content
    except Exception:
        return ""

def complete_text(prompt: str, model: str = "llama-3.3-70b-versatile") -> str:
    """Generate text completion using Groq."""
    client = _get_client()
    if not client:
        return ""
    
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"[GROQ TEXT] Failed: {e}")
        return ""
