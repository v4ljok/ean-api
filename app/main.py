from fastapi import FastAPI, HTTPException
from app.scraper import collect_offers, build_front_response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="EAN Offers API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "https://varuosad-production.up.railway.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/search")
def search(ean: str):
    ean = (ean or "").strip()
    if not ean:
        raise HTTPException(status_code=400, detail="ean is required")

    offers = collect_offers(ean)
    if not offers:
        return {"query_ean": ean, "product": None, "offers": []}

    return build_front_response(offers, query_ean=ean)