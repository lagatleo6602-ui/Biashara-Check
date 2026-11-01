import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"  # tests never touch your MySQL data

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402

# Tests never touch the real trained model: they use their own temporary model folder.
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import ml.train as _mltrain  # noqa: E402

_mltrain.ARTIFACTS = Path(tempfile.mkdtemp(prefix="sme-model-"))
_mltrain.MODEL_FILE = _mltrain.ARTIFACTS / "model.joblib"
_mltrain.META_FILE = _mltrain.ARTIFACTS / "model_meta.json"

# Tests never send real email, SMS or M-Pesa requests, even if your .env has live settings.
for _k in ("SMTP_HOST", "TEXTBEE_API_KEY", "AT_USERNAME", "AT_API_KEY", "MPESA_CONSUMER_KEY",
           "MPESA_CONSUMER_SECRET", "MPESA_CALLBACK_URL", "MPESA_ENV"):
    os.environ.pop(_k, None)

SAMPLE = "data/samples/sample_SME-001.csv"
RECORD = {"month": "2026-01-15", "revenue": 120000, "cogs": 70000, "operating_expenses": 60000,
          "cash_inflows": 118000, "cash_outflows": 125000, "transaction_count": 640}


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.add(User(username="admin", password_hash=hash_password("admin-pass-123"), role="admin", is_super_admin=True))
        db.commit()


def teardown_module():
    engine.dispose()
    if os.path.exists("test.db"):
        os.remove("test.db")


_phone_n = [700000000]


def contact(code):
    """Unique email + valid Kenyan phone for each test account."""
    _phone_n[0] += 1
    return {"email": f"{code.lower()}@test.ke", "phone": f"0{_phone_n[0]}", "contact_consent": True}


def new_client():
    return TestClient(app)


@pytest.fixture
def admin():
    c = new_client()
    assert c.post("/auth/login", json={"username": "admin", "password": "admin-pass-123"}).status_code == 200
    return c


def signup(c, payload, path="/auth/register"):
    """Sign-up is two steps: the form emails a code, the code creates the account."""
    import re as _re
    from app import mailer as _mailer
    r = c.post(path, json=payload)
    if r.status_code != 202:
        return r
    email = payload["email"].strip().lower()
    body = [m for m in _mailer.OUTBOX if m["to"] == email][-1]["body"]
    return c.post("/auth/register/confirm", json={"email": email, "code": _re.search(r"\b(\d{6})\b", body).group(1)})


def owner(code, sector="retail", password="owner-pass-1"):
    c = new_client()
    r = signup(c, {"code": code, "sector": sector, "password": password, "consent": True, **contact(code)})
    assert r.status_code == 201, r.text
    return c


# ---------- system & pages ----------
def test_health_and_pages_public():
    c = new_client()
    assert c.get("/health").json()["status"] == "ok"
    for page in ("/", "/login", "/admin", "/how", "/install", "/static/install.js", "/static/vendor/qrcode.js", "/static/app.js", "/static/login.js", "/static/admin.js", "/static/how.js"):
        assert c.get(page).status_code == 200, page


def test_api_needs_login():
    c = new_client()
    assert c.get("/businesses").status_code == 401
    assert c.get("/auth/me").status_code == 401
    assert c.get("/admin/overview").status_code == 401


# ---------- login / logout / register ----------
def test_register_login_logout():
    c = owner("sme-001")
    me = c.get("/auth/me").json()
    assert {k: me[k] for k in ("username", "role", "business", "must_change_password")} == \
        {"username": "sme-001", "role": "owner", "business": "SME-001", "must_change_password": False}
    assert me["contact"] == {"email": "sm•••••@test.ke", "phone": "+2547•••••001", "email_verified": True, "phone_verified": False}

    assert c.post("/auth/logout").status_code == 200
    assert c.get("/auth/me").status_code == 401  # session really ended

    bad = c.post("/auth/login", json={"username": "SME-001", "password": "wrong"})
    assert bad.status_code == 401
    ok = c.post("/auth/login", json={"username": "SME-001", "password": "owner-pass-1"})  # code is case-insensitive
    assert ok.status_code == 200 and ok.json()["business"] == "SME-001"


def test_register_rules():
    c = new_client()
    base = {"code": "SME-RULE", "sector": "retail", "password": "long-enough", "consent": True, **contact("SME-RULE")}
    assert c.post("/auth/register", json={**base, "consent": False}).status_code == 400
    assert c.post("/auth/register", json={**base, "password": "short"}).status_code == 422
    assert c.post("/auth/register", json={**base, "code": "has space"}).status_code == 422
    assert signup(c, base).status_code == 201
    assert new_client().post("/auth/register", json=base).status_code == 409


def test_lockout_after_five_wrong_passwords():
    owner("SME-LOCK")
    c = new_client()
    for _ in range(5):
        assert c.post("/auth/login", json={"username": "sme-lock", "password": "nope"}).status_code == 401
    r = c.post("/auth/login", json={"username": "sme-lock", "password": "owner-pass-1"})
    assert r.status_code == 429


# ---------- owners only see their own business ----------
def test_owner_isolation():
    a, b = owner("SME-A"), owner("SME-B")
    assert [x["code"] for x in a.get("/businesses").json()] == ["SME-A"]
    assert a.post("/businesses/SME-A/records", json=RECORD).status_code == 201
    assert b.get("/businesses/SME-A/records").status_code == 404
    assert b.post("/businesses/SME-A/records", json=RECORD).status_code == 404
    assert a.post("/businesses", json={"code": "SME-X", "sector": "retail"}).status_code == 403
    assert a.get("/admin/overview").status_code == 403


def test_records_flow():
    c = owner("SME-REC")
    r = c.post("/businesses/SME-REC/records", json=RECORD)
    assert r.status_code == 201
    assert r.json()["month"] == "2026-01-01" and r.json()["net_operating_result"] == -10000
    assert c.post("/businesses/SME-REC/records", json=RECORD).status_code == 409
    assert c.post("/businesses/SME-REC/records", json={**RECORD, "month": "2026-02-01", "revenue": -5}).status_code == 422


# ---------- CSV ----------
def test_template_download():
    r = new_client().get("/template.csv")
    assert r.status_code == 200 and r.text.startswith("month,revenue")


