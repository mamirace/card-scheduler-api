from datetime import datetime, timezone
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from card_scheduler import schedule_cards, CardInput

app = FastAPI(title="Card Scheduler API", version="1.0.0")

# CORS ayarı (her yerden istek gelsin diye)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Veri modelleri ----
class CardIn(BaseModel):
    card_name: str
    statement_closing_day: Optional[int] = None
    payment_due_day: Optional[int] = None
    grace_period: Optional[int] = None
    country: Optional[str] = None

class ScheduleRequest(BaseModel):
    cards: List[CardIn]
    system_dt: Optional[datetime] = None
    language: str = "tr"
    device_tz: Optional[str] = None

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/schedule")
def schedule(req: ScheduleRequest):
    if not req.cards or len(req.cards) < 1:
        raise HTTPException(status_code=400, detail="En az bir kart vermelisiniz.")

    card_list = [
        CardInput(
            card_name=c.card_name,
            statement_closing_day=c.statement_closing_day,
            payment_due_day=c.payment_due_day,
            grace_period=c.grace_period,
            country=c.country,
        )
        for c in req.cards
    ]

    system_dt = req.system_dt
    if system_dt and system_dt.tzinfo is None:
        system_dt = system_dt.replace(tzinfo=timezone.utc)

    try:
        rows = schedule_cards(
            card_list,
            system_dt=system_dt,
            holidays_csv=None,
            language=req.language,
            device_tz=req.device_tz,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hesaplama hatası: {str(e)}")

    return {"rows": rows}
