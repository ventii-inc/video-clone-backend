import os

from dotenv import load_dotenv

# Load environment-specific .env file
env = os.getenv("ENV", "local")
dotenv_file = f".env.{env}"
load_dotenv(dotenv_file)

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from app.db import get_db

app = FastAPI(
    title="Video Clone Backend",
    description="FastAPI backend for video clone application",
    version="0.1.0",
)


@app.get("/")
async def root():
    return {"message": "Welcome to Video Clone Backend"}


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    return {"status": "healthy", "database": "connected"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
