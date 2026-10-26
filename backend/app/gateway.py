import re
import json

from . import shamar

MINUTES_PER_ACTION = 4


class Forbidden(Exception):
    pass


class Refused(Exception):
    pass


def now(db):
    m = int(db.get("clock"))
    return f"{db.get('day')}T{m // 60:02d}:{m % 60:02d}"


def tick(db, minutes=MINUTES_PER_ACTION):
    db.set("clock", min(int(db.get("clock")) + minutes, 23 * 60 + 59))


def actor(db, actor_id):
    a = db.one("SELECT * FROM actors WHERE id=?", (actor_id,))
    if not a:
        raise Forbidden("Unknown user")
    return a


def require_owner(db, actor_id):
    a = actor(db, actor_id)
    if a["kind"] != "owner":
        raise Forbidden("Only the owner can do this")
    return a


def _supplier(db, sid):
    s = db.one("SELECT * FROM suppliers WHERE id=?", (sid,))
    if not s:
        raise Refused("Unknown supplier")
    return s


SYSTEM = {
    "answer_customer": "Email", "read_email": "Email", "export_customers": "Email", "summarise_email": "Email",
    "update_bank_details": "Supplier records", "prepare_payment": "Payments",
    "approve_payment": "Payments", "owner_decision": "Owner decision",
    "blocked_input": "Website", "failed_login": "Sign-in", "rate_limited": "Website",
    "create_discount": "Sales", "issue_refund": "Payments", "add_supplier": "Supplier records",
    "release_order": "Orders",
}


