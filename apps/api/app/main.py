from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import ocr_jobs_router, problems_router

app = FastAPI(
    title="MathHub API",
    description="Math OCR → Problem DB → Workbook/Exam Platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ocr_jobs_router)
app.include_router(problems_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "mathhub-api"}
