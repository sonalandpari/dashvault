from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import io
import uuid
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

import bcrypt
import jwt
import requests
import pandas as pd
import numpy as np
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, UploadFile, File, Form, Depends
from fastapi.responses import PlainTextResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
except ImportError:  # pragma: no cover - fallback for local environments without package access
    LlmChat = None
    UserMessage = None

# -------------- Setup --------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("unbias")

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_ALGORITHM = "HS256"
APP_NAME = "unbias-ai"
STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"

app = FastAPI(title="Unbiased AI Decision API")
api_router = APIRouter(prefix="/api")
db_available = True


def ensure_db_available() -> None:
    if not db_available:
        raise HTTPException(status_code=503, detail="Database unavailable. Please try again later.")

# -------------- Storage --------------
storage_key: Optional[str] = None

def init_storage() -> Optional[str]:
    global storage_key
    if storage_key:
        return storage_key
    try:
        resp = requests.post(
            f"{STORAGE_URL}/init",
            json={"emergent_key": os.environ.get("EMERGENT_LLM_KEY")},
            timeout=30,
        )
        resp.raise_for_status()
        storage_key = resp.json()["storage_key"]
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
        storage_key = None
    return storage_key

def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    if not key:
        raise HTTPException(status_code=500, detail="Storage unavailable")
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=120,
    )
    if resp.status_code == 403:
        # refresh key and retry once
        global storage_key
        storage_key = None
        key = init_storage()
        resp = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data, timeout=120,
        )
    resp.raise_for_status()
    return resp.json()

def get_object(path: str) -> bytes:
    key = init_storage()
    resp = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key}, timeout=60,
    )
    resp.raise_for_status()
    return resp.content

# -------------- Auth helpers --------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]

def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "type": "access",
               "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    payload = {"sub": user_id, "type": "refresh",
               "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=True,
                        samesite="none", max_age=12*3600, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True,
                        samesite="none", max_age=7*24*3600, path="/")

async def get_current_user(request: Request) -> dict:
    ensure_db_available()
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# -------------- Models --------------
class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: Optional[str] = None

class LoginBody(BaseModel):
    email: EmailStr
    password: str

class AnalyzeBody(BaseModel):
    file_id: str
    protected_attribute: str
    outcome_column: str
    favorable_outcome: str  # value considered favorable (e.g., "1", "approved")

class UserOut(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    role: str = "user"

# -------------- Auth Endpoints --------------
@api_router.post("/auth/register", response_model=UserOut)
async def register(body: RegisterBody, response: Response):
    ensure_db_available()
    email = body.email.lower()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "email": email,
        "name": body.name or email.split("@")[0],
        "password_hash": hash_password(body.password),
        "role": "user",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user_doc)
    set_auth_cookies(response, create_access_token(user_id, email), create_refresh_token(user_id))
    return UserOut(id=user_id, email=email, name=user_doc["name"], role="user")

@api_router.post("/auth/login", response_model=UserOut)
async def login(body: LoginBody, response: Response):
    ensure_db_available()
    email = body.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    set_auth_cookies(response, create_access_token(user["id"], email), create_refresh_token(user["id"]))
    return UserOut(id=user["id"], email=user["email"], name=user.get("name"), role=user.get("role", "user"))

@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}

