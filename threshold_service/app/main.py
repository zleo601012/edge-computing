from fastapi import FastAPI
from .api import router

app = FastAPI(title="Multi-node Wastewater Threshold Service", version="1.0")
app.include_router(router)

@app.get("/health")
def health():
    return {"ok": True}