def act(db, actor_id, action, params, summary):
    """Run one action through Shamar. Returns a dict the UI can show."""
    a = actor(db, actor_id)
    tick(db)
    ts = now(db)

    if a["paused"]:
        eid = _log(db, ts, a, action, params, summary, {"score": 0, "level": "hold", "reasons": [
            {"kind": "Context", "text": f"{a['name']} is paused by the owner.", "points": 0}]}, "blocked")
        return {"event_id": eid, "level": "hold", "outcome": "blocked", "score": 0,
                "message": f"{a['name']} is paused. The owner must resume them first.", "reasons": []}

    verdict = shamar.check(db, a, action, params, ts).as_dict()
    level = verdict["level"]

    if action in ("prepare_payment", "release_order"):
        outcome = "held" if level != "clear" else "done"
    elif action in ("issue_refund", "create_discount") and level != "clear":
        outcome = "blocked"   # money leaving: anything unusual is stopped, not just flagged
    elif level == "hold":
        outcome = "blocked"
    elif level == "check":
        outcome = "flagged"
    else:
        outcome = "done"

    eid = _log(db, ts, a, action, params, summary, verdict, outcome)
    result = {"event_id": eid, "level": level, "outcome": outcome, "score": verdict["score"],
              "reasons": verdict["reasons"], "message": ""}

    # --- do the action (only if Shamar allows it) ---
    if action == "update_bank_details" and outcome != "blocked":
        sup = _supplier(db, params["supplier_id"])
        src = f"email:{params['source_email']}" if params.get("source_email") else "verified_contact"
        db.run("""UPDATE suppliers SET previous_account=bank_account, bank_account=?, bank_name=?,
                  bank_changed_at=?, bank_changed_by=?, bank_change_source=? WHERE id=?""",
               (params["new_account"], params.get("bank_name"), ts, a["id"], src, sup["id"]))
        result["message"] = "Saved." if outcome == "done" else "Saved, and Thandi has been asked to confirm it."

    if action == "prepare_payment":
        sup = _supplier(db, params["supplier_id"])
        pid = db.run("""INSERT INTO payments(ts, supplier_id, amount, bank_account, prepared_by, reference, status)
                        VALUES (?,?,?,?,?,?,?)""",
                     (ts, sup["id"], float(params["amount"]), sup["bank_account"], a["id"],
                      params.get("reference"), "held" if outcome == "held" else "awaiting_owner"))
        result["payment_id"] = pid
        result["message"] = ("Sent to Thandi for approval." if outcome == "done"
                             else "Held by Shamar. Thandi has to decide before it can be paid.")

    if action == "answer_customer" and outcome != "blocked":
        db.run("UPDATE customer_queries SET status='answered', reply=?, event_id=? WHERE id=?",
               (params["reply"], eid, params["query_id"]))

    if action in ("issue_refund", "create_discount"):
        if outcome == "blocked":
            paused = a["kind"] == "ai_agent" and level == "hold" and shamar.settings(db)["pause_ai"] == "1"
            if paused:
                db.run("UPDATE actors SET paused=1 WHERE id=?", (a["id"],))
            result["message"] = "Stopped. No money or discount was given." + (f" {a['name']} is paused." if paused else "")
            if params.get("query_id"):
                db.run("UPDATE customer_queries SET status='blocked', event_id=? WHERE id=?", (eid, params["query_id"]))

    if action == "release_order":
        result["message"] = (f"Order #{params.get('order')} released for collection." if outcome == "done"
                             else f"Held by Shamar. Don't hand over order #{params.get('order')} yet.")

    if action == "add_supplier" and outcome != "blocked":
        sid = re.sub(r"[^a-z0-9]+", "", params["name"].lower())[:16] or "supplier"
        while db.one("SELECT 1 x FROM suppliers WHERE id=?", (sid,)):
            sid += "x"
        src = ("claimed-owner:" if params.get("claims_owner") else "message:") + (params.get("source") or "manual")
        db.run("""INSERT INTO suppliers(id, name, bank_account, bank_name, verified_email, verified_phone, created_at,
                  created_by, bank_changed_at, bank_changed_by, bank_change_source) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
               (sid, params["name"], params["account"], params.get("bank_name"), "", None, ts, a["id"], ts, a["id"], src))
        result["supplier_id"] = sid
        params["supplier_id"] = sid
        db.run("UPDATE events SET params=? WHERE id=?", (json.dumps(params), eid))
        result["message"] = "Supplier added." if outcome == "done" else "Supplier added, and Thandi has been asked to confirm it."

    if action == "export_customers":
        if outcome == "blocked":
            paused = a["kind"] == "ai_agent" and shamar.settings(db)["pause_ai"] == "1"
            if paused:
                db.run("UPDATE actors SET paused=1 WHERE id=?", (a["id"],))
            result["message"] = "Stopped. No data left the business." + (f" {a['name']} is paused." if paused else "")
            if params.get("query_id"):
                db.run("UPDATE customer_queries SET status='blocked', event_id=? WHERE id=?", (eid, params["query_id"]))

    # --- tell the owner ---
    if level != "clear":
        same = None
        if action in shamar.LOW_RISK:  # one alert a day for busy-but-harmless work, not one per action
            same = db.one("""SELECT a.id FROM alerts a JOIN events e ON e.id = a.event_id
                             WHERE a.actor_id=? AND e.action=? AND a.status IN ('open','checking')
                             AND substr(a.ts,1,10)=?""", (a["id"], action, ts[:10]))
        result["alert_id"] = same["id"] if same else _alert(db, ts, a, action, params, verdict, eid, result.get("payment_id"))
        if result.get("payment_id"):
            db.run("UPDATE payments SET alert_id=? WHERE id=?", (result["alert_id"], result["payment_id"]))
    return result


def deny(db, actor_id, action, params, summary, why):
    """The permission check said no (before Shamar even scores it). Logged and shown to the owner."""
    a = actor(db, actor_id)
    tick(db)
    ts = now(db)
    verdict = {"score": 10.0, "level": "hold", "metric": None, "reasons": [
        {"kind": "Permission", "text": why, "points": 10.0}]}
    if params.get("trigger"):
        verdict["reasons"].append({"kind": "Context", "text": f"It started right after reading a message from {params['trigger']}.", "points": 0})
    eid = _log(db, ts, a, action, params, summary, verdict, "denied")
    paused = a["kind"] == "ai_agent" and shamar.settings(db)["pause_ai"] == "1"
    if paused:
        db.run("UPDATE actors SET paused=1 WHERE id=?", (a["id"],))
    if params.get("query_id"):
        db.run("UPDATE customer_queries SET status='blocked', event_id=? WHERE id=?", (eid, params["query_id"]))
    aid = db.run("""INSERT INTO alerts(ts, event_id, actor_id, level, score, title, line, reasons, metric)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                 (ts, eid, a["id"], "hold", 10.0, f"{a['name']} tried to do something she isn't allowed to",
                  "Nothing changed. Someone may be trying to trick the assistant.",
                  json.dumps(verdict["reasons"]), "null"))
    return {"event_id": eid, "alert_id": aid, "level": "hold", "outcome": "denied", "score": 10.0,
            "reasons": verdict["reasons"],
            "message": f"Not allowed. Nothing changed.{' ' + a['name'] + ' is paused.' if paused else ''}"}


