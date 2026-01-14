from fastapi import FastAPI

app = FastAPI(
    title="Video Clone Backend",
    description="FastAPI backend for video clone application",
    version="0.1.0",
)


@app.get("/")
async def root():
    return {"message": "Welcome to Video Clone Backend"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
