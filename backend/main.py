"""
ASAF backend - FastAPI application.

Run with:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Provides:
- Registration / login (JWT) for 'administration' and 'patient' roles, plus a
  seeded 'admin' account (Module 5: Security & Privacy Layer)
- Per-user patient records (Module 1) - each 'administration' user only sees
  and manages their own patients; 'admin' sees everything
- Server-side AI risk prediction using the trained Random Forest (Module 3)
- Offline-sync endpoint implementing Algorithm 1 / last-write-wins (Module 2)
- Admin endpoints: manage accounts, view all data, system settings & audit log
"""

from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

import models
import schemas
import risk_model
from models import User, Patient, Examination, AuditLog, Setting, init_db, get_db
from auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_role,
)

app = FastAPI(title="ASAF API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------
# Startup: create tables + seed demo data
# ---------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    init_db()
    db = next(get_db())
    try:
        seed_data(db)
    finally:
        db.close()


def log_action(db: Session, user: Optional[User], action: str, details: str = ""):
    entry = AuditLog(
        username=user.username if user else None,
        role=user.role if user else None,
        action=action,
        details=details,
    )
    db.add(entry)
    db.commit()


def normalize_email(email: Optional[str]) -> Optional[str]:
    if email is None:
        return None
    email = email.strip().lower()
    return email or None


def assert_email_available(db: Session, email: Optional[str], exclude_user_id: Optional[int] = None):
    if not email:
        return
    q = db.query(User).filter(User.email == email)
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    if q.first():
        raise HTTPException(status_code=400, detail="This email is already registered to another account")


def seed_data(db: Session):
    if db.query(User).count() > 0:
        return

    admin = User(username="admin", password_hash=hash_password("admin123"), email="admin@asaf.local",
                  full_name="System Administrator", role="admin", title="Administrator")
    lhw = User(username="lhw1", password_hash=hash_password("lhw123"), email="lhw1@asaf.local",
               full_name="Amina Yousaf", role="administration", title="Lady Health Worker")
    mo = User(username="mo1", password_hash=hash_password("mo123"), email="mo1@asaf.local",
              full_name="Dr. Bilal Ahmed", role="administration", title="Medical Officer")
    razia = User(username="razia", password_hash=hash_password("patient123"), email="razia@example.com",
                  full_name="Razia Bibi", role="patient", title="Patient")
    db.add_all([admin, lhw, mo, razia])
    db.commit()

    razia_record = Patient(owner_id=lhw.id, linked_user_id=razia.id, name="Razia Bibi",
                            age=27, lmp="2026-01-10", village="Chah Sultan", sync_status="synced")
    shabana = Patient(owner_id=lhw.id, name="Shabana Kausar", age=34, lmp="2025-10-02",
                       village="Mauza Kot", sync_status="synced")
    nazia = Patient(owner_id=mo.id, name="Nazia Parveen", age=19, lmp="2026-04-18",
                     village="Basti Niazi", sync_status="synced")
    db.add_all([razia_record, shabana, nazia])

    db.add_all([
        Setting(key="model_version", value="random_forest_v1 (acc=0.862)"),
        Setting(key="maintenance_mode", value="false"),
        Setting(key="announcement", value="Welcome to the ASAF pilot deployment."),
    ])
    db.commit()
    log_action(db, None, "system_seeded", "Initial demo accounts and patients created")


# =================================================================
# Auth
# =================================================================
@app.post("/api/register", response_model=schemas.TokenResponse)
def register(body: schemas.RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    email = normalize_email(body.email)
    if body.role == "patient" and not email:
        raise HTTPException(status_code=400, detail="Email is required for patient accounts")
    assert_email_available(db, email)

    title = body.title or ("Patient" if body.role == "patient" else "Lady Health Worker")
    user = User(username=body.username, password_hash=hash_password(body.password), email=email,
                full_name=body.full_name, role=body.role, title=title)
    db.add(user)
    db.commit()
    db.refresh(user)

    if body.role == "patient":
        record = Patient(
            owner_id=None, linked_user_id=user.id, name=body.full_name,
            age=body.age or 25, lmp=body.lmp or datetime.utcnow().date().isoformat(),
            village=body.village or "", sync_status="synced",
        )
        db.add(record)
        db.commit()

    log_action(db, user, "register", f"role={body.role}")
    token = create_access_token(user)
    return schemas.TokenResponse(access_token=token, user=user)


@app.post("/api/login", response_model=schemas.TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.password_hash):
        log_action(db, None, "login_failed", f"username={form.username}")
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    log_action(db, user, "login")
    token = create_access_token(user)
    return schemas.TokenResponse(access_token=token, user=user)


@app.get("/api/me", response_model=schemas.UserOut)
def read_me(user: User = Depends(get_current_user)):
    return user


@app.patch("/api/me", response_model=schemas.UserOut)
def update_me(body: schemas.MeUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.full_name:
        user.full_name = body.full_name
    if body.title is not None:
        user.title = body.title
    if body.email is not None:
        email = normalize_email(body.email)
        if user.role == "patient" and not email:
            raise HTTPException(status_code=400, detail="Email is required for patient accounts")
        assert_email_available(db, email, exclude_user_id=user.id)
        user.email = email
    if body.new_password:
        if not body.current_password or not verify_password(body.current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        user.password_hash = hash_password(body.new_password)
    db.commit()
    log_action(db, user, "profile_update")
    return user


# =================================================================
# Patients (administration / admin)
# =================================================================
def patient_to_out(p: Patient) -> schemas.PatientOut:
    return schemas.PatientOut(
        id=p.id, name=p.name, age=p.age, lmp=p.lmp, village=p.village,
        sync_status=p.sync_status, owner_id=p.owner_id,
        owner_name=p.owner.full_name if p.owner else None,
        updated_at=p.updated_at, created_at=p.created_at,
    )


@app.get("/api/patients", response_model=List[schemas.PatientOut])
def list_patients(user: User = Depends(require_role("administration", "admin")), db: Session = Depends(get_db)):
    q = db.query(Patient)
    if user.role != "admin":
        q = q.filter(Patient.owner_id == user.id)
    return [patient_to_out(p) for p in q.order_by(Patient.id).all()]


@app.post("/api/patients", response_model=schemas.PatientOut)
def create_patient(body: schemas.PatientCreate, user: User = Depends(require_role("administration", "admin")), db: Session = Depends(get_db)):
    p = Patient(owner_id=user.id, name=body.name, age=body.age, lmp=body.lmp,
                 village=body.village or "", sync_status="synced")
    db.add(p)
    db.commit()
    db.refresh(p)
    log_action(db, user, "patient_create", f"patient_id={p.id} name={p.name}")
    return patient_to_out(p)


def _get_owned_patient(db, patient_id, user):
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    if user.role != "admin" and p.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this patient")
    return p


@app.patch("/api/patients/{patient_id}", response_model=schemas.PatientOut)
def update_patient(patient_id: int, body: schemas.PatientUpdate, user: User = Depends(require_role("administration", "admin")), db: Session = Depends(get_db)):
    p = _get_owned_patient(db, patient_id, user)
    for field in ("name", "age", "lmp", "village"):
        val = getattr(body, field)
        if val is not None:
            setattr(p, field, val)
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    log_action(db, user, "patient_update", f"patient_id={p.id}")
    return patient_to_out(p)


@app.delete("/api/patients/{patient_id}")
def delete_patient(patient_id: int, user: User = Depends(require_role("administration", "admin")), db: Session = Depends(get_db)):
    p = _get_owned_patient(db, patient_id, user)
    db.delete(p)
    db.commit()
    log_action(db, user, "patient_delete", f"patient_id={patient_id}")
    return {"ok": True}


@app.get("/api/patients/{patient_id}/examinations", response_model=List[schemas.ExamOut])
def patient_examinations(patient_id: int, user: User = Depends(require_role("administration", "admin")), db: Session = Depends(get_db)):
    p = _get_owned_patient(db, patient_id, user)
    return p.examinations


# ---------- Patient (self) ----------
def _get_own_record(db, user) -> Patient:
    p = db.query(Patient).filter(Patient.linked_user_id == user.id).first()
    if not p:
        raise HTTPException(status_code=404, detail="No patient record linked to this account")
    return p


@app.get("/api/patients/me", response_model=schemas.PatientOut)
def my_patient_record(user: User = Depends(require_role("patient")), db: Session = Depends(get_db)):
    return patient_to_out(_get_own_record(db, user))


@app.patch("/api/patients/me", response_model=schemas.PatientOut)
def update_my_patient_record(body: schemas.PatientUpdate, user: User = Depends(require_role("patient")), db: Session = Depends(get_db)):
    p = _get_own_record(db, user)
    for field in ("name", "age", "lmp", "village"):
        val = getattr(body, field)
        if val is not None:
            setattr(p, field, val)
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    log_action(db, user, "self_profile_update")
    return patient_to_out(p)


@app.get("/api/patients/me/examinations", response_model=List[schemas.ExamOut])
def my_examinations(user: User = Depends(require_role("patient")), db: Session = Depends(get_db)):
    p = _get_own_record(db, user)
    return p.examinations


# =================================================================
# Risk prediction & examinations (Module 3)
# =================================================================
@app.post("/api/predict", response_model=schemas.PredictResponse)
def predict(vitals: schemas.VitalsIn, user: User = Depends(require_role("administration", "admin")), db: Session = Depends(get_db)):
    result = risk_model.predict_risk(vitals.dict())
    log_action(db, user, "risk_predict", f"label={result['label']}")
    return result


@app.post("/api/examinations", response_model=schemas.ExamOut)
def create_examination(body: schemas.ExamCreate, user: User = Depends(require_role("administration", "admin")), db: Session = Depends(get_db)):
    p = _get_owned_patient(db, body.patient_id, user)
    v = body.vitals

    if body.model_used == "server":
        result = risk_model.predict_risk(v.dict())
        risk_label = result["label"]
        probs = result["probs"]
    else:
        if not body.risk_label or not body.probs:
            raise HTTPException(status_code=400, detail="risk_label and probs are required for on-device results")
        risk_label = body.risk_label
        probs = body.probs

    exam = Examination(
        patient_id=p.id, age=v.Age, systolic_bp=v.SystolicBP, diastolic_bp=v.DiastolicBP,
        bs=v.BS, body_temp=v.BodyTemp, heart_rate=v.HeartRate,
        risk_label=risk_label,
        prob_high=probs.get("high risk", 0.0), prob_low=probs.get("low risk", 0.0), prob_mid=probs.get("mid risk", 0.0),
        model_used=body.model_used, sync_status="synced",
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    log_action(db, user, "examination_create", f"patient_id={p.id} label={risk_label} model={body.model_used}")
    return exam


# =================================================================
# Offline sync (Module 2 / Algorithm 1)
# =================================================================
@app.post("/api/sync", response_model=schemas.SyncResponse)
def sync(items: List[schemas.SyncItem], user: User = Depends(require_role("administration", "admin")), db: Session = Depends(get_db)):
    results = []
    for item in items:
        try:
            if item.type == "patient_create":
                payload = item.payload
                p = Patient(owner_id=user.id, name=payload["name"], age=payload["age"],
                             lmp=payload["lmp"], village=payload.get("village", ""), sync_status="synced")
                db.add(p)
                db.commit()
                db.refresh(p)
                results.append(schemas.SyncResultItem(client_id=item.client_id, status="synced",
                                                        detail=f"Created patient #{p.id} ({p.name})", server_id=p.id))

            elif item.type == "patient_update":
                payload = item.payload
                patient_id = payload["patient_id"]
                p = _get_owned_patient(db, patient_id, user)
                if p.updated_at and item.client_ts <= p.updated_at:
                    results.append(schemas.SyncResultItem(client_id=item.client_id, status="conflict",
                                                            detail=f"Server copy of patient #{p.id} is newer (last-write-wins); edit discarded",
                                                            server_id=p.id))
                else:
                    for field in ("name", "age", "lmp", "village"):
                        if field in payload and payload[field] is not None:
                            setattr(p, field, payload[field])
                    p.updated_at = item.client_ts
                    db.commit()
                    results.append(schemas.SyncResultItem(client_id=item.client_id, status="synced",
                                                            detail=f"Updated patient #{p.id} ({p.name})", server_id=p.id))

            elif item.type == "examination_create":
                payload = item.payload
                p = _get_owned_patient(db, payload["patient_id"], user)
                probs = payload.get("probs", {})
                exam = Examination(
                    patient_id=p.id, age=payload["vitals"]["Age"], systolic_bp=payload["vitals"]["SystolicBP"],
                    diastolic_bp=payload["vitals"]["DiastolicBP"], bs=payload["vitals"]["BS"],
                    body_temp=payload["vitals"]["BodyTemp"], heart_rate=payload["vitals"]["HeartRate"],
                    risk_label=payload["risk_label"], prob_high=probs.get("high risk", 0.0),
                    prob_low=probs.get("low risk", 0.0), prob_mid=probs.get("mid risk", 0.0),
                    model_used=payload.get("model_used", "on-device"), sync_status="synced",
                )
                db.add(exam)
                db.commit()
                db.refresh(exam)
                results.append(schemas.SyncResultItem(client_id=item.client_id, status="synced",
                                                        detail=f"Saved examination #{exam.id} for patient #{p.id} ({exam.risk_label})", server_id=exam.id))
            else:
                results.append(schemas.SyncResultItem(client_id=item.client_id, status="conflict", detail="Unknown item type"))
        except HTTPException as e:
            results.append(schemas.SyncResultItem(client_id=item.client_id, status="conflict", detail=str(e.detail)))

    log_action(db, user, "sync", f"{len(items)} item(s) processed")
    return schemas.SyncResponse(results=results)


# =================================================================
# Admin
# =================================================================
@app.get("/api/admin/users", response_model=List[schemas.AdminUserOut])
def admin_list_users(user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id).all()
    out = []
    for u in users:
        count = db.query(Patient).filter(Patient.owner_id == u.id).count()
        out.append(schemas.AdminUserOut(
            id=u.id, username=u.username, email=u.email, full_name=u.full_name, role=u.role,
            title=u.title, created_at=u.created_at, patient_count=count,
        ))
    return out


@app.post("/api/admin/users", response_model=schemas.AdminUserOut)
def admin_create_user(body: schemas.AdminUserCreate, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    email = normalize_email(body.email)
    if body.role == "patient" and not email:
        raise HTTPException(status_code=400, detail="Email is required for patient accounts")
    assert_email_available(db, email)
    new_user = User(username=body.username, password_hash=hash_password(body.password), email=email,
                     full_name=body.full_name, role=body.role, title=body.title or "")
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    log_action(db, user, "admin_create_user", f"created username={new_user.username} role={new_user.role}")
    return schemas.AdminUserOut(id=new_user.id, username=new_user.username, email=new_user.email, full_name=new_user.full_name,
                                  role=new_user.role, title=new_user.title, created_at=new_user.created_at, patient_count=0)


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(target)
    db.commit()
    log_action(db, user, "admin_delete_user", f"deleted username={target.username}")
    return {"ok": True}


@app.post("/api/admin/users/{user_id}/reset_password")
def admin_reset_password(user_id: int, body: dict, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    new_password = body.get("new_password")
    if not new_password:
        raise HTTPException(status_code=400, detail="new_password is required")
    target.password_hash = hash_password(new_password)
    db.commit()
    log_action(db, user, "admin_reset_password", f"username={target.username}")
    return {"ok": True}


@app.get("/api/admin/data")
def admin_all_data(user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    patients = db.query(Patient).order_by(Patient.id).all()
    return {
        "patients": [patient_to_out(p) for p in patients],
        "examination_count": db.query(Examination).count(),
        "user_count": db.query(User).count(),
        "patient_count": len(patients),
    }


@app.get("/api/admin/logs", response_model=List[schemas.LogOut])
def admin_logs(limit: int = 100, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    logs = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return logs


@app.get("/api/admin/settings", response_model=schemas.SettingsOut)
def admin_get_settings(user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    settings = {s.key: s.value for s in db.query(Setting).all()}
    return schemas.SettingsOut(settings=settings)


@app.put("/api/admin/settings", response_model=schemas.SettingsOut)
def admin_update_settings(body: schemas.SettingsUpdate, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    for key, value in body.settings.items():
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = str(value)
        else:
            db.add(Setting(key=key, value=str(value)))
    db.commit()
    log_action(db, user, "admin_update_settings", str(body.settings))
    settings = {s.key: s.value for s in db.query(Setting).all()}
    return schemas.SettingsOut(settings=settings)


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}