def test_csv_upload_and_reupload():
    c = owner("SME-CSV")
    with open(SAMPLE, "rb") as f:
        r = c.post("/businesses/SME-CSV/upload-csv", files={"file": ("s.csv", f, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 24 and r.json()["first_month"] == "2024-01"
    with open(SAMPLE, "rb") as f:
        r = c.post("/businesses/SME-CSV/upload-csv", files={"file": ("s.csv", f, "text/csv")})
    assert r.json()["inserted"] == 0 and len(r.json()["skipped_existing_months"]) == 24


def test_csv_bad_rows_save_nothing():
    c = owner("SME-BAD")
    bad = ("month,revenue,cogs,operating_expenses,cash_inflows,cash_outflows\n"
           "2026-01,\"120,000\",70000,60000,118000,125000\n"
           "2026-02,abc,70000,60000,118000,125000\n"
           "2026-03,-5,70000,60000,118000,125000\n")
    r = c.post("/businesses/SME-BAD/upload-csv", files={"file": ("b.csv", bad, "text/csv")})
    assert r.status_code == 422
    errs = r.json()["detail"]["errors"]
    assert any("Row 3" in e for e in errs) and any("Row 4" in e for e in errs)
    assert c.get("/businesses/SME-BAD/records").json() == []


def test_csv_missing_column():
    c = owner("SME-COL")
    r = c.post("/businesses/SME-COL/upload-csv", files={"file": ("c.csv", "month,revenue\n2026-01,5\n", "text/csv")})
    assert r.status_code == 400 and "cogs" in r.json()["detail"]


# ---------- admin ----------
def test_admin_create_reset_switch_off_delete(admin):
    r = admin.post("/admin/businesses", json={"code": "sme-adm", "sector": "service"})
    assert r.status_code == 201
    temp = r.json()["temporary_password"]
    assert r.json()["code"] == "SME-ADM" and len(temp) == 14

    o = new_client()
    assert o.post("/auth/login", json={"username": "SME-ADM", "password": temp}).status_code == 200
    assert o.post("/businesses/SME-ADM/records", json=RECORD).status_code == 201

    # switching off logs the owner out and blocks login
    assert admin.post("/admin/businesses/SME-ADM/active", json={"active": False}).status_code == 200
    assert o.get("/auth/me").status_code == 401
    assert o.post("/auth/login", json={"username": "SME-ADM", "password": temp}).status_code == 403

    # reset gives a new password and switches the login back on
    new = admin.post("/admin/businesses/SME-ADM/password").json()["temporary_password"]
    assert o.post("/auth/login", json={"username": "SME-ADM", "password": new}).status_code == 200

    rows = {b["code"]: b for b in admin.get("/admin/businesses").json()}
    assert rows["SME-ADM"]["months"] == 1 and rows["SME-ADM"]["loss_months"] == 1

    export = admin.get("/admin/export.csv")
    assert export.status_code == 200 and "SME-ADM,service,0,2026-01" in export.text

    assert admin.delete("/admin/businesses/SME-ADM").status_code == 200
    assert "SME-ADM" not in {b["code"] for b in admin.get("/admin/businesses").json()}
    assert o.get("/auth/me").status_code == 401


def test_admin_synthetic_and_overview(admin):
    r = admin.post("/admin/businesses", json={"code": "SYN-001", "sector": "retail", "is_synthetic": True})
    assert r.json()["temporary_password"] is None
    with open(SAMPLE, "rb") as f:
        assert admin.post("/businesses/SYN-001/upload-csv", files={"file": ("s.csv", f, "text/csv")}).status_code == 200
    o = admin.get("/admin/overview").json()
    assert o["synthetic_business_months"] == 24
    assert o["business_months"] == o["real_business_months"] + 24
    assert admin.post("/admin/businesses/SYN-001/password").status_code == 400


# ---------- admin sign-up from the login page ----------
def test_admin_signup_off_without_invite(monkeypatch):
    monkeypatch.delenv("ADMIN_SIGNUP_CODE", raising=False)
    c = new_client()
    assert c.get("/auth/options").json()["admin_signup"] is False
    r = c.post("/auth/register-admin", json={"username": "res1", "password": "long-enough", "admin_code": "x", **contact("res1")})
    assert r.status_code == 403


def test_env_code_only_for_first_admin(monkeypatch):
    from app.auth import clear_fails
    monkeypatch.setenv("ADMIN_SIGNUP_CODE", "change-me-to-a-secret")
    assert new_client().get("/auth/options").json()["admin_signup"] is False
    # admins already exist, so even a good .env code no longer works: it has to be a super admin code
    monkeypatch.setenv("ADMIN_SIGNUP_CODE", "kcau-study-2026")
    assert new_client().get("/auth/options").json()["admin_signup"] is False
    r = new_client().post("/auth/register-admin", json={"username": "res0", "password": "long-enough",
                                                        "admin_code": "kcau-study-2026", **contact("res0")})
    assert r.status_code == 403 and "super admin" in r.json()["detail"]
    clear_fails("admin-signup")


def invite(admin_client):
    r = admin_client.post("/admin/invite")
    assert r.status_code == 201, r.text
    return r.json()["code"]


def admin_signup(username, code):
    c = new_client()
    r = signup(c, {"username": username, "password": "long-enough", "admin_code": code, **contact(username + "x")},
               "/auth/register-admin")
    return c, r


def test_super_admin_invite_code(admin):
    from app.auth import clear_fails
    clear_fails("admin-signup")
    me = admin.get("/auth/me").json()
    assert me["is_super_admin"] is True
    code = invite(admin)
    assert len(code) == 19 and code.count("-") == 3
    st = admin.get("/admin/invite").json()
    assert st["active"]["created_by"] == "admin" and "code" not in str(st)  # the code is never shown again
    assert new_client().get("/auth/options").json()["admin_signup_mode"] == "invite"
    _, bad = admin_signup("res2", "aaaa-bbbb-cccc-dddd")
    assert bad.status_code == 403
    c, ok = admin_signup("Res2", code.upper().replace("-", " "))  # forgiving about case and spaces
    assert ok.status_code == 201 and ok.json()["role"] == "admin" and ok.json()["is_super_admin"] is False
    assert c.get("/admin/overview").status_code == 200  # logged in straight away
    # one use only
    _, again = admin_signup("res3", code)
    assert again.status_code == 403 and "already used" in again.json()["detail"]
    assert new_client().get("/auth/options").json()["admin_signup"] is False
    assert admin.get("/admin/invite").json()["last_used"]["used_by"] == "res2"
    # a new code cancels the old unused one
    old, new = invite(admin), invite(admin)
    assert admin_signup("res3", old)[1].status_code == 403
    # same username or business code can't be taken
    assert admin_signup("res2", new)[1].status_code == 409
    owner("SME-CLASH")
    assert admin_signup("sme-clash", new)[1].status_code == 409
    # cancel
    assert admin.delete("/admin/invite").json()["cancelled"] == 1
    assert admin_signup("res3", new)[1].status_code == 403
    # ordinary admins can't make codes or manage admins
    assert c.post("/admin/invite").status_code == 403
    assert c.get("/admin/invite").status_code == 403
    assert c.post("/admin/admins/admin/active", json={"active": False}).status_code == 403
    names = [a["username"] for a in c.get("/admin/admins").json()["admins"]]
    assert "admin" in names and "res2" in names
    acts = [a["action"] for a in admin.get("/admin/activity?action=admin").json()]
    assert "admin.invite_created" in acts and "admin.invite_cancelled" in acts and "admin.created" in acts
    clear_fails("admin-signup")


def test_super_admin_switch_off_and_hand_over(admin):
    from app.auth import clear_fails
    clear_fails("admin-signup")
    c, r = admin_signup("res4", invite(admin))
    assert r.status_code == 201
    assert admin.post("/admin/admins/admin/active", json={"active": False}).status_code == 400  # not yourself
    assert admin.post("/admin/admins/res4/active", json={"active": False}).json()["active"] is False
    assert c.get("/auth/me").status_code == 401  # logged out everywhere
    assert new_client().post("/auth/login", json={"username": "res4", "password": "long-enough"}).status_code != 200
    assert admin.post("/admin/admins/res4/make-super", json={"password": "admin-pass-123"}).status_code == 400  # switched off
    admin.post("/admin/admins/res4/active", json={"active": True})
    # super admin can't delete their own account while other admins exist
    r = admin.post("/auth/delete-account", json={"password": "admin-pass-123", "confirm": "admin"})
    assert r.status_code == 400 and "super admin" in r.json()["detail"]
    # hand over (needs password); the old unused code dies with the role
    leftover = invite(admin)
    assert admin.post("/admin/admins/res4/make-super", json={"password": "wrong"}).status_code == 400
    assert admin.post("/admin/admins/res4/make-super", json={"password": "admin-pass-123"}).json()["super_admin"] == "res4"
    assert admin.get("/auth/me").json()["is_super_admin"] is False
    assert admin.post("/admin/invite").status_code == 403
    assert admin_signup("res5", leftover)[1].status_code == 403
    res4 = new_client()
    res4.post("/auth/login", json={"username": "res4", "password": "long-enough"})
    assert res4.get("/auth/me").json()["is_super_admin"] is True
    supers = [a for a in res4.get("/admin/admins").json()["admins"] if a["is_super_admin"]]
    assert [a["username"] for a in supers] == ["res4"]
    # hand it back so the other tests keep "admin" as super admin
    assert res4.post("/admin/admins/admin/make-super", json={"password": "long-enough"}).status_code == 200
    clear_fails("admin-signup")


# ---------- passwords ----------
def test_signup_gives_recovery_code_and_change_password():
    c = new_client()
    r = signup(c, {"code": "SME-PW", "sector": "retail", "password": "first-pass-1", "consent": True, **contact("SME-PW")})
    rc = r.json()["recovery_code"]
    assert len(rc) == 19 and r.json()["must_change_password"] is False

    other = new_client()  # a second device
    assert other.post("/auth/login", json={"username": "SME-PW", "password": "first-pass-1"}).status_code == 200

    assert c.post("/auth/change-password", json={"current_password": "wrong", "new_password": "second-pass-2"}).status_code == 400
    assert c.post("/auth/change-password", json={"current_password": "first-pass-1", "new_password": "short"}).status_code == 422
    assert c.post("/auth/change-password", json={"current_password": "first-pass-1", "new_password": "second-pass-2"}).status_code == 200
    assert c.get("/auth/me").status_code == 200          # this device stays logged in
    assert other.get("/auth/me").status_code == 401      # other devices are logged out
    assert new_client().post("/auth/login", json={"username": "SME-PW", "password": "second-pass-2"}).status_code == 200


def test_forgot_password_with_recovery_code():
    c = new_client()
    rc = signup(c, {"code": "SME-FGT", "sector": "retail", "password": "old-pass-123", "consent": True, **contact("SME-FGT")}).json()["recovery_code"]
    c.post("/auth/logout")

    bad = new_client().post("/auth/recover", json={"username": "sme-fgt", "recovery_code": "aaaa-bbbb-cccc-dddd", "new_password": "new-pass-123"})
    assert bad.status_code == 400
    # spaces, capitals and missing dashes are forgiven
    typed = rc.upper().replace("-", " ")
    ok = new_client().post("/auth/recover", json={"username": "SME-FGT", "recovery_code": typed, "new_password": "new-pass-123"})
    assert ok.status_code == 200
    new_rc = ok.json()["recovery_code"]
    assert new_rc != rc
    assert new_client().post("/auth/login", json={"username": "SME-FGT", "password": "new-pass-123"}).status_code == 200
    # the old recovery code is used up
    again = new_client().post("/auth/recover", json={"username": "SME-FGT", "recovery_code": rc, "new_password": "other-pass-1"})
    assert again.status_code == 400


def test_new_recovery_code_replaces_old():
    c = new_client()
    first = signup(c, {"code": "SME-RC", "sector": "retail", "password": "pass-pass-1", "consent": True, **contact("SME-RC")}).json()["recovery_code"]
    second = c.post("/auth/recovery-code").json()["recovery_code"]
    assert new_client().post("/auth/recover", json={"username": "SME-RC", "recovery_code": first, "new_password": "x-pass-123"}).status_code == 400
    assert new_client().post("/auth/recover", json={"username": "SME-RC", "recovery_code": second, "new_password": "x-pass-123"}).status_code == 200


def test_admin_temp_password_must_be_changed(admin):
    temp = admin.post("/admin/businesses", json={"code": "SME-TMP", "sector": "retail"}).json()["temporary_password"]
    o = new_client()
    me = o.post("/auth/login", json={"username": "SME-TMP", "password": temp}).json()
    assert me["must_change_password"] is True
    assert o.post("/auth/change-password", json={"current_password": temp, "new_password": "my-own-pass"}).status_code == 200
    assert o.get("/auth/me").json()["must_change_password"] is False
    # an admin reset flips it back on
    admin.post("/admin/businesses/SME-TMP/password")
    assert o.get("/auth/me").status_code == 401  # reset logs the owner out
    assert new_client().post("/auth/login", json={"username": "SME-TMP", "password": temp}).status_code == 401


def test_add_missing_columns_on_old_table(tmp_path):
    """Simulates your MySQL users table from before this update."""
    from sqlalchemy import create_engine, inspect, text
    import app.database as dbmod
    old = create_engine(f"sqlite:///{tmp_path}/old.db")
    with old.begin() as c:
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(40))"))
    saved = dbmod.engine
    dbmod.engine = old
    try:
        dbmod.add_missing_columns()
        dbmod.add_missing_columns()  # running twice is harmless
    finally:
        dbmod.engine = saved
    cols = {c["name"] for c in inspect(old).get_columns("users")}
    assert {"must_change_password", "recovery_hash"} <= cols
    old.dispose()


# ---------- editing and deleting a month ----------
def test_edit_and_delete_month():
    c = owner("SME-EDIT")
    c.post("/businesses/SME-EDIT/records", json=RECORD)
    fixed = {**RECORD, "revenue": 150000}
    r = c.put("/businesses/SME-EDIT/records/2026-01", json=fixed)
    assert r.status_code == 200 and r.json()["net_operating_result"] == 20000
    assert c.get("/businesses/SME-EDIT/records").json()[0]["revenue"] == 150000
    assert c.put("/businesses/SME-EDIT/records/2025-07", json=fixed).status_code == 404
    assert c.put("/businesses/SME-EDIT/records/nonsense", json=fixed).status_code == 400
    # another owner can't touch it
    assert owner("SME-EDIT2").delete("/businesses/SME-EDIT/records/2026-01").status_code == 404
    assert c.delete("/businesses/SME-EDIT/records/2026-01").status_code == 200
    assert c.get("/businesses/SME-EDIT/records").json() == []


def test_future_month_rejected():
    from datetime import date
    c = owner("SME-FUT")
    nxt = date.today().replace(day=1)
    nxt = nxt.replace(year=nxt.year + 1) if nxt.month == 12 else nxt.replace(month=nxt.month + 1)
    r = c.post("/businesses/SME-FUT/records", json={**RECORD, "month": nxt.isoformat()})
    assert r.status_code == 422
    csv_text = "month,revenue,cogs,operating_expenses,cash_inflows,cash_outflows\n" + f"{nxt:%Y-%m},1,1,1,1,1\n"
    r = c.post("/businesses/SME-FUT/upload-csv", files={"file": ("f.csv", csv_text, "text/csv")})
    assert r.status_code == 422 and "future" in r.json()["detail"]["errors"][0]


# ---------- email, phone, verification, accountability ----------
from app import mailer  # noqa: E402


def last_code(to):
    import re
    msg = [m for m in mailer.OUTBOX if m["to"] == to][-1]
    return re.search(r"\b(\d{6})\b", msg["body"]).group(1)


def test_signup_contact_rules():
    c = new_client()
    base = {"code": "SME-CT", "sector": "retail", "password": "long-enough", "consent": True,
            "email": "ct@test.ke", "phone": "0712 345 678", "contact_consent": True}
    assert c.post("/auth/register", json={**base, "contact_consent": False}).status_code == 400
    assert c.post("/auth/register", json={**base, "email": "not-an-email"}).status_code == 422
    assert c.post("/auth/register", json={**base, "phone": "12345"}).status_code == 422
    r = signup(c, base)
    assert r.status_code == 201
    assert r.json()["contact"]["phone"] == "+2547•••••678"           # 0712 345 678 -> +254712345678, masked
    dup = new_client().post("/auth/register", json={**base, "code": "SME-CT2", "email": "CT@test.ke"})
    assert dup.status_code == 409                                     # same email, any capitals


def test_contacts_are_encrypted_at_rest():
    from sqlalchemy import text
    owner("SME-ENC")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT email_enc, phone_enc, email_hash FROM contacts c JOIN users u ON u.id = c.user_id WHERE u.username = 'sme-enc'")).one()
    assert "sme-enc@test.ke" not in " ".join(row) and "+254" not in " ".join(row)


def test_email_verification():
    c = owner("SME-VER")
    assert c.get("/auth/me").json()["contact"]["email_verified"] is True  # confirmed at sign-up
    c.put("/auth/contact", json={"email": "ver2@test.ke", "phone": "0712000999", "current_password": "owner-pass-1"})
    code = last_code("ver2@test.ke")
    assert c.post("/auth/email/verify", json={"code": "000000" if code != "000000" else "111111"}).status_code == 400
    r = c.post("/auth/email/verify", json={"code": code})
    assert r.status_code == 200 and r.json()["contact"]["email_verified"] is True
    assert c.post("/auth/email/verify", json={"code": code}).status_code == 400  # code used up


def test_change_contact_needs_password_and_reverifies():
    c = owner("SME-CHG")
    new = {"email": "new-chg@test.ke", "phone": "0798765432"}
    assert c.put("/auth/contact", json={**new, "current_password": "wrong"}).status_code == 400
    r = c.put("/auth/contact", json={**new, "current_password": "owner-pass-1"})
    assert r.status_code == 200 and r.json()["contact"]["email_verified"] is False
    assert last_code("new-chg@test.ke")  # a new code went to the new address


def test_login_with_email_and_forgot_by_email():
    c = owner("SME-MAIL")
    assert new_client().post("/auth/login", json={"username": "SME-MAIL@test.ke", "password": "owner-pass-1"}).status_code == 200

    anon = new_client()
    same = anon.post("/auth/forgot", json={"email": "nobody@test.ke"}).json()
    assert anon.post("/auth/forgot", json={"email": "sme-mail@test.ke"}).json() == same  # no hint which emails exist
    code = last_code("sme-mail@test.ke")
    bad = anon.post("/auth/reset-with-email", json={"email": "sme-mail@test.ke", "code": "999999" if code != "999999" else "888888", "new_password": "brand-new-1"})
    assert bad.status_code == 400
    ok = anon.post("/auth/reset-with-email", json={"email": "sme-mail@test.ke", "code": code, "new_password": "brand-new-1"})
    assert ok.status_code == 200 and ok.json()["recovery_code"]
    assert c.get("/auth/me").status_code == 401  # old sessions logged out
    assert new_client().post("/auth/login", json={"username": "sme-mail", "password": "brand-new-1"}).status_code == 200


def test_forgot_ignores_unverified_email():
    c = owner("SME-UNV")  # changing the email makes it unconfirmed again
    c.put("/auth/contact", json={"email": "unv2@test.ke", "phone": "0712000998", "current_password": "owner-pass-1"})
    before = len([m for m in mailer.OUTBOX if m["to"] == "unv2@test.ke"])
    new_client().post("/auth/forgot", json={"email": "unv2@test.ke"})
    assert len([m for m in mailer.OUTBOX if m["to"] == "unv2@test.ke"]) == before


def test_admin_contact_reveal_phone_verify_and_activity(admin):
    o = owner("SME-AUD")
    o.post("/businesses/SME-AUD/records", json=RECORD)
    o.put("/businesses/SME-AUD/records/2026-01", json={**RECORD, "revenue": 130000})
    row = {b["code"]: b for b in admin.get("/admin/businesses").json()}["SME-AUD"]
    assert row["contact"]["email"] == "sm•••••@test.ke"            # masked in the list
    full = admin.post("/admin/businesses/SME-AUD/contact/reveal").json()
    assert full["email"] == "sme-aud@test.ke" and full["phone"].startswith("+2547")
    assert admin.post("/admin/businesses/SME-AUD/contact/phone-verified", json={"verified": True}).json()["phone_verified"]
    acts = admin.get("/admin/activity?target=SME-AUD").json()
    kinds = [a["action"] for a in acts]
    for k in ("account.created", "record.added", "record.edited", "contact.viewed", "phone.verified"):
        assert k in kinds, k
    edited = next(a for a in acts if a["action"] == "record.edited")
    assert edited["actor"] == "sme-aud" and "revenue" in edited["detail"]
    viewed = next(a for a in acts if a["action"] == "contact.viewed")
    assert viewed["actor"] == "admin" and viewed["role"] == "admin"
    # owners can't read the log or anyone's contact
    assert o.get("/admin/activity").status_code == 403
    assert o.post("/admin/businesses/SME-AUD/contact/reveal").status_code == 403


def test_export_has_no_contact_details(admin):
    owner("SME-EXP")
    text = admin.get("/admin/export.csv").text
    assert "@" not in text and "+254" not in text


def test_admin_create_with_contact(admin):
    r = admin.post("/admin/businesses", json={"code": "SME-PAPER", "sector": "retail", "email": "paper@test.ke", "phone": "0711000111"})
    assert r.status_code == 201
    row = {b["code"]: b for b in admin.get("/admin/businesses").json()}["SME-PAPER"]
    assert row["contact"]["phone"] == "+2547•••••111"
    assert admin.post("/admin/businesses", json={"code": "SME-HALF", "sector": "retail", "email": "half@test.ke"}).status_code == 422


def test_delete_business_erases_contact(admin):
    from sqlalchemy import text
    owner("SME-ERASE")
    admin.delete("/admin/businesses/SME-ERASE")
    from app.crypto import blind_index
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM contacts WHERE email_hash = :h"), {"h": blind_index("email", "sme-erase@test.ke")}).scalar()
    assert n == 0


# ---------- SMS and live sending ----------
from app import sms  # noqa: E402


def last_sms_code(to):
    import re
    return re.search(r"\b(\d{6})\b", [m for m in sms.OUTBOX if m["to"] == to][-1]["message"]).group(1)


def test_phone_verification_by_sms():
    c = new_client()
    signup(c, {"code": "SME-SMS", "sector": "retail", "password": "long-enough", "consent": True,
                                   "email": "sms@test.ke", "phone": "0722 111 222", "contact_consent": True})
    assert c.post("/auth/phone/send-code").status_code == 200
    code = last_sms_code("+254722111222")
    assert c.post("/auth/phone/verify", json={"code": "000000" if code != "000000" else "111111"}).status_code == 400
    r = c.post("/auth/phone/verify", json={"code": code})
    assert r.status_code == 200 and r.json()["contact"]["phone_verified"] is True


def test_forgot_password_by_sms():
    c = new_client()
    signup(c, {"code": "SME-SMR", "sector": "retail", "password": "long-enough", "consent": True,
                                   "email": "smr@test.ke", "phone": "0733 444 555", "contact_consent": True})
    anon = new_client()
    before = len(sms.OUTBOX)
    anon.post("/auth/forgot", json={"phone": "0733444555"})
    assert len(sms.OUTBOX) == before          # phone not confirmed yet: nothing sent
    c.post("/auth/phone/send-code"); c.post("/auth/phone/verify", json={"code": last_sms_code("+254733444555")})
    r = anon.post("/auth/forgot", json={"phone": "+254 733 444 555"})
    assert r.status_code == 200
    code = last_sms_code("+254733444555")
    ok = anon.post("/auth/reset-with-code", json={"phone": "0733444555", "code": code, "new_password": "texted-pass-1"})
    assert ok.status_code == 200
    assert new_client().post("/auth/login", json={"username": "smr@test.ke", "password": "texted-pass-1"}).status_code == 200


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


def test_africas_talking_live_replies(monkeypatch):
    import httpx
    monkeypatch.setenv("AT_USERNAME", "biasharacheck")
    monkeypatch.setenv("AT_API_KEY", "key")
    sent = {}

    def ok(url, data, headers, timeout):
        sent.update(url=url, data=data, headers=headers)
        return FakeResp(201, {"SMSMessageData": {"Message": "Sent to 1/1", "Recipients": [
            {"statusCode": 101, "number": data["to"], "status": "Success", "cost": "KES 0.8000", "messageId": "x"}]}})
    monkeypatch.setattr(httpx, "post", ok)
    sms.send("+254700000001", "hi")
    assert sent["url"] == "https://api.africastalking.com/version1/messaging"
    assert sent["headers"]["apiKey"] == "key" and sent["data"]["username"] == "biasharacheck"

    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(201, {"SMSMessageData": {"Message": "Sent to 0/1", "Recipients": [
        {"statusCode": 405, "number": "+254700000001", "status": "InsufficientBalance", "cost": "0"}]}}))
    with pytest.raises(sms.SmsError, match="Top up"):
        sms.send("+254700000001", "hi")

    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(401, "The supplied authentication is invalid"))
    with pytest.raises(sms.SmsError, match="API key"):
        sms.send("+254700000001", "hi")

    monkeypatch.setenv("AT_USERNAME", "sandbox")
    monkeypatch.setattr(httpx, "post", ok)
    sms.send("+254700000001", "hi")
    assert sent["url"] == "https://api.sandbox.africastalking.com/version1/messaging"


