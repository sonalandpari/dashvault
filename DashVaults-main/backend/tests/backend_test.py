"""Backend API tests for Unbiased AI Decision."""
import io
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://cecf3fd2-15f3-413a-9cfd-37090be97bee.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

UNIQUE_EMAIL = f"qa-{int(time.time())}@unbias.ai"
UNIQUE_PASS = "qatest123"

CSV_CONTENT = "gender,age_group,education,outcome\n" + "\n".join(
    [f"male,30-40,bachelor,hired" for _ in range(8)]
    + [f"male,30-40,bachelor,not_hired" for _ in range(2)]
    + [f"female,30-40,bachelor,hired" for _ in range(2)]
    + [f"female,30-40,bachelor,not_hired" for _ in range(8)]
)


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    return s


# Auth flow tests
def test_root():
    r = requests.get(f"{API}/")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_register_new_user(session):
    r = session.post(f"{API}/auth/register", json={"email": UNIQUE_EMAIL, "password": UNIQUE_PASS, "name": "QA Tester"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == UNIQUE_EMAIL
    assert "id" in data
    # cookies set
    assert "access_token" in session.cookies.get_dict()


def test_me_endpoint(session):
    r = session.get(f"{API}/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == UNIQUE_EMAIL


def test_register_duplicate(session):
    r = requests.post(f"{API}/auth/register", json={"email": UNIQUE_EMAIL, "password": UNIQUE_PASS})
    assert r.status_code == 400


def test_login_existing_tester():
    s = requests.Session()
    # Ensure tester exists; if not, create
    r = s.post(f"{API}/auth/login", json={"email": "tester@unbias.ai", "password": "test12345"})
    if r.status_code == 401:
        r2 = s.post(f"{API}/auth/register", json={"email": "tester@unbias.ai", "password": "test12345", "name": "Tester"})
        assert r2.status_code == 200
    else:
        assert r.status_code == 200


def test_login_invalid():
    r = requests.post(f"{API}/auth/login", json={"email": UNIQUE_EMAIL, "password": "wrongpass"})
    assert r.status_code == 401


def test_me_unauthenticated():
    r = requests.get(f"{API}/auth/me")
    assert r.status_code == 401


# File upload + analysis flow
@pytest.fixture(scope="module")
def auth_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": "admin@unbias.ai", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def uploaded_file(auth_session):
    files = {"file": ("hiring.csv", CSV_CONTENT.encode("utf-8"), "text/csv")}
    r = auth_session.post(f"{API}/files/upload", files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "id" in data
    assert "gender" in data["columns"]
    assert "outcome" in data["columns"]
    assert data["rows"] == 20
    return data


def test_upload_non_csv(auth_session):
    files = {"file": ("test.txt", b"hello", "text/plain")}
    r = auth_session.post(f"{API}/files/upload", files=files)
    assert r.status_code == 400


def test_upload_unauth():
    files = {"file": ("hiring.csv", CSV_CONTENT.encode("utf-8"), "text/csv")}
    r = requests.post(f"{API}/files/upload", files=files)
    assert r.status_code == 401


def test_list_files(auth_session, uploaded_file):
    r = auth_session.get(f"{API}/files")
    assert r.status_code == 200
    assert any(f["id"] == uploaded_file["id"] for f in r.json())


def test_analyze_high_severity(auth_session, uploaded_file):
    body = {
        "file_id": uploaded_file["id"],
        "protected_attribute": "gender",
        "outcome_column": "outcome",
        "favorable_outcome": "hired",
    }
    r = auth_session.post(f"{API}/analyses/analyze", json=body, timeout=120)
    assert r.status_code == 200, r.text
    data = r.json()
    m = data["metrics"]
    assert m["severity"] == "high"
    assert m["four_fifths_rule_passed"] is False
    # 80% male hired vs 20% female -> DPD ~0.6, DI ~0.25
    assert m["demographic_parity_difference"] > 0.5
    assert m["disparate_impact_ratio"] < 0.4
    assert "ai_explanation" in data and len(data["ai_explanation"]) > 20
    pytest.analysis_id = data["id"]


def test_get_analysis(auth_session):
    aid = getattr(pytest, "analysis_id", None)
    if not aid:
        pytest.skip("no analysis id")
    r = auth_session.get(f"{API}/analyses/{aid}")
    assert r.status_code == 200
    assert r.json()["id"] == aid


def test_list_analyses(auth_session):
    r = auth_session.get(f"{API}/analyses")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_report_plain_text(auth_session):
    aid = getattr(pytest, "analysis_id", None)
    if not aid:
        pytest.skip("no analysis id")
    r = auth_session.get(f"{API}/analyses/{aid}/report")
    assert r.status_code == 200
    assert "FAIRNESS AUDIT REPORT" in r.text
    assert "KEY METRICS" in r.text


def test_analyze_bad_column(auth_session, uploaded_file):
    body = {
        "file_id": uploaded_file["id"],
        "protected_attribute": "nonexistent",
        "outcome_column": "outcome",
        "favorable_outcome": "hired",
    }
    r = auth_session.post(f"{API}/analyses/analyze", json=body)
    assert r.status_code == 400


def test_logout(auth_session):
    r = auth_session.post(f"{API}/auth/logout")
    assert r.status_code == 200
