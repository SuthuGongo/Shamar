import json
import re
import time

from . import gateway

ATTACKS = [
    ("script injection (XSS)", re.compile(r"<\s*/?\s*script|<\s*iframe|<\s*img[^>]*\son\w+\s*=|\son(error|load|click|mouseover)\s*=|javascript\s*:", re.I)),
    ("SQL injection", re.compile(r"('|\")\s*(or|and)\s+('?\w*'?\s*=\s*'?\w*|\d+\s*=\s*\d+)|\bunion\s+(all\s+)?select\b|;\s*(drop|delete|update|insert)\s|\bor\s+1\s*=\s*1\b|'\s*--", re.I)),
    ("NoSQL injection", re.compile(r"\$(ne|gt|gte|lt|lte|where|regex|or|and|in|nin|exists)\b", re.I)),
]

FAIL_LIMIT, FAIL_WINDOW, LOCK_SECONDS = 5, 10 * 60, 15 * 60
CHAT_LIMIT, CHAT_WINDOW = 15, 5 * 60


def detect(*texts):
    """Returns (attack type, the matching piece) if any text looks like an injection attempt."""
    for t in texts:
        for name, rx in ATTACKS:
            m = rx.search(t or "")
            if m:
                return name, m.group(0)[:40]
    return None


def _recent(db, key, window):
    try:
        stamps = json.loads(db.get(key, "[]"))
    except ValueError:
        stamps = []
    now = time.time()
    return [s for s in stamps if now - s < window], now


def _alert_once(db, actor_id, title, line, reasons, event_id):
    """One alert per attack type per day, so an attacker can't flood the owner."""
    today = gateway.now(db)[:10]
    if db.one("SELECT 1 x FROM alerts WHERE title=? AND status IN ('open','checking') AND substr(ts,1,10)=?", (title, today)):
        return
    db.run("""INSERT INTO alerts(ts, event_id, actor_id, level, score, title, line, reasons, metric)
              VALUES (?,?,?,?,?,?,?,?,?)""",
           (gateway.now(db), event_id, actor_id, "hold", 10.0, title, line, json.dumps(reasons), "null"))


def block_input(db, where, sender, kind, piece):
    """Log and alert a blocked injection attempt from the website."""
    reasons = [{"kind": "Context", "text": f"The {where} contained {kind} code: “{piece}”.", "points": 10.0},
               {"kind": "Context", "text": f"Sent by {sender}. It was blocked before it was saved, shown or run.", "points": 0}]
    eid = gateway.audit(db, "visitor", "blocked_input", {"where": where, "sender": sender, "attack": kind},
                        f"Blocked {kind} in the {where} from {sender}", "blocked", f"{kind} detected")
    db.run("UPDATE events SET reasons=? WHERE id=?", (json.dumps(reasons), eid))
    _alert_once(db, "visitor", f"Blocked a {kind} attempt", f"Someone tried to inject code through the {where}. Nothing was saved or run.", reasons, eid)


def login_locked(db, email):
    until = float(db.get(f"lock:{email.lower()}", "0") or 0)
    return until > time.time()


def login_failed(db, email):
    """Count a failed sign-in. Returns True if the account is now locked."""
    key = f"fail:{email.lower()}"
    stamps, now = _recent(db, key, FAIL_WINDOW)
    stamps.append(now)
    db.set(key, json.dumps(stamps))
    if len(stamps) < FAIL_LIMIT:
        return False
    db.set(f"lock:{email.lower()}", now + LOCK_SECONDS)
    db.set(key, "[]")
    user = db.one("SELECT id, name FROM actors WHERE lower(email)=lower(?)", (email,))
    who = user["id"] if user else "visitor"
    name = f"{gateway.actor(db, who)['name']}'s account" if user else f"the unknown account {email}"
    reasons = [{"kind": "Behaviour", "text": f"{FAIL_LIMIT} wrong passwords for {email} within {FAIL_WINDOW // 60} minutes.", "points": 6.0},
               {"kind": "Context", "text": f"The account is locked for {LOCK_SECONDS // 60} minutes. Clearing this alert unlocks it.", "points": 0}]
    eid = gateway.audit(db, who, "failed_login", {"email": email}, f"{FAIL_LIMIT} failed sign-ins on {name}; account locked",
                        "refused", "Too many wrong passwords")
    db.run("UPDATE events SET reasons=? WHERE id=?", (json.dumps(reasons), eid))
    _alert_once(db, who, f"{FAIL_LIMIT} failed sign-ins on {name}",
                "Someone may be guessing the password. Shamar locked the account.", reasons, eid)
    return True


def login_ok(db, email):
    db.set(f"fail:{email.lower()}", "[]")


def unlock(db, actor_id):
    u = db.one("SELECT email FROM actors WHERE id=?", (actor_id,))
    if u and u["email"]:
        db.set(f"lock:{u['email'].lower()}", "0")


def chat_flood(db, email):
    """Returns True if this sender has sent too many messages too fast."""
    key = f"rl:{email.lower()}"
    stamps, now = _recent(db, key, CHAT_WINDOW)
    if len(stamps) >= CHAT_LIMIT:
        reasons = [{"kind": "Behaviour", "text": f"More than {CHAT_LIMIT} messages in {CHAT_WINDOW // 60} minutes from {email}.", "points": 6.0},
                   {"kind": "Context", "text": "Further messages are refused for a few minutes. This is how spam bots behave.", "points": 0}]
        eid = gateway.audit(db, "visitor", "rate_limited", {"sender": email}, f"Refused message flood from {email}",
                            "refused", "Too many messages")
        db.run("UPDATE events SET reasons=? WHERE id=?", (json.dumps(reasons), eid))
        _alert_once(db, "visitor", "Blocked a message flood", "Someone sent messages faster than a person can type.", reasons, eid)
        return True
    stamps.append(now)
    db.set(key, json.dumps(stamps))
    return False