def test_signup_needs_email_to_send(monkeypatch):
    def broken(*a, **k):
        raise mailer.MailError("The email account refused the login.")
    monkeypatch.setattr(mailer, "send", broken)
    c = new_client()
    r = c.post("/auth/register", json={"code": "SME-NOMAIL", "sector": "retail", "password": "long-enough", "consent": True,
                                       "email": "nomail@test.ke", "phone": "0744 000 111", "contact_consent": True})
    assert r.status_code == 502 and "couldn't send" in r.json()["detail"]
    assert c.get("/auth/me").status_code == 401
    monkeypatch.undo()
    assert signup(c, {"code": "SME-NOMAIL", "sector": "retail", "password": "long-enough", "consent": True,
                      "email": "nomail@test.ke", "phone": "0744 000 111", "contact_consent": True}).status_code == 201


def test_signup_waits_for_email_code():
    from app.auth import clear_fails
    c = new_client()
    base = {"code": "SME-WAIT", "sector": "hardware", "password": "long-enough", "consent": True,
            "email": "wait@test.ke", "phone": "0745 000 222", "contact_consent": True}
    r = c.post("/auth/register", json=base)
    assert r.status_code == 202 and r.json()["email"].endswith("@test.ke") and r.json()["pending"]
    assert c.get("/auth/me").status_code == 401                              # no account yet
    assert new_client().post("/auth/login", json={"username": "SME-WAIT", "password": "long-enough"}).status_code == 401
    code = last_code("wait@test.ke")
    wrong = "000000" if code != "000000" else "111111"
    bad = c.post("/auth/register/confirm", json={"email": "wait@test.ke", "code": wrong})
    assert bad.status_code == 400 and "4 tries left" in bad.json()["detail"]
    assert c.post("/auth/register/resend", json={"email": "wait@test.ke"}).status_code == 429  # too soon
    ok = c.post("/auth/register/confirm", json={"email": "WAIT@test.ke", "code": code})
    assert ok.status_code == 201 and ok.json()["contact"]["email_verified"] is True and ok.json()["recovery_code"]
    assert c.get("/auth/me").json()["business"] == "SME-WAIT"
    assert c.post("/auth/register/confirm", json={"email": "wait@test.ke", "code": code}).status_code == 404  # used up
    # too many wrong codes throws the sign-up away
    c2 = new_client()
    c2.post("/auth/register", json={**base, "code": "SME-WAIT2", "email": "wait2@test.ke"})
    for _ in range(5):
        c2.post("/auth/register/confirm", json={"email": "wait2@test.ke", "code": wrong if last_code("wait2@test.ke") != wrong else "222222"})
    clear_fails("signup:" + __import__("app.crypto", fromlist=["x"]).blind_index("email", "wait2@test.ke"))
    gone = c2.post("/auth/register/confirm", json={"email": "wait2@test.ke", "code": last_code("wait2@test.ke")})
    assert gone.status_code in (400, 404) and "again" in gone.json()["detail"]
    # new business types are accepted, unknown ones are not
    assert new_client().get("/sectors").json()[0] == {"id": "retail", "label": "Retail shop / duka"}
    assert c.post("/auth/register", json={**base, "code": "SME-X9", "email": "x9@test.ke", "sector": "spaceships"}).status_code == 422


def test_admin_messaging_status_and_test(admin):
    st = admin.get("/admin/messaging").json()
    assert st["email"]["mode"] == "console" and st["sms"]["mode"] == "console"
    r = admin.post("/admin/messaging/test", json={"channel": "sms", "to": "0711222333"})
    assert r.status_code == 200 and r.json()["mode"] == "console"
    assert sms.OUTBOX[-1]["to"] == "+254711222333"
    assert admin.post("/admin/messaging/test", json={"channel": "email", "to": "me@test.ke"}).json()["ok"]
    assert "messaging.test" in [a["action"] for a in admin.get("/admin/activity?action=messaging").json()]


