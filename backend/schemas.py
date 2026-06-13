from datetime import datetime
from typing import Literal, Optional, List
from pydantic import BaseModel


# ---------- Auth ----------
class RegisterRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: Literal["patient", "administration"]
    title: Optional[str] = ""
    email: Optional[str] = None
    # for role='patient', optional initial profile fields
    age: Optional[int] = 25
    lmp: Optional[str] = None
    village: Optional[str] = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    full_name: str
    role: str
    title: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class MeUpdate(BaseModel):
    full_name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    new_password: Optional[str] = None
    current_password: Optional[str] = None


# ---------- Patients ----------
class PatientCreate(BaseModel):
    name: str
    age: int
    lmp: str
    village: Optional[str] = ""
    client_id: Optional[str] = None  # for sync correlation


class PatientUpdate(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    lmp: Optional[str] = None
    village: Optional[str] = None
    client_updated_at: Optional[datetime] = None


class PatientOut(BaseModel):
    id: int
    name: str
    age: int
    lmp: str
    village: str
    sync_status: str
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    updated_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Risk prediction / examinations ----------
class VitalsIn(BaseModel):
    Age: float
    SystolicBP: float
    DiastolicBP: float
    BS: float
    BodyTemp: float
    HeartRate: float


class PredictResponse(BaseModel):
    label: str
    probs: dict
    factors: list


class ExamCreate(BaseModel):
    model_config = {"protected_namespaces": ()}

    patient_id: int
    vitals: VitalsIn
    model_used: Literal["server", "on-device"] = "server"
    # required when model_used == 'on-device' (computed client-side)
    risk_label: Optional[str] = None
    probs: Optional[dict] = None


class ExamOut(BaseModel):
    model_config = {"protected_namespaces": (), "from_attributes": True}

    id: int
    patient_id: int
    age: float
    systolic_bp: float
    diastolic_bp: float
    bs: float
    body_temp: float
    heart_rate: float
    risk_label: str
    prob_high: float
    prob_low: float
    prob_mid: float
    model_used: str
    sync_status: str
    created_at: datetime


# ---------- Sync ----------
class SyncItem(BaseModel):
    client_id: str
    type: Literal["patient_create", "patient_update", "examination_create"]
    payload: dict
    client_ts: datetime


class SyncResultItem(BaseModel):
    client_id: str
    status: Literal["synced", "conflict"]
    detail: str
    server_id: Optional[int] = None


class SyncResponse(BaseModel):
    results: List[SyncResultItem]


# ---------- Admin ----------
class AdminUserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    role: Literal["admin", "administration", "patient"]
    title: Optional[str] = ""
    email: Optional[str] = None


class AdminUserOut(UserOut):
    created_at: datetime
    patient_count: int = 0

    class Config:
        from_attributes = True


class LogOut(BaseModel):
    id: int
    username: Optional[str]
    role: Optional[str]
    action: str
    details: str
    created_at: datetime

    class Config:
        from_attributes = True


class SettingsOut(BaseModel):
    settings: dict


class SettingsUpdate(BaseModel):
    settings: dict