def _log(db, ts, a, action, params, summary, verdict, outcome):
    return db.run("""INSERT INTO events(ts, actor_id, action, system, summary, params, score, level, outcome, reasons)
                     VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (ts, a["id"], action, SYSTEM.get(action, ""), summary, json.dumps(params),
                   verdict["score"], verdict["level"], outcome, json.dumps(verdict["reasons"])))


def _alert(db, ts, a, action, params, verdict, eid, payment_id):
    context = [r for r in verdict["reasons"] if r["kind"] == "Context"]
    sid = params.get("supplier_id")
    if action == "prepare_payment":
        sup = _supplier(db, sid)
        title = f"R{float(params['amount']):,.0f} to {sup['name']}"
        line = ("Every step was allowed. Together, they don't add up." if len(context) >= 2
                else f"This doesn't match {a['name']}'s normal pattern.")
    elif action == "update_bank_details":
        sup = _supplier(db, sid)
        title = f"{shamar.poss(sup['name'])} bank details changed"
        line = "Saved, but the request didn't come from the supplier's verified contact."
    elif action == "export_customers":
        title = f"{a['name']} tried to send {params.get('records')} customer records"
        line = ("An email told the AI to do it in hidden text. Stopped before any data left the business." if params.get("hidden")
                else "Stopped before any data left the business." if verdict["level"] == "hold" else "Sent, please confirm.")
    elif action == "create_discount":
        title = f"{a['name']} tried to give a {params.get('pct')}% discount"
        line = "A customer talked the assistant into it. Stopped before any code was issued."
    elif action == "issue_refund":
        title = f"{a['name']} tried to refund R{float(params.get('amount', 0)):,.0f}" + (" to a new account" if params.get("to_account") else "")
        line = "A customer talked the assistant into it. Stopped before any money left."
    elif action == "release_order":
        title = f"Order #{params.get('order')} (R{float(params.get('amount', 0)):,.0f}) about to be handed over unpaid"
        line = "The proof of payment looks real, but the money isn't in the bank."
    elif action == "add_supplier":
        title = f"New supplier {params.get('name')} added on someone else's request"
        line = "The request may not have come from who it claims."
    elif action == "answer_customer":
        title = f"{a['name']} is much busier than usual"
        line = "If it's just a busy day, tap Clear and Shamar will accept the extra work for today."
    else:
        title = f"Unusual activity from {a['name']}"
        line = f"This doesn't match {a['name']}'s normal pattern."
    return db.run("""INSERT INTO alerts(ts, event_id, actor_id, level, score, title, line, reasons, metric, payment_id, supplier_id)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                  (ts, eid, a["id"], verdict["level"], verdict["score"], title, line,
                   json.dumps(verdict["reasons"]), json.dumps(verdict["metric"]), payment_id, sid))


# ---------------- owner side ----------------

