# ASAF Full-Stack Web App

This is the working prototype for the ASAF (AI-enhanced Smart Antenatal Framework)
research project. It has two parts:

- **`backend/`** — a FastAPI + SQLite REST API: accounts, authentication (JWT),
  per-user patient records, AI risk prediction (the trained Random Forest from the
  notebook), offline-sync endpoint, and admin endpoints.
- **`frontend/index.html`** — a single-file React app (no build step) with
  Home, About, Login, Register, Profile, Settings, a field-app dashboard, and an
  Admin dashboard. It talks to the backend over the REST API.

Because real data lives in the backend's database (not the browser), the same
account works from any device that can reach the backend — that's what makes this
"cross-device sync" rather than the earlier single-file, localStorage demo.

---

## 1. Run the backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The first time it starts, it creates `asaf.db` (SQLite) and seeds these demo accounts:

| Username     | Password     | Email                | Role             | Notes                                |
|--------------|--------------|----------------------|------------------|---------------------------------------|
| `admin`      | `admin123`   | admin@asaf.local     | admin            | System administrator                   |
| `lhw1`       | `lhw123`     | lhw1@asaf.local       | administration   | Amina Yousaf, Lady Health Worker — owns 2 seeded patients (incl. Razia Bibi) |
| `mo1`        | `mo123`      | mo1@asaf.local        | administration   | Dr. Bilal Ahmed, Medical Officer — owns 1 seeded patient |
| `razia`      | `patient123` | razia@example.com    | patient          | Linked to the "Razia Bibi" patient record |

Visit `http://localhost:8000/docs` for interactive API docs (Swagger UI).

To wipe all data and re-seed, stop the server and delete `backend/asaf.db`.

> **Email addresses must be unique.** Every account has an email field, and patient
> accounts are required to provide one at registration. The backend rejects
> registration or profile updates that reuse an email already tied to another
> account (case-insensitive).

---

## 2. Run the frontend

The frontend is a single HTML file and doesn't need a build step, but it must be
served over `http://` (not opened directly as `file://`) so the browser allows it
to call the API. From the `frontend/` folder:

```bash
python -m http.server 5500
```

Then open `http://localhost:5500/asaf_app.html`. (In VS Code you can also use the
"Live Server" extension — right-click `asaf_app.html` \u2192 "Open with Live Server".)

### Pointing the frontend at the backend

By default the app calls the backend at `http://127.0.0.1:8000`. If your backend
runs somewhere else (e.g. you're demoing across two laptops on the same Wi-Fi, or
hosting the backend), set `window.ASAF_API_BASE` **before** the app's script runs.
Easiest way: open `asaf_app.html` in a text editor and add this line just above the
big `<script type="text/babel" ...>` tag:

```html
<script>window.ASAF_API_BASE = "http://192.168.1.42:8000";</script>
```

(replace with your backend machine's IP address and port). Any device on the same
network that opens the frontend with this setting will see the same accounts and
data, because they're all talking to the same backend database.

> For a real cross-device deployment beyond a local network (e.g. judges testing
> from their own laptops), the backend needs to run somewhere publicly reachable
> (a small cloud VM or a platform like Render/Railway/Fly.io) and `ASAF_API_BASE`
> updated to that public URL. The code itself doesn't need to change.

---

## 3. Pages & accounts

| Page | Path | Who can access it |
|---|---|---|
| Home | `#/home` | everyone |
| About | `#/about` | everyone — gap analysis & module mapping from the paper |
| Register | `#/register` | logged-out users — choose "Health worker" (Administration) or "Patient" |
| Login | `#/login` | logged-out users |
| Profile | `#/profile` | any logged-in user — edit name/title, change password |
| Settings | `#/settings` | any logged-in user — per-browser preferences (offline simulation, default risk model, SMS preview) |
| Dashboard | `#/app` | **administration** accounts get the field app (Patients / Risk check / Sync); **patient** accounts get the Companion view |
| Admin | `#/admin` | **admin** account only — manage all accounts, view all patient data, system settings & audit log |

### Roles, in one paragraph

- **Administration** accounts represent health workers (the paper's Lady Health
  Worker / Medical Officer / District Officer roles, unified into one role with a
  free-text "title"). Each administration account only sees and manages **its own**
  patients — this is the per-user data separation.
- **Patient** accounts are expectant mothers. Each has exactly one linked patient
  record and sees the Companion view (pregnancy timeline, health tips, reminders).
- **Admin** is a single, seeded oversight account. It can create/delete any account,
  reset passwords, see **every** patient record system-wide with its owning health
  worker, view system settings, and read the audit log of key actions (logins,
  registrations, patient/exam edits, syncs).

---

## 4. Demo flow for the offline-sync feature

On the Dashboard (administration account), the connectivity strip at the top of the
phone mockup can be toggled between **ONLINE** and **OFFLINE**:

- While **offline**, registering a new patient or saving a risk examination queues
  the record locally instead of calling the API, and risk checks fall back to the
  on-device decision tree model.
- The **Sync** tab shows the queue. "Sync now" sends queued items to
  `POST /api/sync`, which applies them to the database.
- "Simulate field conflict" demonstrates the last-write-wins rule from the paper's
  Algorithm 1: it immediately updates a patient's record on the server (as if
  another device already synced a change), then queues a *different* offline edit
  to the same record stamped 10 minutes earlier. Pressing "Sync now" shows the
  earlier edit being rejected in favour of the newer server copy.

---

## 5. Troubleshooting

**`ModuleNotFoundError: No module named 'numpy._core'` when starting the backend**

This happens if your Python environment has `numpy < 2.0` (common with Python 3.8
installs) while the bundled model file was saved with `numpy >= 2.0`. This is
already handled in `risk_model.py` with a small compatibility shim, so make sure
you're using the latest version of that file from this package. If you still see
the error, double-check `backend/risk_model.py` starts with the
"Compatibility shim" block near the top of the file.

**`ValueError: node array from the pickle has an incompatible dtype` (mentions `missing_go_to_left`)**

This means your installed scikit-learn is too old to read the model file's
decision-tree format. Fix it with:

```bash
pip install "scikit-learn==1.3.2"
```

scikit-learn 1.3.2 is the last release that supports Python 3.8 *and* understands
this newer tree format, so this single upgrade resolves it without needing to
change numpy or anything else. `requirements.txt` already pins this version for
new installs.

**Warnings about `model_used` / "protected namespace" or `InconsistentVersionWarning`**

These are harmless. The `model_used` warning is fixed in the latest `schemas.py`;
the scikit-learn version warning just means the model was trained with a different
scikit-learn version than you have installed — it still loads and predicts
correctly.

**Frontend can't reach the backend ("Failed to fetch")**

Make sure the backend is running and reachable, and that you opened
`asaf_app.html` over `http://` (e.g. via `python -m http.server`), not as a
`file://` path. If the backend is on a different host/port than
`http://127.0.0.1:8000`, set `window.ASAF_API_BASE` as described in section 2.

---

## 6. Notes for the write-up

- Password hashing uses PBKDF2-HMAC-SHA256 (100,000 iterations) rather than bcrypt,
  to avoid native build dependencies in this environment — functionally equivalent
  for demonstrating the security model described in the paper (Module 5).
- The Random Forest model file (`random_forest_model.joblib`) is the same one
  trained in `ASAF_Risk_Model_Training.ipynb` (accuracy 0.862, see Table V).
- SQLite is used for simplicity; the paper's target architecture (Section V-A)
  specifies PostgreSQL, which SQLAlchemy could swap to by changing `DATABASE_URL`
  in `backend/models.py` without touching the rest of the code.
