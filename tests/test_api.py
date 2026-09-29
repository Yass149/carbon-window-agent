from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from cwa.agent.schemas import AgentAnswer, RunResult, TraceStep
from cwa.api.main import create_app
from cwa.config import Settings
from cwa.store.db import Database


def result():
    return RunResult(
        run_id=str(uuid4()),
        answer=AgentAnswer(answer="Use the cleanest window."),
        ungrounded_numbers=[],
        steps=1,
        tokens_in=0,
        tokens_out=0,
        cost_usd=0,
        latency_ms=1,
        trace=[TraceStep(idx=0, kind="model", name="fake")],
        model="fake",
        prompt_version="test",
    )


class Runner:
    def __init__(self):
        self.histories = []

    async def run(self, question, history=None):
        self.histories.append(history)
        return result()


@pytest.fixture
def client():
    runner = Runner()
    app = create_app(Settings(db_path=":memory:"), lambda question: runner)
    with TestClient(app) as client:
        client.runner = runner
        yield client


def plan(store):
    return store.create_plan(
        title="Charge",
        device="EV",
        start="2026-10-01T01:00:00+00:00",
        end="2026-10-01T05:00:00+00:00",
        expected_kg_co2=0.3,
        notes="Test",
    )


def test_ask_trace_sessions_health(client):
    assert client.get("/health").json()["model"] == "demo-rules-v1"
    for index in range(8):
        response = client.post("/ask", json={"question": f"Question {index}", "session_id": "s"})
        assert response.status_code == 200
    body = response.json()
    assert "trace" not in body
    trace = client.get(f"/runs/{body['run_id']}").json()
    assert trace["trace"][0]["name"] == "fake"
    assert trace["question"] == "Question 7"
    assert len(client.runner.histories[-1]) == 12
    assert client.runner.histories[-1][0]["content"] == "Question 1"
    assert client.app.state.store.history("other") == []
    assert client.app.state.store.history(None) == []
    assert client.get("/runs/unknown").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"question": ""},
        {"question": "  "},
        {"question": "x" * 1001},
        {"question": "ok", "session_id": "../bad"},
        {"question": "ok", "unexpected": True},
    ],
)
def test_bad_input(client, body):
    response = client.post("/ask", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_input"


def test_plan_lifecycle(client):
    first = plan(client.app.state.store)
    assert client.get("/plans").json()[0]["status"] == "pending"
    approved = client.post(f"/plans/{first['id']}/approve")
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_at"]
    assert client.post(f"/plans/{first['id']}/reject").status_code == 400
    assert client.post(f"/plans/{first['id']}/approve").status_code == 400
    second = plan(client.app.state.store)
    assert client.post(f"/plans/{second['id']}/reject").json()["status"] == "rejected"
    assert client.post("/plans/unknown/approve").status_code == 404
    assert client.post("/plans/unknown/reject").status_code == 404
    assert client.get("/unknown").json()["error"]


@pytest.mark.parametrize(
    "exception,status",
    [
        (TimeoutError("secret"), 504),
        (httpx.ReadTimeout("secret"), 504),
        (httpx.ConnectError("secret"), 502),
        (ValueError("secret"), 400),
        (RuntimeError("secret"), 502),
    ],
)
def test_safe_errors(exception, status):
    class Failing:
        async def run(self, *args, **kwargs):
            raise exception

    with TestClient(create_app(Settings(db_path=":memory:"), lambda _: Failing())) as client:
        response = client.post("/ask", json={"question": "hello"})
    assert response.status_code == status
    assert "secret" not in response.text


def test_persistence_and_validation(tmp_path):
    path = tmp_path / "nested" / "database.sqlite"
    db = Database(path)
    saved = result()
    db.save_run(saved, None, "question")
    saved_plan = plan(db)
    db.close()
    db = Database(path)
    assert db.get_run(saved.run_id)["answer"]["answer"] == saved.answer.answer
    assert db.list_plans()[0]["id"] == saved_plan["id"]
    for updates in [
        {"end": "2026-10-01T00:00:00Z"},
        {"expected_kg_co2": float("nan")},
        {"title": ""},
        {"start": "2026-10-01T01:00:00"},
    ]:
        arguments = dict(
            title="a",
            device="b",
            start="2026-10-01T01:00:00Z",
            end="2026-10-01T05:00:00Z",
            expected_kg_co2=0.1,
            notes="",
        )
        with pytest.raises(ValueError):
            db.create_plan(**(arguments | updates))
    db.close()