def decide(db, owner_id, alert_id, decision):
    require_owner(db, owner_id)
    al = db.one("SELECT * FROM alerts WHERE id=?", (alert_id,))
    if not al:
        raise Refused("Unknown alert")
    if decision not in ("clear", "check", "hold"):
        raise Refused("Decision must be clear, check or hold")
    note = ""
    pay = db.one("SELECT * FROM payments WHERE id=?", (al["payment_id"],)) if al["payment_id"] else None
    sup = db.one("SELECT * FROM suppliers WHERE id=?", (al["supplier_id"],)) if al["supplier_id"] else None

    if decision == "clear":
        status = "cleared"
        if pay and pay["status"] == "held":
            db.run("UPDATE payments SET status='awaiting_owner' WHERE id=?", (pay["id"],))
            note = "Released. You can approve the payment now."
        else:
            note = "Marked as fine."
        if sup and (sup["bank_change_source"] or "").startswith("email:"):
            db.run("UPDATE suppliers SET bank_change_source='owner_confirmed' WHERE id=?", (sup["id"],))
            note += f" {shamar.poss(sup['name'])} new bank details are now marked as confirmed by you."
        db.run("UPDATE actors SET paused=0 WHERE id=?", (al["actor_id"],))
    elif decision == "check":
        status = "checking"
        note = (f"Still held. Call {sup['name']} on {sup['verified_phone']} (the number on file, not one from an email)."
                if sup else "Marked to check. Nothing is released yet.")
    else:
        status = "held"
        parts = []
        if pay and pay["status"] in ("held", "awaiting_owner"):
            db.run("UPDATE payments SET status='blocked' WHERE id=?", (pay["id"],))
            parts.append("Payment cancelled.")
        if sup and sup["previous_account"] and (sup["bank_change_source"] or "").startswith("email:"):
            db.run("""UPDATE suppliers SET bank_account=previous_account, previous_account=NULL,
                      bank_changed_at=created_at, bank_change_source='restored' WHERE id=?""", (sup["id"],))
            parts.append(f"{shamar.poss(sup['name'])} bank details restored to the account on file.")
            # any other open alert about the same supplier change is now settled too
            db.run("UPDATE alerts SET status='held', note=? WHERE supplier_id=? AND status IN ('open','checking') AND id<>?",
                   ("Settled with the related alert.", sup["id"], alert_id))
        if db.one("SELECT kind FROM actors WHERE id=?", (al["actor_id"],))["kind"] == "ai_agent":
            db.run("UPDATE actors SET paused=1 WHERE id=?", (al["actor_id"],))
            parts.append("The AI assistant stays paused.")
        note = " ".join(parts) or "Blocked."
    db.run("UPDATE alerts SET status=?, note=? WHERE id=?", (status, note, alert_id))
    word = {"cleared": "Released", "checking": "Kept on hold to check", "held": "Blocked"}[status]
    audit(db, owner_id, "owner_decision", {"alert_id": alert_id, "supplier_id": al["supplier_id"],
                                            "payment_id": al["payment_id"]}, f"{word}: {al['title']}", "done")
    return {"status": status, "note": note}


