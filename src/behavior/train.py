import json
import os
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import sklearn
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OrdinalEncoder
from sklearn.impute import KNNImputer

DATA_PATH = Path(os.getenv("DATA_PATH", "datasets/telco_churn.csv"))
MODEL_NAME = os.getenv("MODEL_NAME", "behavior")
EXPERIMENT = os.getenv("MLFLOW_EXPERIMENT", "behavior")
C = float(os.getenv("C", "1.0"))
MIN_GAIN = float(os.getenv("GATE_MIN_GAIN", "0.0"))
SEED = 42
SKOPS_TRUSTED = ["numpy.dtype", "sklearn.compose._column_transformer._RemainderColsList"]

NUMERIC = [
    'time_spent_alone', 'social_event_attendance', 'going_outside', 
    'friends_circle_size', 'post_frequency'
]
CATEGORICAL = ['stage_fear', 'drained_after_socializing']


def load_and_validate(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = df.columns.str.lower()
    missing = set(NUMERIC + CATEGORICAL + ["personality"]) - set(df.columns)
    if missing:
        raise ValueError(f"в данных нет колонок: {sorted(missing)}")
    if len(df) < 1000:
        raise ValueError(f"слишком мало строк: {len(df)}")
    if not set(df["Churn"].unique()) <= {"Extrovert", "Introvert"}:
        raise ValueError(f"неожиданные значения таргета: {df['personality'].unique()[:5]}")
    df["target"] = (df['personality'] == 'Extrovert').astype(int)
    df = df.drop(columns='personality')
    return df


def build_pipeline(c: float) -> Pipeline:
    cat_pipeline = Pipeline([
        (
            'encoder',
            OrdinalEncoder(categories=[['No', 'Yes']] * 2,
            handle_unknown='use_encoded_value', unknown_value=np.nan)
        ),
        ('imputer', KNNImputer(n_neighbors=3, add_indicator=True)),
    ])

    num_pipeline = Pipeline([
        ('imputer', KNNImputer(n_neighbors=3, add_indicator=True)),
        ('scaler', StandardScaler()),
    ])

    preprocess = ColumnTransformer(
        transformers=[
            ('cat_transformer', cat_pipeline, CATEGORICAL),
            ('num_transformer', num_pipeline, NUMERIC)
        ],
        remainder='passthrough'
    )
    return Pipeline([("preprocess", preprocess), ("model", LogisticRegression(max_iter=1000, C=c))])


def champion_auc(client: MlflowClient) -> tuple[str | None, float | None]:
    try:
        mv = client.get_model_version_by_alias(MODEL_NAME, "champion")
    except MlflowException:
        return None, None
    return mv.version, client.get_run(mv.run_id).data.metrics.get("roc_auc")


def main() -> dict:
    df = load_and_validate(DATA_PATH)
    features = NUMERIC + CATEGORICAL
    x_train, x_test, y_train, y_test = train_test_split(
        df[features], df["target"], test_size=0.2, stratify=df["target"], random_state=SEED
    )

    pipeline = build_pipeline(C).fit(x_train, y_train)
    proba = pipeline.predict_proba(x_test)[:, 1]
    auc = float(roc_auc_score(y_test, proba))
    precision, recall, thresholds = precision_recall_curve(y_test, proba)
    threshold = float(thresholds[recall[:-1] >= 0.70].max())

    mlflow.set_experiment(EXPERIMENT)
    client = MlflowClient()
    with mlflow.start_run() as run:
        metadata = {"features": features, "threshold": round(threshold, 4), "n_train": len(x_train),
                    "data_rows": len(df), "sklearn": sklearn.__version__}
        mlflow.log_params({"C": C, "model": "LogisticRegression", "seed": SEED, "data": str(DATA_PATH)})
        mlflow.log_metrics({"roc_auc": auc, "pr_auc": float(average_precision_score(y_test, proba)), "threshold": threshold})
        mlflow.log_dict(metadata, "metadata.json")
        info = mlflow.sklearn.log_model(
            pipeline,
            name="model",
            registered_model_name=MODEL_NAME,
            skops_trusted_types=SKOPS_TRUSTED
        )
        version = info.registered_model_version

    old_version, old_auc = champion_auc(client)
    promoted = old_auc is None or auc > old_auc + MIN_GAIN
    client.set_registered_model_alias(MODEL_NAME, "challenger", version)
    if promoted:
        client.set_registered_model_alias(MODEL_NAME, "champion", version)

    result = {"run_id": run.info.run_id, "version": version, "roc_auc": round(auc, 4),
              "champion_before": old_version, "champion_auc_before": old_auc, "promoted": promoted}
    print(json.dumps(result, ensure_ascii=False))
    xcom = Path("/airflow/xcom")
    if xcom.is_dir():
        (xcom / "return.json").write_text(json.dumps(result))
    return result


if __name__ == "__main__":
    main()