from fastapi import FastAPI
from models import create_all_tables

app = FastAPI(title="CPChain Backend", version="0.1.0")
@app.on_event("startup")
async def on_startup():
    create_all_tables()

@app.get("/")
async def root():
    return {"message": "Welcome to CPChain Backend"}

# Placeholder for future routers
from routers import auth, requests as requests_router, worker as worker_router # Ensure dot for relative import
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(requests_router.router, prefix="/requests", tags=["Requester Operations"])
app.include_router(worker_router.router, prefix="/worker", tags=["Worker Operations"])
