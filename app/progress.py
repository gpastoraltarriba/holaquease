from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.main import get_current_user
from models import WorkoutSet
from app.prediction import suggest_next_load

router = APIRouter(prefix="/progress", tags=["progress"])

@router.post("/sets")
def create_set(payload: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    ws = WorkoutSet(
        user_id=user.id,
        exercise_id=payload["exercise_id"],
        weight=payload["weight"],
        reps=payload["reps"],
        rir=payload.get("rir", 2),
        rest_sec=payload.get("rest_sec", 120),
        bodyweight=payload.get("bodyweight")
    )
    db.add(ws); db.commit(); db.refresh(ws)
    return {"ok": True, "set_id": ws.id}

@router.get("/suggestion/{exercise_id}")
def get_suggestion(exercise_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    sets = db.query(WorkoutSet).filter_by(user_id=user.id, exercise_id=exercise_id)\
                               .order_by(WorkoutSet.created_at.desc()).limit(10).all()
    load = suggest_next_load(sets)
    if load is None:
        return {"suggested_load": None, "reason": "No history – run baseline test"}
    return {"suggested_load": load}