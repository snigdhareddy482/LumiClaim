"""LLM Interface for LumiClaim using Groq."""

import logging
from backend.llm_adapters.groq_adapter import complete_text

LOGGER = logging.getLogger(__name__)

def generate_appeal_letter(
    doc_id: str, 
    deny_code: str, 
    diagnosis: str, 
    procedure: str, 
    user_context: str, 
    policy_context: str
) -> str:
    """Generate a formal appeal letter using Groq."""
    
    prompt = f"""
    You are an expert Patient Advocate and Medical Billing Specialist. Write a formal, persuasive appeal letter to a health insurance payer.
    
    CASE DETAILS:
    - Claim ID: {doc_id}
    - Denial Reason/Code: {deny_code}
    - Diagnosis: {diagnosis}
    - Procedure: {procedure}
    
    PATIENT CONTEXT (User Notes):
    {user_context}
    
    INSURANCE POLICY CONTEXT (Summary of Benefits):
    {policy_context}
    
    INSTRUCTIONS:
    1. Introduction: State clearly that this is an appeal for Claim {doc_id}.
    2. Argument: Use the User Notes and Policy Context to argue why the claim should be paid. If the policy mentions coverage for this type of service, cite it.
    3. Medical Necessity: Emphasize that the service was medically necessary.
    4. Tone: Professional, specific, and firm.
    5. Formatting: Use standard business letter format (Subject line, Body, Closing). Do not use placeholders like [Insert Date], assume today's date or leave generic.
    
    OUTPUT:
    Return ONLY the body of the letter. Do not include introductory text like "Here is the letter".
    """
    
    result = complete_text(prompt)
    if not result:
        return "AI Generation Failed (Groq API Error or Missing Key)."
    return result

def summarize_bill(breakdown_text: str, persona: str, grade_level: str) -> str:
    """Generate a persona-based summary of the bill."""
    
    prompt = f"""
    You are a medical billing explainer.
    
    BILL BREAKDOWN:
    {breakdown_text}
    
    TASK:
    Explain this bill to the user.
    
    PERSONA: {persona} (Reading Level: {grade_level})
    
    INSTRUCTIONS:
    - If persona is '5-year-old', use simple analogies (e.g. "The insurance is like a coupon").
    - If persona is 'Spanish', translate the explanation and concept into Spanish.
    - If persona is 'Professional', use precise terminology but keep it concise.
    - Focus on: What they were billed, what insurance paid, and what they owe.
    - Keep it short (max 3-4 sentences).
    
    OUTPUT:
    Just the explanation text.
    """
    
    result = complete_text(prompt)
    if not result:
        return "AI Summary Unavailable."
    return result.strip()
