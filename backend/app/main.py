import json
import os
import re
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, gateway, lindi, morning, security, seed, shamar
from .db import DB

db = DB()
app = FastAPI(title="Shamar", description="Guard what matters", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    res = await call_next(request)
    res.headers["X-Content-Type-Options"] = "nosniff"
    res.headers["X-Frame-Options"] = "DENY"
    res.headers["Referrer-Policy"] = "no-referrer"
    res.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    res.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
    if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        res.headers["Strict-Transport-Security"] = "max-age=31536000"
    return res


def fresh():
    seed.seed(db)
    shamar.reset_cache()
    morning.run(db)


if not db.one("SELECT 1 x FROM actors LIMIT 1") or db.get("day") != seed.demo_day().isoformat():
    fresh()


def run(fn, *args):
    try:
        return fn(*args)
    except gateway.Forbidden as e:
        raise HTTPException(403, str(e))
    except gateway.Refused as e:
        raise HTTPException(409, str(e))


def mask(acc):
    return "••" + acc[-4:] if acc else ""


# ---------- login ----------

def current_user(authorization: str = Header(default="")):
    """Every staff route uses this. 401 if there is no valid token."""
    token = authorization.removeprefix("Bearer ").strip()
    uid = auth.read_token(token)
    user = db.one("SELECT id, name, role, kind FROM actors WHERE id=?", (uid,)) if uid else None
    if not user:
        raise HTTPException(401, "Please log in")
    return user


def owner_only(user=Depends(current_user)):
    if user["kind"] != "owner":
        raise HTTPException(403, "Only the owner can do this")
    return user


class Login(BaseModel):
    email: str = Field(max_length=120)
    password: str = Field(max_length=120)


@app.post("/api/login")
def login(body: Login):
    email = body.email.strip()
    hit = security.detect(email)
    if hit:
        security.block_input(db, "sign-in form", "an unknown visitor", *hit)
        raise HTTPException(401, "Wrong email or password")
    if security.login_locked(db, email):
        raise HTTPException(429, "Too many failed sign-ins. This account is locked for 15 minutes.")
    u = db.one("SELECT * FROM actors WHERE lower(email)=lower(?)", (email,))
    if not u or not auth.check_password(body.password, u["password_hash"]):
        if security.login_failed(db, email):
            raise HTTPException(429, "Too many failed sign-ins. This account is locked for 15 minutes.")
        raise HTTPException(401, "Wrong email or password")
    security.login_ok(db, email)
    return {"token": auth.make_token(u["id"]),
            "user": {"id": u["id"], "name": u["name"], "role": u["role"], "kind": u["kind"]}}


@app.get("/api/demo-accounts")
def demo_accounts():
    return {"password": auth.DEMO_PASSWORD, "accounts": [
        {"id": "thandi", "who": "Thandi (owner)", "email": auth.DEMO_ACCOUNTS["thandi"]},
        {"id": "sipho", "who": "Sipho (store admin)", "email": auth.DEMO_ACCOUNTS["sipho"]}]}


# ---------- read everything a staff screen needs ----------

@app.get("/api/state")
def state(user=Depends(current_user)):
    day = db.get("day")
    actors = {a["id"]: a for a in db.q("SELECT id, name, role, kind, paused FROM actors")}
    suppliers = db.q("SELECT * FROM suppliers ORDER BY name")
    sup_name = {s["id"]: s["name"] for s in suppliers}
    events = db.q("SELECT * FROM events WHERE history=0 ORDER BY id DESC")
    for e in events:
        e["actor"] = actors[e["actor_id"]]["name"]
        e["time"] = e["ts"][11:16]
    payments = db.q("SELECT * FROM payments WHERE history=0 ORDER BY id DESC")
    for p in payments:
        p["supplier"] = sup_name[p["supplier_id"]]
        p["account"] = mask(p["bank_account"])
        p["by"] = actors[p["prepared_by"]]["name"]
        p.pop("bank_account", None)
    alerts = db.q("SELECT * FROM alerts ORDER BY id DESC")
    sup_by_id = {s["id"]: s for s in suppliers}
    for a in alerts:
        a["actor"] = actors[a["actor_id"]]["name"]
        a["actor_kind"] = actors[a["actor_id"]]["kind"]
        a["time"] = a["ts"][11:16]
        a["chain"] = gateway.chain(db, a)
        sup = sup_by_id.get(a["supplier_id"])
        ev_action = db.one("SELECT action FROM events WHERE id=?", (a["event_id"],))["action"]
        if sup and (sup.get("bank_change_source") or "").startswith("claimed-owner:"):
            a["next_step"] = ("You didn't send this request. Don't pay it. Tell your staff that payment requests "
                              "must be confirmed with you on your usual number.")
            continue
        a["next_step"] = (f"Call {sup['name']} on {sup['verified_phone']} (the number you already had for them, "
                          "not one from an email) and ask them to confirm their bank account.") if sup else (
                          "If it was the real person, clear it to unlock the account. If not, block it and change the password."
                          if ev_action == "failed_login" else
                          "Nothing to do. Shamar blocked it. Keep an eye out if it happens again." if ev_action in ("blocked_input", "rate_limited") else
                          "Check your banking app, not the screenshot. Only hand over the goods once the money shows in your account." if ev_action == "release_order" else
                          "Read the message that triggered this. If it was a trick, keep the assistant paused.")
    for s in suppliers:
        s["account"] = mask(s["bank_account"])
        s["changed_today"] = bool(s["bank_changed_at"] and s["bank_changed_at"][:10] == day
                                  and s["bank_changed_at"] != s["created_at"])
        for k in ("bank_account", "previous_account"):
            s.pop(k, None)
    check_at, hold_at = shamar.SENSITIVITY[shamar.settings(db)["sensitivity"]]
    return {
        "me": user,
        "day": day,
        "thresholds": {"check": check_at, "hold": hold_at},
        "clock": gateway.now(db)[11:16],
        "actors": list(actors.values()),
        "suppliers": suppliers,
        "inbox": [{**m, "body": lindi.split_hidden(m["body"])[0]}
                  for m in db.q("SELECT * FROM inbox WHERE to_actor='sipho' ORDER BY ts DESC, id DESC")],
        "queries": db.q("SELECT * FROM customer_queries ORDER BY id"),
        "events": events,
        "payments": payments,
        "alerts": alerts,
        "counts": {
            "checked": len(events),
            "through": sum(1 for e in events if e["outcome"] == "done"),
            "stopped": sum(1 for e in events if e["outcome"] in ("held", "blocked", "flagged", "denied", "refused")),
            "saved": sum(p["amount"] for p in payments if p["status"] == "blocked"),
        },
    }


# ---------- customers (public) ----------

class Ask(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    text: str = Field(min_length=1, max_length=1000)


@app.post("/api/shop/ask")
def shop_ask(body: Ask):
    hit = security.detect(body.name, body.text)
    if hit:
        security.block_input(db, "shop chat", body.email.strip(), *hit)
        raise HTTPException(400, "Sorry, that message couldn't be sent.")
    if security.chat_flood(db, body.email.strip()):
        raise HTTPException(429, "You're sending messages too quickly. Please wait a few minutes.")
    qid = db.run("INSERT INTO customer_queries(customer, email, text) VALUES (?,?,?)",
                 (body.name.strip(), body.email.strip(), body.text.strip()))
    q = db.one("SELECT * FROM customer_queries WHERE id=?", (qid,))
    return run(lindi.answer, db, q)


@app.get("/api/shop/chat")
def shop_chat(email: str):
    rows = db.q("""SELECT id, customer, text, status, reply FROM customer_queries
                   WHERE lower(email)=lower(?) ORDER BY id""", (email,))
    paused = db.one("SELECT paused FROM actors WHERE id='lindi'")["paused"]
    return {"messages": rows, "lindi_paused": bool(paused)}


BANKS = r"(Capitec(?: Business)?|FNB|First National Bank|Absa|Standard Bank|Nedbank|TymeBank|Discovery Bank|African Bank|Investec)"


class ShopEmail(BaseModel):
    from_name: str = Field(min_length=1, max_length=80)
    from_addr: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    subject: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=3000)


def read_ask(text):
    """Work out if an email asks to change a supplier's bank details (like a person reading it would)."""
    t = text.lower()
    acc = re.search(r"\b\d{8,13}\b", text)
    if not (acc and re.search(r"\b(bank|banking|account)\b", t)):
        return {"type": "none"}
    for s in db.q("SELECT id, name FROM suppliers"):
        if s["name"].lower().split()[0] in t:
            bank = re.search(BANKS, text, re.I)
            return {"type": "bank_change", "supplier_id": s["id"], "new_account": acc.group(0),
                    "bank_name": bank.group(0) if bank else "New bank"}
    return {"type": "none"}


@app.post("/api/shop/email")
def shop_email(body: ShopEmail):
    hit = security.detect(body.from_name, body.subject, body.body)
    if hit:
        security.block_input(db, "contact form", body.from_addr.strip(), *hit)
        raise HTTPException(400, "Sorry, that message couldn't be sent.")
    ask = read_ask(body.subject + "\n" + body.body)
    gateway.tick(db, 1)
    db.run("""INSERT INTO inbox(to_actor, ts, from_name, from_addr, subject, body, ask, sent_by_visitor)
              VALUES ('sipho',?,?,?,?,?,?,1)""",
           (gateway.now(db), body.from_name.strip(), body.from_addr.strip(), body.subject.strip(),
            body.body, json.dumps(ask)))
    return {"delivered": True, "asks_for_bank_change": ask["type"] == "bank_change",
            "message": "Delivered to Sipho's inbox."}


# ---------- staff / AI actions (all go through Shamar) ----------

class BankChange(BaseModel):
    new_account: str = Field(min_length=6, max_length=16, pattern=r"^\d+$")
    bank_name: str = Field(min_length=2, max_length=40)
    source_email_id: int | None = None


class NewPayment(BaseModel):
    supplier_id: str = Field(max_length=40)
    amount: float = Field(gt=0, le=1_000_000)
    reference: str = Field(default="", max_length=40)


@app.post("/api/lindi/next")
def lindi_next(user=Depends(current_user)):
    return run(lindi.answer_next, db)


@app.post("/api/inbox/{email_id}/read")
def read_email(email_id: int, user=Depends(current_user)):
    e = db.one("SELECT * FROM inbox WHERE id=?", (email_id,))
    if not e:
        raise HTTPException(404, "Email not found")
    return run(gateway.act, db, user["id"], "read_email", {"email_id": email_id}, f"Read “{e['subject']}”")


@app.post("/api/inbox/{email_id}/summarise")
def summarise_email(email_id: int, user=Depends(current_user)):
    e = db.one("SELECT * FROM inbox WHERE id=?", (email_id,))
    if not e:
        raise HTTPException(404, "Email not found")
    return run(lindi.summarise, db, e)


@app.post("/api/suppliers/{supplier_id}/bank")
def change_bank(supplier_id: str, body: BankChange, user=Depends(current_user)):
    sup = db.one("SELECT * FROM suppliers WHERE id=?", (supplier_id,))
    if not sup:
        raise HTTPException(404, "Supplier not found")
    source = None
    if body.source_email_id:
        mail = db.one("SELECT * FROM inbox WHERE id=?", (body.source_email_id,))
        source = mail["from_addr"] if mail else None
        db.run("UPDATE inbox SET done=1 WHERE id=?", (body.source_email_id,))
    params = {"supplier_id": supplier_id, "new_account": body.new_account, "bank_name": body.bank_name,
              "source_email": source}
    return run(gateway.act, db, user["id"], "update_bank_details", params,
               f"Changed {shamar.poss(sup['name'])} bank account to {mask(body.new_account)}")


class NewSupplierPay(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    bank_name: str = Field(min_length=2, max_length=40)
    account: str = Field(min_length=6, max_length=16, pattern=r"^\d+$")
    amount: float = Field(gt=0, le=1_000_000)
    source_email_id: int | None = None


@app.post("/api/suppliers/new-and-pay")
def new_supplier_and_pay(body: NewSupplierPay, user=Depends(current_user)):
    mail = db.one("SELECT * FROM inbox WHERE id=?", (body.source_email_id,)) if body.source_email_id else None
    owner = db.one("SELECT name FROM actors WHERE kind='owner'")
    params = {"name": body.name.strip(), "account": body.account, "bank_name": body.bank_name.strip(),
              "source": mail["from_addr"] if mail else None,
              "claims_owner": bool(mail and owner and mail["from_name"].strip().lower() == owner["name"].lower()),
              "message": (mail["body"] if mail else "")}
    if mail:
        db.run("UPDATE inbox SET done=1 WHERE id=?", (mail["id"],))
    r1 = run(gateway.act, db, user["id"], "add_supplier", params, f"Added new supplier {params['name']}")
    if r1["outcome"] == "blocked":
        return {"supplier": r1, "payment": None}
    r2 = run(gateway.act, db, user["id"], "prepare_payment",
             {"supplier_id": r1["supplier_id"], "amount": body.amount, "reference": "Requested by message"},
             f"Prepared R{body.amount:,.0f} to {params['name']}")
    return {"supplier": r1, "payment": r2}


@app.post("/api/orders/release")
def release_order(body: dict, user=Depends(current_user)):
    mail = db.one("SELECT * FROM inbox WHERE id=?", (int(body.get("email_id", 0)),))
    if not mail or not isinstance(mail["ask"], dict) or mail["ask"].get("type") != "pop_release":
        raise HTTPException(404, "No order to release in that email")
    ask = mail["ask"]
    db.run("UPDATE inbox SET done=1 WHERE id=?", (mail["id"],))
    return run(gateway.act, db, user["id"], "release_order",
               {"order": ask["order"], "amount": ask["amount"], "buyer": ask["buyer"], "message": mail["body"],
                "source_email": mail["from_addr"]},
               f"Released order #{ask['order']} (R{ask['amount']:,.0f}) on proof of payment")


@app.post("/api/payments")
def new_payment(body: NewPayment, user=Depends(current_user)):
    sup = db.one("SELECT * FROM suppliers WHERE id=?", (body.supplier_id,))
    if not sup:
        raise HTTPException(404, "Supplier not found")
    return run(gateway.act, db, user["id"], "prepare_payment", body.model_dump(),
               f"Prepared R{body.amount:,.0f} to {sup['name']}")


# ---------- owner only ----------

class Decision(BaseModel):
    decision: str = Field(pattern="^(clear|check|hold)$")


class Settings(BaseModel):
    sensitivity: str = Field(pattern="^(relaxed|balanced|strict)$")
    payment_limit: int = Field(ge=0, le=10_000_000)
    pause_ai: bool


@app.get("/api/settings")
def get_settings(user=Depends(owner_only)):
    cfg = shamar.settings(db)
    check_at, hold_at = shamar.SENSITIVITY[cfg["sensitivity"]]
    return {"sensitivity": cfg["sensitivity"], "payment_limit": int(float(cfg["payment_limit"])),
            "pause_ai": cfg["pause_ai"] == "1", "check_at": check_at, "hold_at": hold_at}


@app.put("/api/settings")
def put_settings(body: Settings, user=Depends(owner_only)):
    db.set("sensitivity", body.sensitivity)
    db.set("payment_limit", body.payment_limit)
    db.set("pause_ai", "1" if body.pause_ai else "0")
    gateway.audit(db, user["id"], "owner_decision", {}, f"Changed settings: {body.sensitivity}, payment limit "
                  f"R{body.payment_limit:,}, pause AI on hold {'on' if body.pause_ai else 'off'}", "done")
    return get_settings(user)


@app.get("/api/profiles")
def profiles(user=Depends(owner_only)):
    return shamar.profiles(db, db.get("day"))


@app.post("/api/alerts/{alert_id}/decision")
def decide(alert_id: int, body: Decision, user=Depends(owner_only)):
    res = run(gateway.decide, db, user["id"], alert_id, body.decision)
    al = db.one("SELECT a.actor_id, e.action FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.id=?", (alert_id,))
    if al and al["action"] == "failed_login" and body.decision == "clear":
        security.unlock(db, al["actor_id"])
        res["note"] = "Cleared. The account is unlocked."
        db.run("UPDATE alerts SET note=? WHERE id=?", (res["note"], alert_id))
    return res


@app.post("/api/payments/{payment_id}/approve")
def approve(payment_id: int, user=Depends(current_user)):
    return run(gateway.approve_payment, db, user["id"], payment_id)  # role and hold are checked inside, and logged


@app.post("/api/actors/{actor_id}/resume")
def resume(actor_id: str, user=Depends(owner_only)):
    return run(gateway.resume, db, user["id"], actor_id)


@app.post("/api/reset")
def reset():
    """Puts the demo back to 08:00 so the next judge starts fresh."""
    fresh()
    return {"ok": True}


# ---------- serve the React app ----------
DIST = Path(os.environ.get("SHAMAR_WEB", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
