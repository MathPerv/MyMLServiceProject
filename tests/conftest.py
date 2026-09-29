import pytest
from fastapi.testclient import TestClient

from behavior.service.app import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def good_row():
    return {
        "TimeSpentAlone": 4.0,
        "StageFear": "No",
        "SocialEventAttendance": 4.0,
        "GoingOutside": 6.0,
        "DrainedAfterSocializing": "No",
        "FriendsCircleSize": 13.0,
        "PostFrequency": 5.0
    }

@pytest.fixture()
def bad_row():
    {
        "TimeSpentAlone": -10.0,
        "StageFear": "No",
        "SocialEventAttendance": 4.0,
        "GoingOutside": 6.0,
        "DrainedAfterSocializing": "No",
        "FriendsCircleSize": 13.0,
        "PostFrequency": 5.0
    }