# ---------- deleting your own account ----------
def test_owner_deletes_own_account():
    from sqlalchemy import text
    c = owner("SME-BYE")
    c.post("/businesses/SME-BYE/records", json=RECORD)
    dl = c.get("/businesses/SME-BYE/records.csv")
    assert dl.status_code == 200 and dl.text.startswith("month,revenue") and "2026-01" in dl.text

    assert c.post("/auth/delete-account", json={"password": "wrong", "confirm": "SME-BYE"}).status_code == 400
    assert c.post("/auth/delete-account", json={"password": "owner-pass-1", "confirm": "SME-BY"}).status_code == 400
    sent_before = len([m for m in mailer.OUTBOX if m["to"] == "sme-bye@test.ke"])
    r = c.post("/auth/delete-account", json={"password": "owner-pass-1", "confirm": "sme-bye"})
    assert r.status_code == 200
    assert len([m for m in mailer.OUTBOX if m["to"] == "sme-bye@test.ke"]) == sent_before + 1  # goodbye email

    assert c.get("/auth/me").status_code == 401
    assert new_client().post("/auth/login", json={"username": "SME-BYE", "password": "owner-pass-1"}).status_code == 401
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM businesses WHERE code='SME-BYE'")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM users WHERE username='sme-bye'")).scalar() == 0
        ips = conn.execute(text("SELECT ip FROM audit_log WHERE target='SME-BYE' OR actor='sme-bye'")).scalars().all()
    assert ips and all(ip == "" for ip in ips)  # history kept, IPs blanked
    # the code can be registered again later
    assert signup(new_client(), {"code": "SME-BYE", "sector": "retail", "password": "again-pass-1",
                                                     "consent": True, **contact("SME-BYE2")}).status_code == 201


def test_cant_download_or_delete_someone_else():
    a, b = owner("SME-OWN1"), owner("SME-OWN2")
    assert b.get("/businesses/SME-OWN1/records.csv").status_code == 404


def test_last_admin_cannot_delete_self(admin):
    from sqlalchemy import text
    with engine.begin() as conn:  # make "admin" the only active admin for this test
        others = conn.execute(text("SELECT id FROM users WHERE role='admin' AND username<>'admin' AND is_active=1")).scalars().all()
        conn.execute(text("UPDATE users SET is_active=0 WHERE role='admin' AND username<>'admin'"))
    try:
        r = admin.post("/auth/delete-account", json={"password": "admin-pass-123", "confirm": "admin"})
        assert r.status_code == 400 and "only admin" in r.json()["detail"]
    finally:
        with engine.begin() as conn:
            for i in others:
                conn.execute(text("UPDATE users SET is_active=1 WHERE id=:i"), {"i": i})


def test_textbee_replies(monkeypatch):
    import httpx
    monkeypatch.setenv("TEXTBEE_API_KEY", "tb-key")
    monkeypatch.setenv("AT_USERNAME", "sandbox")  # TextBee wins when both are set
    monkeypatch.setenv("AT_API_KEY", "x")
    assert sms.provider() == "textbee" and sms.mode() == "live"
    seen = {}

    class R:
        def __init__(self, code, body):
            self.status_code, self._b, self.text = code, body, str(body)
            self.headers = {"content-type": "application/json"}

        def json(self):
            return self._b

    def ok(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return R(201, {"data": {"success": True, "smsBatchId": "b1", "recipientCount": 1}})
    monkeypatch.setattr(httpx, "post", ok)
    sms.send("+254700000009", "hi")
    assert seen["url"].endswith("/gateway/send-sms") and seen["headers"]["x-api-key"] == "tb-key"
    assert seen["json"] == {"recipients": ["+254700000009"], "message": "hi"}

    for code, hint in ((401, "API key"), (429, "free limit"), (400, "TextBee app")):
        monkeypatch.setattr(httpx, "post", lambda *a, _c=code, **k: R(_c, {"message": "x"}))
        with pytest.raises(sms.SmsError, match=hint):
            sms.send("+254700000009", "hi")


# ---------- Biashara Pro: M-Pesa payments ----------
from app import mpesa  # noqa: E402

PDF_SAMPLE = "data/samples/mpesa_statement_SAMPLE.pdf"
CSV_SAMPLE = "data/samples/mpesa_business_SAMPLE.csv"


def pay(c, plan="month"):
    r = c.post("/payments/stk", json={"plan": plan, "phone": "0712 000 111"})
    assert r.status_code == 201, r.text
    return r.json()


def test_pro_page_and_test_mode_payment(admin):
    c = owner("SME-PRO1")
    page = c.get("/payments/pro").json()
    assert page["mode"] == "test" and page["status"]["active"] is False
    assert page["phone"].startswith("07") and {p["id"] for p in page["plans"]} == {"month", "year"}
    assert admin.get("/payments/pro").status_code == 400  # admins don't pay
    # Pro features are locked until paid
    with open(CSV_SAMPLE, "rb") as f:
        assert c.post("/businesses/SME-PRO1/mpesa-statement", files={"file": ("s.csv", f, "text/csv")}).status_code == 402
    p = pay(c)
    assert p["status"] == "pending" and p["mode"] == "test" and p["phone"].endswith("111")
    assert c.post("/payments/stk", json={"plan": "month", "phone": "0712000111"}).status_code == 429  # one at a time
    done = c.get(f"/payments/{p['id']}").json()
    assert done["status"] == "paid" and done["pro"]["active"] and done["pro"]["days_left"] >= 29
    assert c.get("/auth/me").json()["pro"]["active"] is True
    # polling again never adds the days twice
    assert c.get(f"/payments/{p['id']}").json()["pro"]["days_left"] == done["pro"]["days_left"]
    # a second payment extends from the current end date
    p2 = pay(c, "year")
    assert c.get(f"/payments/{p2['id']}").json()["pro"]["days_left"] >= 29 + 365
    # someone else can't see the payment
    assert owner("SME-PRO2").get(f"/payments/{p['id']}").status_code == 404
    acts = [a["action"] for a in admin.get("/admin/activity?target=SME-PRO1").json()]
    assert "payment.started" in acts and "payment.paid" in acts
    listing = admin.get("/admin/payments").json()
    assert listing["mode"] == "test" and any(x["business"] == "SME-PRO1" and x["status"] == "paid" for x in listing["payments"])
    assert listing["paid_total"] == sum(x["amount"] for x in listing["payments"] if x["status"] == "paid" and x["mode"] != "test")


def test_admin_gives_pro_free(admin):
    c = owner("SME-PRO3")
    assert admin.post("/admin/businesses/SME-PRO3/pro", json={"days": 90}).json()["pro"]["source"] == "admin"
    assert c.get("/auth/me").json()["pro"]["active"] is True
    row = next(b for b in admin.get("/admin/businesses").json() if b["code"] == "SME-PRO3")
    assert row["pro"]["active"] and row["pro"]["days_left"] >= 89
    assert admin.post("/admin/businesses/SME-PRO3/pro", json={"days": 0}).json()["pro"]["active"] is False
    assert c.post("/admin/businesses/SME-PRO3/pro", json={"days": 90}).status_code == 403


def test_daraja_requests_and_results(monkeypatch):
    import base64
    import httpx
    monkeypatch.setenv("MPESA_CONSUMER_KEY", "k")
    monkeypatch.setenv("MPESA_CONSUMER_SECRET", "s")
    mpesa._token.update(value="", until=0)
    assert mpesa.mode() == "sandbox" and mpesa.shortcode() == "174379"
    seen = {}

    class R:
        def __init__(self, code, body):
            self.status_code, self._b = code, body

        def json(self):
            return self._b

    def fake_get(url, **kw):
        seen["auth"] = kw["auth"]
        return R(200, {"access_token": "tok", "expires_in": "3599"})

    replies = []

    def fake_post(url, json, headers, timeout):
        seen.setdefault("posts", []).append((url, json, headers))
        return replies.pop(0)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    replies.append(R(200, {"MerchantRequestID": "m1", "CheckoutRequestID": "ws_CO_1", "ResponseCode": "0",
                           "CustomerMessage": "Success. Request accepted for processing"}))
    out = mpesa.stk_push("+254712000111", 1, "SME-001", "Biashara Pro")
    url, body, headers = seen["posts"][0]
    assert url == "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest" and headers["Authorization"] == "Bearer tok"
    assert body["PartyA"] == body["PhoneNumber"] == "254712000111" and body["PartyB"] == "174379"
    assert body["TransactionType"] == "CustomerPayBillOnline" and body["Amount"] == 1 and body["AccountReference"] == "SME-001"
    assert base64.b64decode(body["Password"]).decode() == "174379" + mpesa.SANDBOX_PASSKEY + body["Timestamp"]
    assert out["checkout_id"] == "ws_CO_1"
    # query: still waiting, cancelled, paid
    replies += [R(500, {"errorCode": "500.001.1001", "errorMessage": "The transaction is being processed"}),
                R(200, {"ResponseCode": "0", "ResultCode": "1032", "ResultDesc": "Request cancelled by user"}),
                R(200, {"ResponseCode": "0", "ResultCode": "0", "ResultDesc": "The service request is processed successfully."})]
    assert mpesa.stk_query("ws_CO_1")["state"] == "pending"
    cancelled = mpesa.stk_query("ws_CO_1")
    assert cancelled["state"] == "cancelled" and "cancelled" in cancelled["desc"]
    assert mpesa.stk_query("ws_CO_1")["state"] == "paid"
    # a Buy Goods till changes the transaction type and who gets paid
    monkeypatch.setenv("MPESA_TILL", "5551234")
    replies.append(R(200, {"MerchantRequestID": "m2", "CheckoutRequestID": "ws_CO_2", "ResponseCode": "0"}))
    mpesa.stk_push("+254712000111", 1, "SME-001", "Biashara Pro")
    body = seen["posts"][-1][1]
    assert body["TransactionType"] == "CustomerBuyGoodsOnline" and body["PartyB"] == "5551234"
    # wrong keys give a plain message
    mpesa._token.update(value="", until=0)
    monkeypatch.setattr(httpx, "get", lambda url, **kw: R(400, {}))
    try:
        mpesa.stk_push("+254712000111", 1, "SME-001", "x")
        raise AssertionError("should fail")
    except mpesa.MpesaError as exc:
        assert "consumer key" in str(exc)
    mpesa._token.update(value="", until=0)


def test_mpesa_callback():
    from app.auth import utcnow
    from app.models import Business, Payment
    c = owner("SME-CB1")
    with SessionLocal() as db:
        b = db.scalar(__import__("sqlalchemy").select(Business).where(Business.code == "SME-CB1"))
        now = utcnow()
        for cid, amt in (("ws_CO_cb1", 300), ("ws_CO_cb2", 300)):
            db.add(Payment(business_id=b.id, business_code=b.code, username="sme-cb1", plan="month", amount=amt,
                           phone_masked="+2547•••••111", mode="sandbox", checkout_id=cid, created_at=now, updated_at=now))
        db.commit()

    def cb(cid, code, amount):
        return {"Body": {"stkCallback": {"MerchantRequestID": "m", "CheckoutRequestID": cid, "ResultCode": code,
                "ResultDesc": "x", "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": "TJK1ABC2DE"}, {"Name": "PhoneNumber", "Value": 254712000111}]}}}}

    anon = new_client()
    assert anon.post("/payments/mpesa/callback/wrong-secret", json=cb("ws_CO_cb1", 0, 300)).status_code == 404
    url = "/payments/mpesa/callback/" + mpesa.callback_secret()
    assert anon.post(url, json=cb("ws_CO_cb2", 0, 1)).json()["ResultCode"] == 0  # amount doesn't match
    assert c.get("/auth/me").json()["pro"]["active"] is False
    assert anon.post(url, json=cb("ws_CO_cb1", 0, 300)).json()["ResultCode"] == 0
    hist = c.get("/payments/pro").json()
    assert hist["status"]["active"] is True
    got = sorted((p["status"], p["receipt"]) for p in hist["payments"])
    assert got == [("failed", "TJK1ABC2DE"), ("paid", "TJK1ABC2DE")]
    assert anon.post(url, json={"nonsense": True}).json()["ResultCode"] == 1


