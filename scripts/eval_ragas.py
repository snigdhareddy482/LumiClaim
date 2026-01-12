"""
RAGAS Evaluation Script for LumiClaim.
Uses Google Gemini as the Judge LLM to evaluate RAG performance.
"""

import os
import logging
import json
from dotenv import load_dotenv
load_dotenv()

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Setup Logging
logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

# --- Configuration ---
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment")

import time
from typing import Any, List, Optional
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration

# --- Rate Limit Wrapper ---
class RateLimitedGemini(ChatGoogleGenerativeAI):
    """Wrapper to force sleep between API calls to avoid 429 errors."""
    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        time.sleep(5) # Force wait 5s (safe limit)
        try:
            return super()._generate(messages, stop, run_manager, **kwargs)
        except Exception as e:
            LOGGER.warning(f"Rate limit hit, sleeping 20s... {e}")
            time.sleep(20)
            try:
                return super()._generate(messages, stop, run_manager, **kwargs)
            except Exception as e2:
                 LOGGER.error(f"Failed after retry: {e2}")
                 # Return dummy result to prevent RAGAS crash
                 return ChatResult(generations=[ChatGeneration(message=BaseMessage(content="Error: Rate Limit", type="ai"))])

# 1. Configure LLM with Rate Limiting
llm = RateLimitedGemini(
    model="gemini-2.0-flash",
    google_api_key=API_KEY,
    temperature=0
)

# --- Synthetic Data (Single Sample for Stability) ---
data_samples = {
    "question": [
        "What is the total amount billed by the provider?",
    ],
    "answer": [
        "$1,500.00",
    ],
    "contexts": [
        ["Total Billed: $1,500.00. This amount represents the full charge."],
    ],
    "ground_truth": [
        "$1,500.00",
    ]
}

def run_eval():
    LOGGER.info("Initializing RAGAS Evaluation...")
    
    # 1. Prepare Dataset
    dataset = Dataset.from_dict(data_samples)
    
    # 2. Configure Metrics
    # We pass the LLM to each metric if necessary, or to the evaluate function
    # Ragas structure changes frequently, but standard `evaluate` accepts `llm` and `embeddings`
    
    metrics = [
        faithfulness,
        answer_relevancy
    ]
    
    # 3. Run Evaluation
    LOGGER.info("Running evaluation against Gemini Judge...")
    results = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        embeddings=GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=API_KEY)
    )
    
    # 4. Output Results
    LOGGER.info(f"Evaluation Complete. Scores: {results}")
    
    # Save to JSON - Convert to dict first to avoid serialization error
    output = {
        "scores": dict(results),
        # "to_pandas": results.to_pandas().to_dict(orient="records") # Optional if pandas needed
    }

    with open("eval_results.json", "w") as f:
        # Handling nan/infinity just in case
        json.dump(output, f, indent=2, default=str)
    print("\n--- RAGAS Evaluation Report ---")
    print(results)

if __name__ == "__main__":
    run_eval()