def chain(db, al):
    """The real sequence of events behind an alert, from the audit log, oldest first."""
    steps = []
    evs = db.q("SELECT * FROM events WHERE history=0 ORDER BY id")
    sid = al["supplier_id"]
    if sid:
        related = [e for e in evs if isinstance(e["params"], dict) and e["params"].get("supplier_id") == sid]
        sources = {e["params"].get("source_email") for e in related if e["action"] == "update_bank_details"}
        sources |= {e["params"].get("source") for e in related if e["action"] == "add_supplier"}
        for m in db.q("SELECT * FROM inbox WHERE to_actor='sipho'"):
            if m["from_addr"] in sources:
                steps.append({"ts": m["ts"], "text": f"Message arrives from {m['from_addr']}: \u201c{m['subject']}\u201d", "tone": "check"})
                for e in evs:
                    if e["action"] == "read_email" and e["params"].get("email_id") == m["id"]:
                        steps.append({"ts": e["ts"], "text": f"{_name(db, e['actor_id'])} opens the email", "tone": "clear"})
        for e in related:
            steps.append({"ts": e["ts"], "text": f"{_name(db, e['actor_id'])}: {e['summary']}", "tone": _tone(e)})
            if e["id"] == al["event_id"] and e["outcome"] in ("held", "blocked", "flagged"):
                steps.append({"ts": e["ts"], "text": "Shamar connects these steps and " +
                              ("holds the payment" if e["action"] == "prepare_payment" else "flags it for the owner"), "tone": e["level"]})
    else:
        e = db.one("SELECT * FROM events WHERE id=?", (al["event_id"],))
        src = e["params"].get("source_email") if isinstance(e["params"], dict) else None
        if src:
            for m in db.q("SELECT * FROM inbox WHERE from_addr=?", (src,)):
                steps.append({"ts": m["ts"], "text": f"Message arrives from {m['from_addr']}: \u201c{m['subject']}\u201d", "tone": "check"})
        mail = db.one("SELECT * FROM inbox WHERE id=?", (e["params"].get("email_id"),)) if e["params"].get("task") == "summarise_email" else None
        if mail:
            steps.append({"ts": mail["ts"], "text": f"Email arrives from {mail['from_addr']}: \u201c{mail['subject']}\u201d", "tone": "check"})
            if e["params"].get("hidden"):
                steps.append({"ts": mail["ts"], "text": "Hidden inside it, in invisible text: an instruction for the AI", "tone": "hold"})
            steps.append({"ts": e["ts"], "text": "Sipho asks Lindi to summarise the email", "tone": "clear"})
        q = db.one("SELECT * FROM customer_queries WHERE event_id=?", (e["id"],))
        if q:
            steps.append({"ts": e["ts"], "text": f"Message from {q['email']}: \u201c{q['text'][:90]}{'…' if len(q['text']) > 90 else ''}\u201d", "tone": "check"})
        steps.append({"ts": e["ts"], "text": f"{_name(db, e['actor_id'])}: {e['summary']}", "tone": _tone(e)})
        steps.append({"ts": e["ts"], "text": ("Shamar holds the order: the money isn't in the bank" if e["action"] == "release_order" else
                                              "Stopped before it happened. " + ("Lindi is paused." if e["actor_id"] == "lindi" else "")), "tone": "hold"})
    steps.sort(key=lambda s: s["ts"])
    for s in steps:
        s["time"] = s.pop("ts")[11:16]
    return steps


def _name(db, actor_id):
    return actor(db, actor_id)["name"]


def _tone(e):
    if e["outcome"] in ("held", "blocked", "denied", "refused"):
        return "hold"
    return "check" if e["outcome"] == "flagged" else "clear"


def audit(db, actor_id, action, params, summary, outcome, why=None):
    """Write a non-Shamar event (approvals, refusals, owner decisions) to the audit log."""
    a = actor(db, actor_id)
    tick(db, 1)
    reasons = [{"kind": "Permission", "text": why, "points": 0}] if why else []
    return _log(db, now(db), a, action, params, summary,
                {"score": 0, "level": "hold" if outcome in ("refused", "denied") else "clear", "reasons": reasons}, outcome)


def approve_payment(db, user_id, payment_id):
    p = db.one("SELECT * FROM payments WHERE id=?", (payment_id,))
    if not p:
        raise Refused("Unknown payment")
    sup = _supplier(db, p["supplier_id"])
    what = f"R{p['amount']:,.0f} to {sup['name']}"
    params = {"payment_id": payment_id, "supplier_id": sup["id"]}
    if actor(db, user_id)["kind"] != "owner":
        audit(db, user_id, "approve_payment", params, f"Tried to approve {what}", "denied", "Only the owner can approve payments.")
        raise Forbidden("Only the owner can approve payments")
    why = {"held": "Refused: Shamar is holding this payment. Decide on the alert first.",
           "blocked": "Refused: this payment was blocked.", "paid": "Already paid."}.get(p["status"])
    if why:
        audit(db, user_id, "approve_payment", params, f"Tried to approve {what}", "refused", why)
        raise Refused(why)
    db.run("UPDATE payments SET status='paid' WHERE id=?", (payment_id,))
    audit(db, user_id, "approve_payment", params, f"Approved {what}", "done")
    return {"status": "paid"}


def resume(db, owner_id, actor_id):
    require_owner(db, owner_id)
    db.run("UPDATE actors SET paused=0 WHERE id=?", (actor_id,))
    return {"ok": True}
