"""
sbc_parser.py - Extract benefits (Deductible, OOP Max) from Summary of Benefits and Coverage (SBC) PDFs.
Uses heuristics based on standard SBC templates.
"""

import re
import logging
from typing import Dict, Any, Optional

from backend.extractors import parse_pdf

LOGGER = logging.getLogger(__name__)

def parse_sbc(file_path: str) -> Dict[str, Any]:
    """Parse an SBC PDF and return found plan attributes."""
    
    # 1. Text Extraction
    _, raw_pages, notes = parse_pdf(file_path)
    if not raw_pages:
        return {"error": "No text content found in PDF", "notes": notes}
        
    full_text = "\n".join(raw_pages)
    
    # 2. Normalization
    # SBCs are often table-based text.
    # "What is the overall deductible? $500 / individual"
    
    # regex patterns
    # We look for amounts like $500 or $1,000.
    amount_re = r"\$[\d,]+"
    
    results = {
        "deductible_individual": None,
        "deductible_family": None,
        "oop_individual": None,
        "oop_family": None,
        "coinsurance": None,
        "full_text": full_text # Expose text for RAG
    }
    
    # --- Deductible ---
    # Look for the section
    deduct_match = re.search(r"overall deductible", full_text, re.IGNORECASE)
    if deduct_match:
        # Get context window around "Overall deductible"
        start = deduct_match.start()
        context = full_text[start:start+300] # look ahead
        
        # Find all dollar amounts
        amounts = re.findall(r"\$([\d,]+)", context)
        # Context usually: "$500 / individual" or "$500 Individual / $1000 Family"
        # Heuristic: First amount is Indiv, Second is Family (if present)
        
        if amounts:
            try:
                results["deductible_individual"] = float(amounts[0].replace(",", ""))
                if len(amounts) > 1:
                    results["deductible_family"] = float(amounts[1].replace(",", ""))
            except:
                pass

    # --- Out-of-Pocket Limit ---
    oop_match = re.search(r"out-of-pocket limit", full_text, re.IGNORECASE)
    if oop_match:
        start = oop_match.start()
        context = full_text[start:start+300]
        amounts = re.findall(r"\$([\d,]+)", context)
        if amounts:
            try:
                results["oop_individual"] = float(amounts[0].replace(",", ""))
                if len(amounts) > 1:
                    results["oop_family"] = float(amounts[1].replace(",", ""))
            except:
                pass
                
    # --- Coinsurance ---
    # This is harder as it's often "20%" or "0%" text in a "Physician" row.
    # We might look for "coinsurance".
    # "General Coinsurance" isn't a standard SBC term, usually it's per service.
    # We'll skip for now or set a default.
    
    return results