# ---------- Biashara Pro: M-Pesa statement import ----------
def test_statement_pdf_and_csv_agree(admin):
    from datetime import date
    from fastapi import HTTPException
    from app.statements import read_statement
    pdf, csvb = open(PDF_SAMPLE, "rb").read(), open(CSV_SAMPLE, "rb").read()
    for pw, words in (("", "locked"), ("nope", "didn't open")):
        try:
            read_statement(pdf, "s.pdf", pw)
            raise AssertionError("should fail")
        except HTTPException as exc:
            assert words in exc.detail
    a = read_statement(pdf, "s.pdf", "12345678", today=date(2026, 10, 9))
    b = read_statement(csvb, "s.csv", today=date(2026, 10, 9))
    assert a == b and a["transactions"] > 300 and a["skipped"] == 0
    assert [m["month"] for m in a["months"]] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    assert "incomplete" in a["months"][0]["note"] and a["months"][1]["note"] == ""
    # an unfinished month is never usable
    c = read_statement(csvb, "s.csv", today=date(2026, 9, 15))
    assert c["months"][-1]["usable"] is False and "isn't over" in c["months"][-1]["note"]
    try:
        read_statement(b"hello,world\n1,2\n", "x.csv")
        raise AssertionError("should fail")
    except HTTPException as exc:
        assert "Paid In" in exc.detail


def test_statement_import_flow(admin):
    c = owner("SME-MP1")
    for m in ("2026-06-01", "2026-07-01"):
        assert c.post("/businesses/SME-MP1/records", json={**RECORD, "month": m}).status_code == 201
    admin.post("/admin/businesses/SME-MP1/pro", json={"days": 30})
    with open(PDF_SAMPLE, "rb") as f:
        bad = c.post("/businesses/SME-MP1/mpesa-statement", files={"file": ("st.pdf", f, "application/pdf")},
                     data={"password": "wrong"})
    assert bad.status_code == 400
    with open(PDF_SAMPLE, "rb") as f:
        r = c.post("/businesses/SME-MP1/mpesa-statement", files={"file": ("st.pdf", f, "application/pdf")},
                   data={"password": "12345678"})
    assert r.status_code == 200, r.text
    months = {m["month"]: m for m in r.json()["months"]}
    assert months["2026-06"]["saved"] and not months["2026-08"]["saved"]
    pick = [{"month": k, "received": months[k]["received"], "count": months[k]["count_in"]} for k in ("2026-06", "2026-08")]
    out = c.post("/businesses/SME-MP1/mpesa-statement/apply", json={"months": pick}).json()
    assert out == {"updated": ["2026-06"], "missing": ["2026-08"]}
    june = next(x for x in c.get("/businesses/SME-MP1/records").json() if x["month"] == "2026-06-01")
    assert june["mobile_money_receipts"] == months["2026-06"]["received"] and june["transaction_count"] == months["2026-06"]["count_in"]
    acts = [a["action"] for a in admin.get("/admin/activity?target=SME-MP1").json()]
    assert "mpesa.statement_read" in acts and "mpesa.statement_applied" in acts
    # another owner can't import into this business
    with open(CSV_SAMPLE, "rb") as f:
        assert owner("SME-MP2").post("/businesses/SME-MP1/mpesa-statement", files={"file": ("s.csv", f, "text/csv")}).status_code == 404
    # admins can use it without paying
    with open(CSV_SAMPLE, "rb") as f:
        assert admin.post("/businesses/SME-MP1/mpesa-statement", files={"file": ("s.csv", f, "text/csv")}).status_code == 200


def test_deleting_business_keeps_unlinked_receipt(admin):
    c = owner("SME-PAYDEL")
    p = pay(c)
    c.get(f"/payments/{p['id']}")
    assert admin.delete("/admin/businesses/SME-PAYDEL").status_code == 200
    row = next(x for x in admin.get("/admin/payments").json()["payments"] if x["id"] == p["id"])
    assert row["business"] == "SME-PAYDEL (deleted)" and row["phone"] == "" and row["status"] == "paid"


def test_welcome_tour_shows_once():
    c = owner("SME-TOUR")
    assert c.get("/auth/me").json()["show_tour"] is True
    assert c.post("/auth/tour-done").json()["ok"]
    assert c.get("/auth/me").json()["show_tour"] is False
    assert new_client().post("/auth/tour-done").status_code == 401


def test_mpesa_connection_check(admin, monkeypatch):
    import httpx
    r = admin.post("/admin/mpesa/check").json()
    assert r["ok"] is False and r["mode"] == "test" and ".env" in r["message"]
    monkeypatch.setenv("MPESA_CONSUMER_KEY", "k")
    monkeypatch.setenv("MPESA_CONSUMER_SECRET", "s")

    class R:
        status_code = 200

        def json(self):
            return {"access_token": "tok", "expires_in": "3599"}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: R())
    r = admin.post("/admin/mpesa/check").json()
    assert r["ok"] is True and r["mode"] == "sandbox" and "174379" in r["message"]
    mpesa._token.update(value="", until=0)


def test_still_processing_is_not_a_failure_and_can_be_rechecked(monkeypatch):
    from app.auth import utcnow
    from app.models import Business, Payment
    assert mpesa.result("4999", "The transaction is still under processing")["state"] == "pending"
    assert mpesa.result("1", "x")["state"] == "failed"
    c = owner("SME-4999")
    with SessionLocal() as db:
        b = db.scalar(__import__("sqlalchemy").select(Business).where(Business.code == "SME-4999"))
        now = utcnow()
        db.add(Payment(business_id=b.id, business_code=b.code, username="sme-4999", plan="month", amount=1,
                       phone_masked="+2547•••••111", mode="sandbox", checkout_id="ws_CO_4999", status="failed",
                       result_desc="The transaction is still under processing", created_at=now, updated_at=now))
        db.commit()
        pid = db.scalar(__import__("sqlalchemy").select(Payment.id).where(Payment.checkout_id == "ws_CO_4999"))
    replies = [{"state": "pending", "desc": "M-Pesa is still processing the payment."}, {"state": "paid", "desc": "Paid."}]
    monkeypatch.setattr(mpesa, "stk_query", lambda cid: replies.pop(0))
    r = c.post(f"/payments/{pid}/check").json()
    assert r["status"] == "pending" and r["pro"]["active"] is False
    r = c.post(f"/payments/{pid}/check").json()
    assert r["status"] == "paid" and r["pro"]["active"] is True
    assert c.post(f"/payments/{pid}/check").json()["pro"]["days_left"] == r["pro"]["days_left"]  # never added twice
    assert owner("SME-4998").post(f"/payments/{pid}/check").status_code == 404


