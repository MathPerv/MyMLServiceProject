import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

import joblib
import numpy as np
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from behavior import db
from behavior.config import settings

_MISSING = ['', 'na', 'n/a', 'nan', 'null', 'none']
_RANGES = {'TimeSpentAlone': (0, 11), 'SocialEventAttendance': (0, 10),
           'GoingOutside': (0, 7), 'FriendsCircleSize': (0, 15), 'PostFrequency': (0, 10)}

class Features(BaseModel):
    model_config = {"extra": "forbid"}

    TimeSpentAlone: float
    StageFear: Literal['Yes', 'No'] | float
    SocialEventAttendance: float
    GoingOutside: float
    DrainedAfterSocializing: Literal['Yes', 'No'] | float
    FriendsCircleSize: float
    PostFrequency: float

    @field_validator('StageFear', 'DrainedAfterSocializing', mode='before')
    @classmethod
    def is_yes_no_or_empty(cls, value: str| None, info) -> Literal['Yes', 'No'] | float:
        if value in ['Yes', 'No']:
            return value
        if (value is None 
            or (isinstance(value, str) and value.strip().lower() in _MISSING)
            or (isinstance(value, (int, float)) and np.isnan(value))
        ):
            return np.nan
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
    def is_float_or_empty(cls, value: float | None, info) -> float:
        if (
            value is None 
            or (isinstance(value, str) and value.strip().lower() in _MISSING)
            or (isinstance(value, (int, float)) and np.isnan(value)) 
        ):
            return np.nan
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
    def is_nan_or_in_range(cls, value: float, info) -> float:
        nan_condition = np.isnan(value)
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
    if getattr(app.state, "pipeline", "None") is  None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    return {"status": "ready"}


@app.post("/v1/predict")
def predict(x: Features, bg: BackgroundTasks) -> Prediction:
    t0 = time.perf_counter()
    request_id = str(uuid.uuid4())
    payload = x.model_dump()
    frame = pd.DataFrame([payload]).reindex(columns=app.state.meta["features"])

    score = float(app.state.pipeline.predict_proba(frame)[0, 1])

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    bg.add_task(db.save_prediction, request_id, payload, score, app.state.version, latency_ms)

    return Prediction(score=score, model_version = app.state.version, request_id=request_id, latency_ms=latency_ms)