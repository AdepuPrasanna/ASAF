"""
ASAF backend - database models (SQLAlchemy)

Tables:
- users        : login accounts. role in {'admin', 'administration', 'patient'}
- patients      : clinical records managed by an 'administration' user (Module 1)
- examinations  : risk-assessment records linked to a patient (Module 3)
- audit_logs    : system activity log, visible to admins (Module 5 / oversight)
- settings      : simple key-value system settings (admin-editable)
"""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DATABASE_URL = "sqlite:///./asaf.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'admin' | 'administration' | 'patient'
    title = Column(String, default="")     # e.g. "Lady Health Worker", "Medical Officer"
    created_at = Column(DateTime, default=datetime.utcnow)

    patients = relationship("Patient", back_populates="owner", foreign_keys="Patient.owner_id")
    own_patient_record = relationship("Patient", back_populates="linked_user", foreign_keys="Patient.linked_user_id", uselist=False)


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)       # administration user managing this record
    linked_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # patient's own login, if any
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    lmp = Column(String, nullable=False)   # ISO date string
    village = Column(String, default="")
    sync_status = Column(String, default="synced")  # 'synced' | 'pending' | 'conflict'
    updated_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="patients", foreign_keys=[owner_id])
    linked_user = relationship("User", back_populates="own_patient_record", foreign_keys=[linked_user_id])
    examinations = relationship("Examination", back_populates="patient", cascade="all, delete-orphan")


class Examination(Base):
    __tablename__ = "examinations"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    age = Column(Float)
    systolic_bp = Column(Float)
    diastolic_bp = Column(Float)
    bs = Column(Float)
    body_temp = Column(Float)
    heart_rate = Column(Float)
    risk_label = Column(String)
    prob_high = Column(Float)
    prob_low = Column(Float)
    prob_mid = Column(Float)
    model_used = Column(String, default="server")  # 'server' (Random Forest) | 'on-device' (Decision Tree)
    sync_status = Column(String, default="synced")
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="examinations")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String)
    role = Column(String)
    action = Column(String, nullable=False)
    details = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