def test_statement_errors_are_explained(monkeypatch):
    import builtins
    from fastapi import HTTPException
    from app.statements import read_statement
    real_import = builtins.__import__

    def no_pdfplumber(name, *a, **k):
        if name == "pdfplumber":
            raise ImportError("no pdfplumber")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_pdfplumber)
    try:
        read_statement(open(PDF_SAMPLE, "rb").read(), "s.pdf", "12345678")
        raise AssertionError("should fail")
    except HTTPException as exc:
        assert exc.status_code == 503 and "pip install pdfplumber" in exc.detail
    monkeypatch.undo()
    try:
        read_statement(b"%PDF-1.7 not really a pdf", "s.pdf", "x")
        raise AssertionError("should fail")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_ngrok_callback_detection_and_test(admin, monkeypatch):
    import httpx
    mpesa._ngrok_cache.update(url="", at=0)
    monkeypatch.delenv("MPESA_CALLBACK_URL", raising=False)

    class R:
        def __init__(self, code, body):
            self.status_code, self._b = code, body

        def json(self):
            return self._b

    tunnels = {"tunnels": [{"public_url": "http://abc.ngrok-free.dev", "config": {"addr": "http://localhost:8000"}},
                           {"public_url": "https://abc.ngrok-free.dev", "config": {"addr": "http://localhost:8000"}}]}
    secret_path = mpesa.CALLBACK_PATH + mpesa.callback_secret()
    anon = new_client()

    def fake_get(url, **kw):
        if url == mpesa.NGROK_API:
            return R(200, tunnels)
        if url == "https://abc.ngrok-free.dev" + secret_path:  # "through ngrok" = straight to the app here
            r = anon.get(secret_path)
            return R(r.status_code, r.json())
        raise httpx.ConnectError("no")

    monkeypatch.setattr(httpx, "get", fake_get)
    assert mpesa.callback_base() == ("https://abc.ngrok-free.dev", "ngrok")
    assert mpesa.callback_url() == "https://abc.ngrok-free.dev" + secret_path
    assert anon.get("/payments/mpesa/callback/wrong").status_code == 404
    info = admin.get("/admin/payments").json()["callback"]
    assert info["source"] == "ngrok" and info["url"] == "https://abc.ngrok-free.dev"
    r = admin.post("/admin/mpesa/callback-test").json()
    assert r["ok"] is True and "abc.ngrok-free.dev" in r["message"]
    # the .env setting wins over ngrok
    monkeypatch.setenv("MPESA_CALLBACK_URL", "https://other.example.org/")
    assert mpesa.callback_base() == ("https://other.example.org", "env")
    assert admin.post("/admin/mpesa/callback-test").json()["ok"] is False
    # ngrok not running
    monkeypatch.delenv("MPESA_CALLBACK_URL")
    mpesa._ngrok_cache.update(url="", at=0)
    monkeypatch.setattr(httpx, "get", lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    assert mpesa.callback_base() == ("", "")
    assert mpesa.callback_url().startswith("https://example.com/")
    mpesa._ngrok_cache.update(url="", at=0)


# ---------- risk model: synthetic data, training, SHAP reasons ----------
def test_model_pipeline(admin):
    c = owner("SME-ML1")
    st = admin.get("/admin/model").json()
    assert st["libraries"] is True and st["ready"] is False
    assert c.get("/businesses/SME-ML1/risk").json()["source"] == "rules"
    # too little data gives a plain message, not a crash
    r = admin.post("/admin/model/train", json={"real_only": True})
    assert r.status_code == 400 and "Not enough data" in r.json()["detail"]
    # synthetic businesses: flagged, coded SYN-, no login
    out = admin.post("/admin/synthetic", json={"businesses": 40}).json()
    assert out["businesses"] == 40 and out["business_months"] >= 40 * 18 and 0 < out["loss_rate"] < 0.5
    rows = admin.get("/admin/businesses").json()
    syn = [b for b in rows if b["code"].startswith("SYN-")]
    assert len(syn) >= 40 and all(b["is_synthetic"] and b["account"] is None for b in syn)
    # train: four models compared, best saved, SHAP importance
    meta = admin.post("/admin/model/train", json={}).json()
    assert set(meta["models"]) == {"logreg", "rf", "xgb", "lgbm"} and meta["best"] in meta["models"]
    best = meta["models"][meta["best"]]
    assert 0.5 < best["roc_auc"] <= 1 and 0 < best["pr_auc"] <= 1 and sum(best["confusion"].values()) == meta["rows"]["test"]
    assert meta["rows"]["synthetic"] > 0 and meta["importance"] and "background" not in meta
    st = admin.get("/admin/model").json()
    assert st["ready"] and st["meta"]["importance"][0]["name"]
    # an owner with 6 months gets the model's risk with plain-language reasons
    months = [("2026-01", 100000, 60000, 30000), ("2026-02", 98000, 60000, 31000), ("2026-03", 90000, 61000, 32000),
              ("2026-04", 85000, 62000, 33000), ("2026-05", 80000, 63000, 34000), ("2026-06", 76000, 63000, 35000)]
    for m, rev, cogs, opex in months:
        c.post("/businesses/SME-ML1/records", json={**RECORD, "month": m + "-01", "revenue": rev, "cogs": cogs,
                                                     "operating_expenses": opex, "cash_inflows": rev, "cash_outflows": cogs + opex})
    r = c.get("/businesses/SME-ML1/risk").json()
    assert r["source"] == "model" and r["band"] in ("Low", "Moderate", "High") and 0 <= r["probability"] <= 1
    assert r["as_of"] == "2026-06" and r["reasons"] and all(x["text"] for x in r["reasons"])
    assert r["history"] and r["history"][-1]["month"] == "2026-06"
    # Kiswahili: same prediction, reasons and tips in Kiswahili
    assert c.put("/auth/settings", json={"language": "sw"}).json()["language"] == "sw"
    sw = c.get("/businesses/SME-ML1/risk").json()
    assert sw["probability"] == r["probability"] and [x["feature"] for x in sw["reasons"]] == [x["feature"] for x in r["reasons"]]
    assert all(x["text"] and x["text"] != y["text"] for x, y in zip(sw["reasons"], r["reasons"]))
    c.put("/auth/settings", json={"language": "en"})
    # owners can't train or see the model page
    assert c.post("/admin/model/train", json={}).status_code == 403
    acts = [a["action"] for a in admin.get("/admin/activity?action=model").json()]
    assert "model.trained" in acts
    # remove synthetic data again
    assert admin.delete("/admin/synthetic").json()["removed"] >= 40
    assert not [b for b in admin.get("/admin/businesses").json() if b["code"].startswith("SYN-")]


def test_features_and_label():
    import pandas as pd
    from ml import features as F
    rows = [{"business_id": 1, "sector": "retail", "is_synthetic": False, "start_date": None,
             "month": pd.Timestamp(2026, m, 1), "revenue": 100.0, "cogs": 60.0,
             "operating_expenses": 30.0 if m != 5 else 60.0, "cash_inflows": 100.0, "cash_outflows": 90.0,
             "mobile_money_receipts": 0.0, "closing_stock": 0.0, "outstanding_debt": 0.0, "transaction_count": 0.0}
            for m in range(1, 9)]
    X = F.build(F.records_frame(rows)).set_index("month")
    # May is a loss, so Feb, Mar and Apr are labelled 1; Jan (next 3 = Feb-Apr) is 0; the last 3 months have no label
    assert X.loc["2026-01-01", "label"] == 0
    assert list(X.loc["2026-02-01":"2026-04-01", "label"]) == [1, 1, 1]
    assert X.loc["2026-06-01":, "label"].isna().all()
    assert X.loc["2026-05-01", "margin"] < 0 and X.loc["2026-01-01", "sector_retail"] == 1


# ---------- reports, notifications, reminders, feedback ----------
def _months(c, code, n, start=(2025, 10), declining=False):
    y, m = start
    for i in range(n):
        rev = 120000 - (i * 6000 if declining else 0)
        c.post(f"/businesses/{code}/records", json={**RECORD, "month": f"{y}-{m:02d}-01", "revenue": rev,
                                                    "cogs": 70000, "operating_expenses": 40000,
                                                    "cash_inflows": rev, "cash_outflows": 110000})
        m += 1
        if m == 13:
            y, m = y + 1, 1


def test_pdf_reports(admin):
    c = owner("SME-REP")
    assert c.get("/businesses/SME-REP/report.pdf").status_code == 400  # no figures yet
    _months(c, "SME-REP", 7)
    r = c.get("/businesses/SME-REP/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-"
    assert c.get("/businesses/SME-REP/loan-report.pdf").status_code == 402  # Pro feature
    admin.post("/admin/businesses/SME-REP/pro", json={"days": 30})
    r = c.get("/businesses/SME-REP/loan-report.pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert owner("SME-REP2").get("/businesses/SME-REP/report.pdf").status_code == 404
    # full business report (Pro): every period works, other values are refused
    for m in (6, 12, 24, 0):
        r = c.get(f"/businesses/SME-REP/business-report.pdf?months={m}")
        assert r.status_code == 200 and r.content[:5] == b"%PDF-", (m, r.text[:200])
    assert c.get("/businesses/SME-REP/business-report.pdf?months=7").status_code == 422
    assert owner("SME-REP3").get("/businesses/SME-REP3/business-report.pdf").status_code == 402
    r = admin.get("/admin/study-report.pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert c.get("/admin/study-report.pdf").status_code == 403
    acts = [a["detail"] for a in admin.get("/admin/activity?action=report&target=SME-REP").json()]
    assert "monthly report" in acts and "loan-readiness report" in acts and "business report, last 12 months" in acts


def test_monthly_report_email_and_settings():
    from app import mailer
    c = owner("SME-SUM")
    before = len(mailer.OUTBOX)
    _months(c, "SME-SUM", 2)
    mails = [m for m in mailer.OUTBOX[before:] if m["to"] == "sme-sum@test.ke"]
    assert len(mails) == 2 and mails[-1]["attachments"] and mails[-1]["attachments"][0].endswith(".pdf")
    # filling in an older month doesn't email again
    c.post("/businesses/SME-SUM/records", json={**RECORD, "month": "2025-01-01"})
    assert len([m for m in mailer.OUTBOX[before:] if m["to"] == "sme-sum@test.ke"]) == 2
    # switched off: no email
    me = c.put("/auth/settings", json={"reports": False}).json()
    assert me["notify"] == {"reports": False, "reminders": True, "alerts": True}
    _months(c, "SME-SUM", 1, start=(2025, 12))
    assert len([m for m in mailer.OUTBOX[before:] if m["to"] == "sme-sum@test.ke"]) == 2
    assert c.put("/auth/settings", json={"language": "xx"}).status_code == 422


def test_reminders(admin):
    from datetime import date
    from app import mailer
    from app.notify import last_full_month, send_reminders
    month = last_full_month()
    c = owner("SME-REM")
    done = owner("SME-REM2")
    done.post("/businesses/SME-REM2/records", json={**RECORD, "month": f"{month:%Y-%m}-01"})
    quiet = owner("SME-REM3")
    quiet.put("/auth/settings", json={"reminders": False})
    before = len(mailer.OUTBOX)
    r = admin.post("/admin/reminders/send").json()
    sent_to = {m["to"] for m in mailer.OUTBOX[before:]}
    assert "sme-rem@test.ke" in sent_to and "sme-rem2@test.ke" not in sent_to and "sme-rem3@test.ke" not in sent_to
    assert r["month"] == f"{month:%Y-%m}" and r["emails"] >= 1
    # never twice in a month
    before = len(mailer.OUTBOX)
    admin.post("/admin/reminders/send")
    assert "sme-rem@test.ke" not in {m["to"] for m in mailer.OUTBOX[before:]}
    assert last_full_month(date(2027, 1, 5)) == date(2026, 12, 1)


def test_risk_alert_on_rise():
    from app import mailer, sms
    from app.database import SessionLocal
    from app.models import Business
    from app.notify import risk_alert
    c = owner("SME-ALR")
    c.post("/auth/phone/send-code")
    c.post("/auth/phone/verify", json={"code": last_sms_code([m["to"] for m in sms.OUTBOX][-1])})
    with SessionLocal() as db:
        b = db.scalar(__import__("sqlalchemy").select(Business).where(Business.code == "SME-ALR"))
        r = {"band": "High", "probability": 0.71, "as_of": "2026-06",
             "reasons": [{"text": "Costs grew 12 points faster than sales.", "tip": "List your three biggest costs."}]}
        e0, s0 = len(mailer.OUTBOX), len(sms.OUTBOX)
        assert risk_alert(db, b, "Low", r) is True
        db.commit()
    assert any("rose from Low to High" in m["message"] for m in sms.OUTBOX[s0:])
    assert any("went up to High" in m["subject"] for m in mailer.OUTBOX[e0:])
    c.put("/auth/settings", json={"alerts": False})
    with SessionLocal() as db:
        b = db.scalar(__import__("sqlalchemy").select(Business).where(Business.code == "SME-ALR"))
        assert risk_alert(db, b, "Low", r) is False


def test_feedback_questionnaire(admin):
    c = owner("SME-FB")
    q = c.get("/feedback/questions").json()
    assert len(q["questions"]) == 11 and q["given"] is False
    assert c.post("/feedback", json={"answers": [None] * 11}).status_code == 422
    assert c.post("/feedback", json={"answers": [6] + [None] * 10}).status_code == 422
    assert c.post("/feedback", json={"answers": [5, 4, None, 4, 5, 4, 5, 5, 5, 4, 3], "liked": "The charts",
                                     "confusing": "", "wish": "Kiswahili"}).status_code == 201
    assert c.get("/feedback/questions").json()["given"] is True
    s = admin.get("/admin/feedback").json()
    assert s["responses"] >= 1 and s["questions"][0]["mean"] is not None and s["groups"][0]["mean"] is not None
    assert any(x["wish"] == "Kiswahili" for x in s["comments"])
    assert c.get("/admin/feedback").status_code == 403


def test_pwa_files():
    c = new_client()
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"] and "no-cache" in sw.headers.get("cache-control", "")
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and "manifest" in m.headers["content-type"]
    man = m.json()
    assert man["start_url"] == "/" and man["display"] == "standalone" and {i["sizes"] for i in man["icons"]} >= {"192x192", "512x512"}
    for i in man["icons"]:
        assert c.get(i["src"]).status_code == 200
    for page in ("/login",):
        html = c.get(page).text
        assert "/manifest.webmanifest" in html and "/static/i18n.js" in html and "/static/pwa.js" in html
    assert c.get("/static/i18n.js").status_code == 200


def test_kiswahili_reasons_cover_every_feature():
    from ml import features as F
    from ml.predict import explain, explain_sw
    vals = {"margin": -0.05, "margin_3m": 0.12, "margin_trend": -0.04, "losses_last3": 2, "rev_growth_3m": -0.2,
            "cost_growth_3m": 0.3, "cost_vs_sales_growth": 0.25, "rev_mom": 0.4, "cogs_ratio": 0.8, "opex_ratio": 0.3,
            "net_cf_ratio": -0.1, "neg_cf_months_3": 2, "mpesa_share": 0.6, "tx_growth_3m": -0.1, "debt_to_rev": 0.9,
            "debt_growth_3m": 0.5, "stock_to_rev": 1.2, "age_months": 14, "month_sin": 0.5, "month_cos": 0.8}
    for f in F.FEATURES:
        v = vals.get(f, 1)
        for up in (True, False):
            en, sw = explain(f, v, up), explain_sw(f, v, up)
            assert sw[0] and isinstance(sw[0], str) and sw[0] != en[0], f


def test_training_csv_import(admin, tmp_path):
    from ml.synthetic import write_csv
    path = tmp_path / "trn.csv"
    info = write_csv(str(path), businesses=5, seed=7, prefix="IMP")
    r = admin.post("/admin/training-csv", files={"file": ("trn.csv", path.read_bytes(), "text/csv")})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["businesses_added"] == 5 and out["business_months_added"] == info["business_months"]
    rows = {b["code"]: b for b in admin.get("/admin/businesses").json()}
    assert rows["IMP-0001"]["is_synthetic"] and rows["IMP-0001"]["account"] is None
    again = admin.post("/admin/training-csv", files={"file": ("trn.csv", path.read_bytes(), "text/csv")}).json()
    assert again["businesses_added"] == 0 and len(again["skipped_existing"]) == 5
    bad = "business_code,sector,month,revenue\nX-1,retail,2025-01,5\n"
    r = admin.post("/admin/training-csv", files={"file": ("bad.csv", bad.encode(), "text/csv")})
    assert r.status_code == 400 and "missing these columns" in r.json()["detail"]
    bad = ("business_code,sector,month,revenue,cogs,operating_expenses,cash_inflows,cash_outflows\n"
           "IMP-X1,retail,2025-13,5,1,1,5,2\n")
    r = admin.post("/admin/training-csv", files={"file": ("bad.csv", bad.encode(), "text/csv")})
    assert r.status_code == 400 and "Row 2" in r.json()["detail"]
    assert owner("SME-IMPX").post("/admin/training-csv", files={"file": ("t.csv", b"x", "text/csv")}).status_code == 403
    admin.delete("/admin/synthetic")


def test_email_report_to_self(admin):
    from app import mailer
    c = owner("SME-MAILR")
    _months(c, "SME-MAILR", 7)
    me = c.get("/auth/me").json()
    assert me["contact"]["email_verified"]
    to = contact("SME-MAILR")["email"].lower()
    before = len([m for m in mailer.OUTBOX if m["to"] == to])
    r = c.post("/businesses/SME-MAILR/reports/email", json={"kind": "monthly"})
    assert r.status_code == 200, r.text
    assert "@" in r.json()["sent_to"] and "\u2022" in r.json()["sent_to"]
    sent = [m for m in mailer.OUTBOX if m["to"] == to][before:]
    assert len(sent) == 1 and sent[0]["attachments"][0].endswith(".pdf")
    # Pro reports need Pro
    assert c.post("/businesses/SME-MAILR/reports/email", json={"kind": "business"}).status_code == 402
    admin.post("/admin/businesses/SME-MAILR/pro", json={"days": 30})
    assert c.post("/businesses/SME-MAILR/reports/email", json={"kind": "business", "months": 6}).status_code == 200
    assert c.post("/businesses/SME-MAILR/reports/email", json={"kind": "loan"}).status_code == 200
    assert c.post("/businesses/SME-MAILR/reports/email", json={"kind": "business", "months": 5}).status_code == 422
    # only to your own business, and at most 10 a day
    assert owner("SME-MAILX").post("/businesses/SME-MAILR/reports/email", json={"kind": "monthly"}).status_code == 404
    for _ in range(7):
        assert c.post("/businesses/SME-MAILR/reports/email", json={"kind": "monthly"}).status_code == 200
    assert c.post("/businesses/SME-MAILR/reports/email", json={"kind": "monthly"}).status_code == 429


def test_import_any_spreadsheet():
    import io as _io
    import json as _json
    c = owner("SME-IMPT")
    messy = ("MAMA MBOGA SHOP\nRecords 2025\n\nMwezi;Mauzo (KES);Gharama ya bidhaa;Rent;Wages\n"
             "Jan 2025;\"KES 50,000\";30 000;5000;4000\nFeb 2025;52,000/=;31000;5000;4000\nJUMLA;102000;61000;10000;8000\n")
    r = c.post("/businesses/SME-IMPT/import/preview", files={"file": ("shop.csv", messy.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "ok" and [x["month"] for x in p["records"]] == ["2025-01", "2025-02"]
    assert p["records"][0]["revenue"] == 50000 and p["records"][0]["operating_expenses"] == 9000
    assert p["mapping"]["revenue"] == "Mauzo (KES)" and p["notes"] and p["new_months"] == 2
    r = c.post("/businesses/SME-IMPT/import", files={"file": ("shop.csv", messy.encode(), "text/csv")})
    assert r.json()["inserted"] == 2
    again = c.post("/businesses/SME-IMPT/import", files={"file": ("shop.csv", messy.encode(), "text/csv")}).json()
    assert again["inserted"] == 0 and again["skipped_existing"] == 2
    changed = messy.replace('"KES 50,000"', "55000")
    r = c.post("/businesses/SME-IMPT/import", files={"file": ("shop.csv", changed.encode(), "text/csv")}, data={"replace": "1"}).json()
    assert r["updated"] == 2 and r["inserted"] == 0
    assert c.get("/businesses/SME-IMPT/records").json()[0]["revenue"] == 55000
    # transactions in an Excel file are added up per month
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Date", "Item", "Type", "Amount"])
    from datetime import datetime as _dt
    ws.append([_dt(2025, 3, 2), "maize", "Sale", 1200]); ws.append([_dt(2025, 3, 9), "rent", "Expense", 800])
    ws.append([_dt(2025, 4, 1), "beans", "Sale", 2000])
    buf = _io.BytesIO(); wb.save(buf)
    p = c.post("/businesses/SME-IMPT/import/preview", files={"file": ("book.xlsx", buf.getvalue(), "application/octet-stream")}).json()
    assert p["status"] == "ok" and p["records"][0] == {**p["records"][0], "month": "2025-03", "revenue": 1200, "operating_expenses": 800}
    # no dates: ask for the first month, then it works
    nod = "Sales,Expenses\n100,60\n110,70\n"
    p = c.post("/businesses/SME-IMPT/import/preview", files={"file": ("x.csv", nod.encode(), "text/csv")}).json()
    assert p["status"] == "need_start"
    p = c.post("/businesses/SME-IMPT/import/preview", files={"file": ("x.csv", nod.encode(), "text/csv")},
               data={"mapping": _json.dumps({"start_month": "2024-05"})}).json()
    assert [x["month"] for x in p["records"]] == ["2024-05", "2024-06"]
    # the owner can point at the sales column themselves
    odd = "When,Colour,Thing A,Thing B\n2024-01,red,500,300\n2024-02,blue,600,350\n"
    p = c.post("/businesses/SME-IMPT/import/preview", files={"file": ("o.csv", odd.encode(), "text/csv")}).json()
    assert p["status"] == "need_sales" and {c_["name"] for c_ in p["columns"]} >= {"Thing A", "Thing B"}
    p = c.post("/businesses/SME-IMPT/import/preview", files={"file": ("o.csv", odd.encode(), "text/csv")},
               data={"mapping": _json.dumps({"revenue": "Thing A", "total_costs": "Thing B"})}).json()
    assert p["status"] == "ok" and p["records"][0]["revenue"] == 500 and p["records"][0]["operating_expenses"] == 300
    # an M-Pesa statement is recognised, and other people's businesses are refused
    st = "Receipt No.,Completion Time,Details,Transaction Status,Paid In,Withdrawn\nA,1,x,Completed,5,\n"
    assert c.post("/businesses/SME-IMPT/import/preview", files={"file": ("s.csv", st.encode(), "text/csv")}).json()["status"] == "mpesa"
    assert owner("SME-IMPY").post("/businesses/SME-IMPT/import/preview", files={"file": ("x.csv", nod.encode(), "text/csv")}).status_code == 404


# ---------- username, figures, distress model, evidence ----------
def test_change_username():
    c = owner("SME-UN1")
    bad = c.put("/auth/username", json={"username": "duka-la-mama", "current_password": "wrong-pass"})
    assert bad.status_code == 400
    assert c.put("/auth/username", json={"username": "ab", "current_password": "owner-pass-1"}).status_code == 422
    assert c.put("/auth/username", json={"username": "duka0712345678", "current_password": "owner-pass-1"}).status_code == 422
    assert c.put("/auth/username", json={"username": "admin", "current_password": "owner-pass-1"}).status_code == 409
    owner("SME-UN2")
    assert c.put("/auth/username", json={"username": "sme-un2", "current_password": "owner-pass-1"}).status_code == 409
    r = c.put("/auth/username", json={"username": "Duka-La-Mama", "current_password": "owner-pass-1"})
    assert r.status_code == 200 and r.json()["username"] == "duka-la-mama" and r.json()["business"] == "SME-UN1"
    # the new username, the business code and the email all log in
    for name in ("duka-la-mama", "SME-UN1", "sme-un1@test.ke"):
        d = new_client().post("/auth/login", json={"username": name, "password": "owner-pass-1"})
        assert d.status_code == 200 and d.json()["business"] == "SME-UN1", name
    # nobody else can take it
    c2 = owner("SME-UN3")
    assert c2.put("/auth/username", json={"username": "duka-la-mama", "current_password": "owner-pass-1"}).status_code == 409
    # recovery with the business code still works
    assert c.get("/businesses/SME-UN1/records").status_code == 200


def test_figures_with_formulas():
    c = owner("SME-FIG")
    rows = [("2026-01", 100000, 60000, 30000, 98000, 85000), ("2026-02", 110000, 66000, 30000, 108000, 92000),
            ("2026-03", 105000, 63000, 31000, 100000, 96000), ("2026-04", 98000, 62000, 32000, 95000, 99000),
            ("2026-05", 90000, 61000, 32000, 88000, 97000), ("2026-06", 92000, 60000, 30000, 80000, 95000)]
    for m, rev, cogs, opex, cin, cout in rows:
        assert c.post("/businesses/SME-FIG/records", json={**RECORD, "month": m + "-01", "revenue": rev, "cogs": cogs,
                      "operating_expenses": opex, "cash_inflows": cin, "cash_outflows": cout,
                      "closing_stock": 150000, "outstanding_debt": 20000}).status_code == 201
    f = c.get("/businesses/SME-FIG/figures").json()
    L = f["latest"]
    assert L["month"] == "2026-06" and L["gross_profit"] == 32000 and L["operating_profit"] == 2000
    assert abs(L["gross_margin"] - 32000 / 92000) < 1e-9 and L["net_cash_flow"] == -15000
    assert abs(L["break_even_sales"] - 30000 / (32000 / 92000)) < 1e-6 and L["profit_cash_gap"] == 17000
    items = {i["key"]: i for i in f["items"]}
    assert items["gross_profit"]["worked"] == "KES 92,000 - KES 60,000 = KES 32,000"
    assert items["operating_profit"]["formula"].startswith("Gross profit - running expenses")
    assert items["stock_cover"]["value"] == 2.5 and "debt_months" in items
    titles = [x["title"] for x in f["checks"]]
    assert "Profit, but cash went down" in titles and "Cash shortfall in 2 or more of the last 3 months" in titles
    assert "Close to break-even" in titles and all(x["rule"] for x in f["checks"])
    assert f["statement"]["profit"][2] == ["= Gross profit", 32000]
    assert f["trends"]["sales"]["now"] == 98000 + 90000 + 92000 and f["totals"]["loss_months"] == 1  # May: 90,000 - 61,000 - 32,000
    # integrity: months, no gaps, a fingerprint that changes when any figure changes, and the change log
    i = f["integrity"]
    assert i["months"] == 6 and i["gaps"] == [] and len(i["fingerprint"]) == 64 and i["changes"]["added"] == 6
    c.put("/businesses/SME-FIG/records/2026-06", json={**RECORD, "month": "2026-06-01", "revenue": 92001, "cogs": 60000,
          "operating_expenses": 30000, "cash_inflows": 80000, "cash_outflows": 95000, "closing_stock": 150000, "outstanding_debt": 20000})
    i2 = c.get("/businesses/SME-FIG/figures").json()["integrity"]
    assert i2["fingerprint"] != i["fingerprint"] and i2["changes"]["edited"] == 1
    tr = c.get("/businesses/SME-FIG/figures").json()["track_record"]
    assert tr["judged"] >= tr["right"] >= 0 and all(x["month"] <= "2026-03" for x in tr["checks"])
    assert new_client().get("/businesses/SME-FIG/figures").status_code == 401
    assert owner("SME-FIG2").get("/businesses/SME-FIG/figures").status_code in (403, 404)


def test_distress_model_and_evidence(admin):
    import math
    c = owner("SME-DST")
    assert new_client().get("/method/evidence").status_code == 401
    assert admin.post("/admin/synthetic", json={"businesses": 60}).status_code in (200, 201)
    meta = admin.post("/admin/model/train", json={}).json()
    d = meta["distress"]
    assert "error" not in d, d
    names = [x["feature"] for x in d["coefficients"]]
    assert names[0] == "(intercept)" and len(names) == 9
    assert all(0 <= x["p_value"] <= 1 and x["ci_low"] <= x["odds_ratio"] <= x["ci_high"] for x in d["coefficients"])
    assert 0.5 < d["test"]["roc_auc"] <= 1 and 0 <= d["mcfadden_r2"] <= 1 and "hosmer_lemeshow" in d["test"]
    ev = meta["evidence"]
    assert sum(b["n"] for b in ev["bands"]) == meta["rows"]["test"] and ev["calibration"] and ev["rule"]["name"]
    _months(c, "SME-DST", 6, start=(2026, 1), declining=True)
    r = c.get("/businesses/SME-DST/risk").json()
    ds = r["distress"]
    assert ds and ds["source"] == "logistic_regression" and len(ds["terms"]) == 8
    # the calculation adds up: intercept + contributions = log-odds, and the logistic function gives the probability
    assert abs(ds["intercept"] + sum(t["contribution"] for t in ds["terms"]) - ds["log_odds"]) < 1e-3
    assert abs(1 / (1 + math.exp(-ds["log_odds"])) - ds["probability"]) < 1e-3
    assert all(t["text"] for t in ds["terms"])
    e = c.get("/method/evidence").json()
    assert e["ready"] and e["evidence"]["bands"] and e["distress"]["coefficients"][1]["name"] and "background" not in e
    sw = c.put("/auth/settings", json={"language": "sw"}) and c.get("/businesses/SME-DST/risk").json()["distress"]
    assert sw["probability"] == ds["probability"]
    c.put("/auth/settings", json={"language": "en"})
    assert admin.delete("/admin/synthetic").json()["removed"] >= 60


def test_assistant_answers_from_own_figures():
    c = owner("SME-BOT")
    r = c.post("/assistant/ask", json={"message": "hello"}).json()
    assert r["intent"] == "greeting" and "SME-BOT" in r["reply"]
    assert "add" in c.post("/assistant/ask", json={"message": "what were my sales in march"}).json()["reply"].lower()
    for m, rev, cogs, opex in [("2026-01", 100000, 60000, 30000), ("2026-02", 110000, 66000, 30000), ("2026-03", 90000, 61000, 32000)]:
        c.post("/businesses/SME-BOT/records", json={**RECORD, "month": m + "-01", "revenue": rev, "cogs": cogs,
                                                     "operating_expenses": opex, "cash_inflows": rev, "cash_outflows": cogs + opex})
    ask = lambda q, **k: c.post("/assistant/ask", json={"message": q, **k}).json()  # noqa: E731
    r = ask("What were my sales in February?")
    assert r["intent"] == "figure" and "KES 110,000" in r["reply"] and r["context"] == {"figure": "sales", "month": "2026-02"}
    assert "KES 90,000" in ask("and in march?", context=r["context"])["reply"]
    assert "KES 44,000" in ask("gross profit in feb")["reply"]                      # 110,000 - 66,000
    r = ask("what was my profit in march")
    assert "loss of KES 3,000" in r["reply"]                                          # 90,000 - 61,000 - 32,000
    r = ask("What if I cut running costs by 10%?")
    assert r["intent"] == "whatif" and "+KES 3,067" in r["reply"]                     # 10% of the 3-month average 30,667
    assert ask("what is break even")["intent"] == "explain"
    assert ask("how is gross margin calculated")["intent"] == "calc"
    assert ask("how do I change my username")["intent"] == "howto:username"
    assert ask("who can see my data")["intent"] == "privacy"
    assert ask("how many loss months")["intent"] == "losses"
    sw = ask("mauzo yangu ya februari ni ngapi")
    assert sw["lang"] == "sw" and "KES 110,000" in sw["reply"] and "Mauzo" in sw["reply"]
    assert ask("qwerty zxcv")["intent"] == "unknown"
    # topics are logged, the words are not
    from app.database import SessionLocal
    from app.models import AuditLog
    with SessionLocal() as db:
        rows = db.query(AuditLog).filter(AuditLog.action == "assistant.asked", AuditLog.target == "SME-BOT").all()
        assert len(rows) >= 10 and all("sales" not in r.detail.lower() or r.detail == "figure" for r in rows)
        assert not any("qwerty" in (r.detail + r.target) for r in rows)
    assert new_client().post("/assistant/ask", json={"message": "hi"}).status_code == 401
    assert c.post("/assistant/ask", json={"message": ""}).status_code == 422


def test_pro_auto_renew_cancel_and_renewal_prompt(admin):
    from datetime import timedelta

    from app import mailer
    from app.auth import utcnow
    from app.database import SessionLocal
    from app.models import Business, Payment
    from app.renewals import process
    c = owner("SME-REN")
    p = c.post("/payments/stk", json={"plan": "month", "phone": "0712 000 222", "auto_renew": True}).json()
    st = c.get(f"/payments/{p['id']}").json()["pro"]
    assert st["active"] and st["auto_renew"] and st["plan"] == "month" and st["renewal"]["amount"] >= 1
    assert st["renewal"]["phone"].endswith("222") and st["until"].endswith("Z")
    # cancel: Pro stays until its end date, no renewal, the saved number is deleted
    out = c.post("/payments/auto-renew", json={"on": False}).json()
    assert out["status"]["active"] and not out["status"]["auto_renew"] and out["status"]["cancelled_at"]
    with SessionLocal() as db:
        b = db.query(Business).filter_by(code="SME-REN").one()
        assert b.renew_phone_enc is None and not b.auto_renew
        b.pro_until = utcnow() + timedelta(hours=12)   # Pro is about to end
        db.commit()
        assert process(db)["prompts"] == 0 and not db.query(Payment).filter_by(business_code="SME-REN", kind="renewal").count()
    # turn it back on: a day before the end, a notice and an M-Pesa prompt for the same plan
    assert c.post("/payments/auto-renew", json={"on": True}).json()["status"]["auto_renew"]
    with SessionLocal() as db:
        first = process(db)
        assert first["notices"] == 1 and first["prompts"] == 1
        assert process(db)["prompts"] == 0                # never twice for the same end date
    pays = c.get("/payments/pro").json()["payments"]
    assert pays[0]["kind"] == "renewal"
    # test mode: the renewal "goes through" and Pro runs on from the old end date
    st = c.get("/payments/pro").json()["status"]
    assert st["days_left"] >= 30 and st["auto_renew"]
    assert any("renews soon" in m["subject"].lower() for m in mailer.OUTBOX if m["to"] == "sme-ren@test.ke")
    acts = [a["action"] for a in admin.get("/admin/activity?target=SME-REN").json()]
    assert {"pro.renewal_cancelled", "pro.renewal_on", "pro.renewal_notice", "payment.paid"} <= set(acts)
    assert admin.post("/admin/renewals/run").status_code == 200
    # Pro given free by the study team can't be put on automatic renewal
    c2 = owner("SME-REN2")
    admin.post("/admin/businesses/SME-REN2/pro", json={"days": 30})
    assert c2.post("/payments/auto-renew", json={"on": True}).status_code == 400
    assert c2.post("/payments/auto-renew", json={"on": False}).status_code == 200


def test_assistant_links_and_install_answer():
    c = owner("SME-LNK")
    ask = lambda q: c.post("/assistant/ask", json={"message": q}).json()  # noqa: E731
    r = ask("can I download the app to my phone?")
    assert r["intent"] == "howto:install" and r["links"][0]["href"] == "/install"
    assert ask("how do I upload excel")["links"][0]["href"] == "/#upload"
    assert ask("how do i get a report")["links"][0]["href"] == "/#reports"
    assert ask("how do I add a month")["links"][0]["href"] == "/#add"


def test_assistant_subscription_answers():
    c = owner("SME-SUB")
    ask = lambda q: c.post("/assistant/ask", json={"message": q}).json()  # noqa: E731
    assert "free plan" in ask("how do I cancel my subscription")["reply"]
    p = c.post("/payments/stk", json={"plan": "month", "phone": "0712 000 333", "auto_renew": True}).json()
    c.get(f"/payments/{p['id']}")
    r = ask("when does my subscription end?")
    assert r["intent"] == "subscription" and "active until" in r["reply"] and "Cancel automatic renewal" in r["reply"]
    c.post("/payments/auto-renew", json={"on": False})
    assert "Automatic renewal is off" in ask("cancel renewal")["reply"]


def test_install_page_and_manifest():
    import json
    c = new_client()
    page = c.get("/install").text
    assert 'id="ga-install"' in page and 'id="ga-guide"' in page
    m = json.loads(c.get("/manifest.webmanifest").text)
    assert m["id"] == "/" and m["display"] == "standalone" and len(m["screenshots"]) >= 2
    assert any(s.get("form_factor") == "narrow" for s in m["screenshots"])
    for s in m["screenshots"] + m["icons"]:
        assert c.get(s["src"]).status_code == 200, s["src"]
    # the manifest is fetched with cookies, so an ngrok free address (which needs its cookie) can still install
    for p in ("/", "/login", "/account", "/how", "/install", "/admin"):
        assert 'rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials"' in c.get(p).text, p
    assert "data-install" in c.get("/login").text and 'id="app-promo"' in c.get("/").text


def test_outlook_1_to_12_months(admin):
    c = owner("SME-OUT")
    assert c.get("/businesses/SME-OUT/outlook?months=6").json() == {"ready": False, "reason": "few_months", "months_needed": 3}
    assert admin.post("/admin/synthetic", json={"businesses": 60}).status_code in (200, 201)
    meta = admin.post("/admin/model/train", json={}).json()
    hz = meta["horizon"]
    assert "error" not in hz, hz
    assert set(hz["horizons"]) == {str(h) for h in range(1, 13)} and hz["horizons"]["1"]["enough"]
    _months(c, "SHOULD-NOT-EXIST" if False else "SME-OUT", 8, start=(2025, 11), declining=True)
    main = c.get("/businesses/SME-OUT/risk").json()
    out3 = c.get("/businesses/SME-OUT/outlook?months=3").json()
    assert out3["ready"] and len(out3["curve"]) == 12
    # anchored: the 3-month outlook equals the main 3-month risk check
    assert abs(out3["probability"] - main["probability"]) < 2e-3
    probs = [p["probability"] for p in out3["curve"]]
    assert probs == sorted(probs)                            # a loss within 3 months is also a loss within 6
    o9 = c.get("/businesses/SME-OUT/outlook?months=9").json()
    assert o9["months"] == 9 and o9["until"] == o9["curve"][8]["month"] and o9["probability"] == o9["curve"][8]["probability"]
    assert o9["reasons"] and all(r["feature"] != "horizon" for r in o9["reasons"] + o9["protective"])
    assert o9["evidence"] is None or "n" in o9["evidence"]
    for bad in (0, 13):
        assert c.get(f"/businesses/SME-OUT/outlook?months={bad}").status_code == 422
    # the choice is saved on the account
    assert c.put("/auth/settings", json={"outlook_months": 6}).json()["outlook_months"] == 6
    assert c.put("/auth/settings", json={"outlook_months": 13}).status_code == 422
    assert owner("SME-OUT2").get("/businesses/SME-OUT/outlook?months=3").status_code in (403, 404)
    assert c.put("/auth/settings", json={"language": "sw"}).status_code == 200
    sw = c.get("/businesses/SME-OUT/outlook?months=6").json()
    assert sw["probability"] == c.get("/businesses/SME-OUT/outlook?months=6").json()["probability"]
    c.put("/auth/settings", json={"language": "en"})
    # the chosen outlook is remembered after each change, and a rise of a band sends a warning
    from app import risk as _risk
    from app.database import SessionLocal
    from app.models import Business
    c.put("/auth/settings", json={"outlook_months": 6})
    with SessionLocal() as db:
        bid = db.query(Business).filter_by(code="SME-OUT").one().id
    _risk.refresh(bid)
    with SessionLocal() as db:
        b = db.get(Business, bid)
        assert b.outlook_for == 6 and b.outlook_band in ("Low", "Moderate", "High")
        now_band, b.outlook_band = b.outlook_band, "Low"
        db.commit()
    _risk.refresh(bid)
    acts = [a["action"] for a in admin.get("/admin/activity?target=SME-OUT").json()]
    assert ("alert.outlook" in acts) == (now_band != "Low")
    # the assistant answers "risk in the next N months"
    r = c.post("/assistant/ask", json={"message": "what is my risk in the next 9 months?"}).json()
    assert r["intent"] == "outlook" and "9 months ahead" in r["reply"]
    assert "1 to 12" in c.post("/assistant/ask", json={"message": "risk in the next 15 months"}).json()["reply"]
    admin.delete("/admin/synthetic")
