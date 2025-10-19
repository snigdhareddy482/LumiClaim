from fastapi import FastAPI
from models import HealthResponse

app = FastAPI(
    title="LumiClaim API",
    version="0.1.0",
    description="Backend API for LumiClaim platform"
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="healthy", version="0.1.0")