@api_router.get("/auth/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return UserOut(id=user["id"], email=user["email"], name=user.get("name"), role=user.get("role", "user"))

# -------------- File Upload --------------
@api_router.post("/files/upload")
async def upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
    ensure_db_available()
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")
    # Validate parseable
    try:
        df = pd.read_csv(io.BytesIO(data))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {e}")

    file_id = str(uuid.uuid4())
    path = f"{APP_NAME}/uploads/{user['id']}/{file_id}.csv"
    try:
        put_object(path, data, "text/csv")
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail="Storage upload failed")

    columns = list(df.columns)
    preview = df.head(5).fillna("").astype(str).to_dict(orient="records")
    col_info = []
    for c in columns:
        unique_vals = df[c].dropna().unique().tolist()[:20]
        col_info.append({
            "name": c,
            "unique_count": int(df[c].nunique(dropna=True)),
            "sample_values": [str(v) for v in unique_vals],
            "dtype": str(df[c].dtype),
        })

    doc = {
        "id": file_id,
        "user_id": user["id"],
        "original_filename": file.filename,
        "storage_path": path,
        "size": len(data),
        "rows": int(len(df)),
        "columns": columns,
        "column_info": col_info,
        "preview": preview,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.files.insert_one(doc)
    doc.pop("_id", None)
    return doc

# -------------- Bias Metrics --------------
def _normalize_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip()

def compute_fairness(df: pd.DataFrame, protected: str, outcome: str, favorable: str) -> Dict[str, Any]:
    if protected not in df.columns or outcome not in df.columns:
        raise HTTPException(status_code=400, detail="Column not found in dataset")

    df = df[[protected, outcome]].dropna().copy()
    df[protected] = _normalize_series(df[protected])
    df[outcome] = _normalize_series(df[outcome])
    favorable = str(favorable).strip()
    df["__fav__"] = (df[outcome] == favorable).astype(int)

    groups = []
    for group_value, g in df.groupby(protected):
        n = int(len(g))
        fav = int(g["__fav__"].sum())
        rate = float(fav / n) if n else 0.0
        groups.append({"group": str(group_value), "size": n, "favorable": fav, "rate": rate})

    if not groups:
        raise HTTPException(status_code=400, detail="No data after filtering")

    groups.sort(key=lambda x: x["rate"], reverse=True)
    rates = [g["rate"] for g in groups]
    max_rate = max(rates)
    min_rate = min(rates)
    privileged = groups[0]["group"]
    unprivileged = groups[-1]["group"]

    dpd = max_rate - min_rate  # demographic parity difference
    di = (min_rate / max_rate) if max_rate > 0 else 0.0  # disparate impact ratio
    overall_rate = float(df["__fav__"].mean())

    # Severity using 80% rule
    if di >= 0.9 and dpd < 0.05:
        severity = "low"
    elif di >= 0.8 and dpd < 0.1:
        severity = "medium"
    else:
        severity = "high"

    return {
        "protected_attribute": protected,
        "outcome_column": outcome,
        "favorable_outcome": favorable,
        "groups": groups,
        "overall_favorable_rate": overall_rate,
        "privileged_group": privileged,
        "unprivileged_group": unprivileged,
        "demographic_parity_difference": dpd,
        "disparate_impact_ratio": di,
        "statistical_parity_difference": groups[0]["rate"] - groups[-1]["rate"],
        "four_fifths_rule_passed": di >= 0.8,
        "severity": severity,
        "total_rows": int(len(df)),
    }

# -------------- Gemini Explanation --------------
async def gemini_explain(metrics: Dict[str, Any], dataset_name: str) -> Dict[str, str]:
    if LlmChat is None or UserMessage is None:
        return {
            "text": (
                "AI explanation unavailable (emergentintegrations package not installed). "
                "Metrics computed successfully."
            )
        }
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY")
    system = (
        "You are an AI fairness auditor. You explain statistical bias findings in plain English "
        "for non-technical stakeholders, then give concrete mitigation steps. "
        "Return strictly in this format:\n\n"
        "## Summary\n<2-3 sentence plain-language summary>\n\n"
        "## What the Metrics Mean\n<bullet list>\n\n"
        "## Risk Assessment\n<paragraph describing real-world impact>\n\n"
        "## Mitigation Recommendations\n<numbered list of 4-6 concrete actions>"
    )
    chat = LlmChat(
        api_key=api_key,
        session_id=f"bias-{uuid.uuid4()}",
        system_message=system,
    ).with_model("gemini", "gemini-3-flash-preview")

    prompt = (
        f"Dataset: {dataset_name}\n"
        f"Protected attribute: {metrics['protected_attribute']}\n"
        f"Outcome column: {metrics['outcome_column']} (favorable = {metrics['favorable_outcome']})\n"
        f"Overall favorable rate: {metrics['overall_favorable_rate']:.2%}\n"
        f"Groups: {metrics['groups']}\n"
        f"Privileged group: {metrics['privileged_group']} | Unprivileged: {metrics['unprivileged_group']}\n"
        f"Demographic parity difference: {metrics['demographic_parity_difference']:.4f}\n"
        f"Disparate impact ratio: {metrics['disparate_impact_ratio']:.4f}\n"
        f"Statistical parity difference: {metrics['statistical_parity_difference']:.4f}\n"
        f"Four-fifths rule passed: {metrics['four_fifths_rule_passed']}\n"
        f"Severity: {metrics['severity']}\n\n"
        "Explain these findings and provide mitigation recommendations."
    )
    try:
        text = await chat.send_message(UserMessage(text=prompt))
        return {"text": text if isinstance(text, str) else str(text)}
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        return {"text": f"AI explanation unavailable ({e}). Metrics computed successfully."}

# -------------- Analysis Endpoints --------------
@api_router.post("/analyses/analyze")
async def analyze(body: AnalyzeBody, user=Depends(get_current_user)):
    ensure_db_available()
    file_doc = await db.files.find_one({"id": body.file_id, "user_id": user["id"]}, {"_id": 0})
    if not file_doc:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        data = get_object(file_doc["storage_path"])
        df = pd.read_csv(io.BytesIO(data))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load file: {e}")

    metrics = compute_fairness(df, body.protected_attribute, body.outcome_column, body.favorable_outcome)
    ai = await gemini_explain(metrics, file_doc["original_filename"])

    analysis_id = str(uuid.uuid4())
    doc = {
        "id": analysis_id,
        "user_id": user["id"],
        "file_id": body.file_id,
        "file_name": file_doc["original_filename"],
        "metrics": metrics,
        "ai_explanation": ai["text"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.analyses.insert_one(doc)
    doc.pop("_id", None)
    return doc

@api_router.get("/analyses")
async def list_analyses(user=Depends(get_current_user)):
    ensure_db_available()
    cursor = db.analyses.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(200)
    return items

@api_router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: str, user=Depends(get_current_user)):
    ensure_db_available()
    doc = await db.analyses.find_one({"id": analysis_id, "user_id": user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc

@api_router.get("/analyses/{analysis_id}/report", response_class=PlainTextResponse)
async def report(analysis_id: str, user=Depends(get_current_user)):
    ensure_db_available()
    doc = await db.analyses.find_one({"id": analysis_id, "user_id": user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    m = doc["metrics"]
    lines = [
        "UNBIASED AI DECISION — FAIRNESS AUDIT REPORT",
        "=" * 60,
        f"Dataset: {doc['file_name']}",
        f"Generated: {doc['created_at']}",
        f"Protected Attribute: {m['protected_attribute']}",
        f"Outcome Column: {m['outcome_column']} (favorable = {m['favorable_outcome']})",
        "",
        "KEY METRICS",
        "-" * 60,
        f"Overall Favorable Rate:           {m['overall_favorable_rate']:.4f}",
        f"Demographic Parity Difference:    {m['demographic_parity_difference']:.4f}",
        f"Disparate Impact Ratio:           {m['disparate_impact_ratio']:.4f}",
        f"Statistical Parity Difference:    {m['statistical_parity_difference']:.4f}",
        f"Four-Fifths Rule:                 {'PASS' if m['four_fifths_rule_passed'] else 'FAIL'}",
        f"Severity:                         {m['severity'].upper()}",
        "",
        "GROUP BREAKDOWN",
        "-" * 60,
    ]
    for g in m["groups"]:
        lines.append(f"  {g['group']:<20} n={g['size']:<6} favorable={g['favorable']:<6} rate={g['rate']:.4f}")
    lines.extend(["", "AI EXPLANATION & MITIGATION", "-" * 60, doc["ai_explanation"]])
    return "\n".join(lines)

@api_router.get("/files")
async def list_files(user=Depends(get_current_user)):
    ensure_db_available()
    cursor = db.files.find({"user_id": user["id"]}, {"_id": 0, "preview": 0}).sort("created_at", -1)
    return await cursor.to_list(200)

@api_router.get("/files/{file_id}")
async def get_file(file_id: str, user=Depends(get_current_user)):
    ensure_db_available()
    doc = await db.files.find_one({"id": file_id, "user_id": user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc

@api_router.get("/")
async def root():
    return {"service": "Unbiased AI Decision API", "status": "ok"}

# -------------- App wire-up --------------
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000")],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    global db_available
    try:
        await db.users.create_index("email", unique=True)
        await db.users.create_index("id", unique=True)
        await db.files.create_index("id", unique=True)
        await db.files.create_index("user_id")
        await db.analyses.create_index("id", unique=True)
        await db.analyses.create_index("user_id")
        # seed admin
        admin_email = os.environ.get("ADMIN_EMAIL", "admin@unbias.ai").lower()
        admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
        existing = await db.users.find_one({"email": admin_email})
        if not existing:
            await db.users.insert_one({
                "id": str(uuid.uuid4()),
                "email": admin_email,
                "name": "Admin",
                "password_hash": hash_password(admin_password),
                "role": "admin",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info("Admin seeded")
        elif not verify_password(admin_password, existing["password_hash"]):
            await db.users.update_one({"email": admin_email},
                                      {"$set": {"password_hash": hash_password(admin_password)}})
        db_available = True
    except Exception as e:
        db_available = False
        logger.error(f"Database startup failed: {e}")
    init_storage()

@app.on_event("shutdown")
async def shutdown():
    client.close()
