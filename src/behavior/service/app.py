import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

import joblib
import json
import numpy as np
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request , RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from behavior import db
from behavior.config import settings

_MISSING = ['', 'na', 'n/a', 'nan', 'null', 'none']
_RANGES = {'TimeSpentAlone': (0, 11), 'SocialEventAttendance': (0, 10),
           'GoingOutside': (0, 7), 'FriendsCircleSize': (0, 15), 'PostFrequency': (0, 10)}
RENAME_MAP = {
        "TimeSpentAlone": "time_spent_alone",
        "StageFear": "stage_fear",
        "SocialEventAttendance": "social_event_attendance",
        "GoingOutside": "going_outside",
        "DrainedAfterSocializing": "drained_after_socializing",
        "FriendsCircleSize": "friends_circle_size",
        "PostFrequency": "post_frequency",
    }
PREDICT_PATH = "/v1/predict"

class Features(BaseModel):
    model_config = {"extra": "forbid"}

    TimeSpentAlone: float | None
    StageFear: Literal['Yes', 'No'] | None
    SocialEventAttendance: float | None
    GoingOutside: float | None
    DrainedAfterSocializing: Literal['Yes', 'No'] | None
    FriendsCircleSize: float | None
    PostFrequency: float | None

    @field_validator('StageFear', 'DrainedAfterSocializing', mode='before')
    @classmethod
    def is_yes_no_or_empty(cls, value: str| None, info) -> Literal['Yes', 'No'] | None:
        if value in ['Yes', 'No']:
            return value
        if (value is None 
            or (isinstance(value, str) and value.strip().lower() in _MISSING)
            or (isinstance(value, (int, float)) and np.isnan(value))
        ):
            return None
        raise ValueError(
            f"Only 'Yes', 'No', None, np.nan, {', '.join(map(repr, _MISSING))} are allowed"
            f" in feature {info.field_name}"
        )

    @field_validator(
        'TimeSpentAlone', 
        'SocialEventAttendance',
        'GoingOutside',
        'FriendsCircleSize',
        'PostFrequency',
        mode='before'
    )
    @classmethod
    def is_float_or_empty(cls, value: float | None, info) -> float | None:
        if (
            value is None 
            or (isinstance(value, str) and value.strip().lower() in _MISSING)
            or (isinstance(value, (int, float)) and np.isnan(value)) 
        ):
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        raise ValueError(
            f"Only int, float values or None, np.nan, {', '.join(map(repr, _MISSING))} are allowed"
            f" in feature {info.field_name}"
        )

    # корректность ввода гарантирована before-validator
    @field_validator(
            'TimeSpentAlone', 
            'SocialEventAttendance',
            'GoingOutside',
            'FriendsCircleSize',
            'PostFrequency',
            mode='after'
        )
    @classmethod
    def is_nan_or_in_range(cls, value: float | None, info) -> float | None:
        nan_condition = value is None
        range_condition = _RANGES[info.field_name][0] <= value <= _RANGES[info.field_name][1]
        if nan_condition or range_condition:
            return value
        raise ValueError(
            f"Feature {info.field_name} must be in interval " 
            f"[{_RANGES[info.field_name][0]}, {_RANGES[info.field_name][1]}] or nan."
            f"Got: {value}"
        )


class Prediction(BaseModel):

    score: float
    model_version: str
    request_id: str
    latency_ms: float
    code: int 


@asynccontextmanager
async def lifespan(app: FastAPI):
    bundle = joblib.load(settings.model_path)
    app.state.pipeline = bundle["pipeline"]
    app.state.meta = bundle["metadata"]
    app.state.version = bundle["metadata"]["version"]

    db.init()
    yield
    app.state.pipeline = None

app = FastAPI(title="behavior-service", version="1.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "model_version": getattr(app.state, "version", "unknown")}


@app.get("/ready")
def ready():
    if getattr(app.state, "pipeline", None) is  None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    return {"status": "ready"}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.url.path != PREDICT_PATH:
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()},
        )

    t0 = time.perf_counter()
    request_id = str(uuid.uuid4())

    raw_body = await request.body()
    try:
        raw = json.loads(raw_body)
    except Exception:
        raw = {"_raw": raw_body.decode("utf-8", errors="replace")}

    if isinstance(raw, dict):
        payload = {RENAME_MAP.get(k, k): v for k, v in raw.items()}
    else:
        payload = {"_raw": raw}

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    bg = BackgroundTasks()
    bg.add_task(
        db.save_prediction,
        request_id,
        payload,
        None,
        getattr(app.state, "version", "unknown"),
        latency_ms,
        422,
    )

    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "request_id": request_id,
            "model_version": app.state.version,
            "code": 422
        },
        headers={"request_id": request_id},
        background=bg,
    )


@app.post("/v1/predict")
def predict(x: Features, bg: BackgroundTasks):
    t0 = time.perf_counter()
    request_id = str(uuid.uuid4())
    payload = {RENAME_MAP.get(k, k): v for k, v in x.model_dump().items()}
    frame = pd.DataFrame([payload]).reindex(columns=list(app.state.meta["features"]))

    try:
        score = float(app.state.pipeline.predict_proba(frame)[0, 1])
    except Exception:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        bg.add_task(
            db.save_prediction, request_id, payload, None,
            app.state.version, latency_ms, 500,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Scoring failed", "request_id": request_id, "code": 500},
            headers={"request_id": request_id},
            background=bg,
        )

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    bg.add_task(
        db.save_prediction, request_id, payload, score,
        app.state.version, latency_ms, 200,
    )
    return Prediction(
        score=score, model_version=app.state.version,
        request_id=request_id, latency_ms=latency_ms, code=200,
    )