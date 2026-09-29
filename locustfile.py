import random

from locust import HttpUser, task


class PredictUser(HttpUser):

    @task(10)
    def post_predict(self):
        payload = {
            "TimeSpentAlone": random.randint(0, 11),
            "StageFear": random.choice(["Yes", "No", None]),
            "SocialEventAttendance": random.randint(0, 10),
            "GoingOutside": random.randint(0, 7),
            "DrainedAfterSocializing": random.choice(["Yes", "No"]),
            "FriendsCircleSize": random.randint(0, 15),
            "PostFrequency": random.randint(0, 10)
        }
        self.client.post("/v1/predict", json=payload, name="POST /v1/predict")

    @task(1)
    def get_health(self):
        self.client.get("/health", name="GET /health")