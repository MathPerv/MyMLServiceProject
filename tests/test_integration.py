import os

import psycopg
import pytest

DATABASE_URL = os.getenv("DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="нужен Postgres: задайте DATABASE_URL"),
]


def test_prediction_is_logged(client, good_row):
    body = client.post("/v1/predict", json=good_row).json()

    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT model_version, score, features->>'time_spent_alone' "
            "FROM predictions WHERE request_id = %s",
            (body["request_id"],),
        ).fetchone()

    assert row is not None
    assert row[0] == body["model_version"]
    assert row[1] == pytest.approx(body["score"])
    assert float(row[2]) ==pytest.approx(good_row["TimeSpentAlone"])


def test_prediction_failure_is_logged(client, bad_row):
    body = client.post("/v1/predict", json=bad_row).json()

    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            """SELECT model_version, score, code
            FROM predictions WHERE request_id = %s""",
            (body["request_id"],),
        ).fetchone()

    assert row is not None
    assert row[0] == body["model_version"]
    assert row[1] is None
    assert row[2] == 422