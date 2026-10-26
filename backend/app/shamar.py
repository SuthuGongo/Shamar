import re
from datetime import date
from difflib import SequenceMatcher
from statistics import median

CHECK_AT = 3.5
HOLD_AT = 6.0

SENSITIVITY = {"relaxed": (4.5, 7.0), "balanced": (3.5, 6.0), "strict": (2.5, 5.0)}
DEFAULTS = {"sensitivity": "balanced", "payment_limit": "50000", "pause_ai": "1"}


def settings(db):
    return {k: db.get(k, v) for k, v in DEFAULTS.items()}

# Busy-but-harmless work can raise a Check, never a Hold on volume alone.
LOW_RISK = {"answer_customer", "read_email", "summarise_email"}

ACTION_LABEL = {
    "answer_customer": "customer emails answered",
    "read_email": "emails read",
    "prepare_payment": "payments prepared",
    "update_bank_details": "bank detail changes",
    "export_customers": "customer exports",
    "summarise_email": "email summaries",
    "create_discount": "discount codes",
    "issue_refund": "refunds",
    "add_supplier": "new suppliers added",
    "release_order": "orders released",
}

URGENT = re.compile(r"\b(urgent|urgently|right now|immediately|asap|today|don'?t call|do not call|quickly|confidential|keep (this|it) (quiet|between us))\b", re.I)

_cache = {}


def reset_cache():
    _cache.clear()


def robust_z(x, med, mad, floor=1.0):
    return 0.6745 * (x - med) / max(mad, floor)


def _percentile(values, p):
    v = sorted(values)
    if not v:
        return 0
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def daily_baseline(db, actor_id, action):
    """Median, MAD and usual range of how many times a day this actor does this action."""
    key = ("daily", actor_id, action)
    if key not in _cache:
        days = [r["d"] for r in db.q("SELECT DISTINCT substr(ts,1,10) d FROM events WHERE history=1")]
        counts = {d: 0 for d in days}
        for r in db.q("""SELECT substr(ts,1,10) d, COUNT(*) n FROM events
                         WHERE history=1 AND actor_id=? AND action=? GROUP BY d""", (actor_id, action)):
            counts[r["d"]] = r["n"]
        vals = list(counts.values()) or [0]
        med = median(vals)
        mad = median([abs(v - med) for v in vals])
        _cache[key] = {"median": med, "mad": mad, "lo": round(_percentile(vals, 0.05)),
                       "hi": round(_percentile(vals, 0.95)), "total": sum(vals)}
    return _cache[key]


def amount_baseline(db, supplier_id):
    key = ("amount", supplier_id)
    if key not in _cache:
        vals = [r["amount"] for r in db.q("SELECT amount FROM payments WHERE history=1 AND supplier_id=?", (supplier_id,))]
        if not vals:
            _cache[key] = None
        else:
            med = median(vals)
            _cache[key] = {"median": med, "mad": median([abs(v - med) for v in vals]),
                           "lo": _percentile(vals, 0.05), "hi": _percentile(vals, 0.95), "n": len(vals)}
    return _cache[key]


def supplier_forecast(db, supplier_id):
    """Predict the next payment to a supplier from the rhythm of past payments."""
    key = ("forecast", supplier_id)
    if key not in _cache:
        rows = db.q("SELECT ts, amount FROM payments WHERE history=1 AND supplier_id=? ORDER BY ts", (supplier_id,))
        if len(rows) < 3:
            _cache[key] = None
        else:
            dates = [date.fromisoformat(r["ts"][:10]) for r in rows]
            gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
            every = median(gaps) if gaps else 7
            from datetime import timedelta
            _cache[key] = {"every_days": round(every, 1), "last": dates[-1].isoformat(),
                           "next": (dates[-1] + timedelta(days=round(every))).isoformat(),
                           "amount": round(median([r["amount"] for r in rows]), -1)}
    return _cache[key]


def _param_list(db, actor_id, action):
    out = []
    for r in db.q("SELECT params FROM events WHERE history=1 AND actor_id=? AND action=?", (actor_id, action)):
        if isinstance(r["params"], dict):
            out.append(r["params"])
    return out


def poss(name):
    return name + ("'" if name.endswith("s") else "'s")


def _domain(addr):
    return (addr or "").split("@")[-1].lower()


def _days_between(a_iso, b_iso):
    return (date.fromisoformat(b_iso[:10]) - date.fromisoformat(a_iso[:10])).days


class Verdict:
    def __init__(self, check_at=CHECK_AT, hold_at=HOLD_AT):
        self.check_at, self.hold_at = check_at, hold_at
        self.reasons = []   # {"kind": "Behaviour"|"Context", "text": str, "points": float}
        self.metric = None  # data for the "usually vs now" bar

    def add(self, kind, text, points):
        self.reasons.append({"kind": kind, "text": text, "points": round(points, 1)})

    @property
    def score(self):
        return round(min(10.0, sum(r["points"] for r in self.reasons)), 1)

    @property
    def level(self):
        s = self.score
        return "hold" if s >= self.hold_at else "check" if s >= self.check_at else "clear"

    def as_dict(self):
        return {"score": self.score, "level": self.level, "reasons": self.reasons, "metric": self.metric,
                "check_at": self.check_at, "hold_at": self.hold_at}


def check(db, actor, action, params, now):
    """Run Watch + Connect for one action. Returns a Verdict. Never changes data."""
    cfg = settings(db)
    v = Verdict(*SENSITIVITY.get(cfg["sensitivity"], SENSITIVITY["balanced"]))
    today = now[:10]
    staff_accounts = {r["salary_account"] for r in db.q("SELECT salary_account FROM actors WHERE salary_account IS NOT NULL")}

    # ---------- 1. WATCH: is this normal for this actor? ----------
    if actor["kind"] != "owner":
        base = daily_baseline(db, actor["id"], action)
        done_today = db.one("""SELECT COUNT(*) n FROM events WHERE history=0 AND actor_id=? AND action=?
                               AND substr(ts,1,10)=?""", (actor["id"], action, today))["n"] + 1
        label = ACTION_LABEL.get(action, action.replace("_", " "))
        if base["total"] == 0:
            v.add("Behaviour", f"{actor['name']} has never done this before ({label}).", 4.0)
        else:
            z = robust_z(done_today, base["median"], base["mad"])
            owner_ok = db.one("""SELECT 1 x FROM alerts a JOIN events e ON e.id = a.event_id
                                 WHERE a.actor_id=? AND e.action=? AND a.status='cleared'
                                 AND substr(a.ts,1,10)=?""", (actor["id"], action, today))
            if z >= CHECK_AT and not owner_ok:
                cap = 4.0 if action in LOW_RISK else 8.0
                v.add("Behaviour", f"{done_today} {label} today. {actor['name']} usually does "
                                   f"{base['lo']}–{base['hi']} a day.", min(z, cap))
            v.metric = {"label": f"{label.capitalize()} per day", "lo": base["lo"], "hi": base["hi"],
                        "today": done_today, "unit": ""}

    # ---------- 2. CONNECT: does it fit with what happened before? ----------
    if action == "update_bank_details":
        sup = db.one("SELECT * FROM suppliers WHERE id=?", (params["supplier_id"],))
        src = params.get("source_email")
        if src:
            if _domain(src) != _domain(sup["verified_email"]):
                v.add("Context", f"The request came from {src}. The address on file is {sup['verified_email']}.", 4.0)
                if SequenceMatcher(None, _domain(src), _domain(sup["verified_email"])).ratio() > 0.75:
                    v.add("Context", "That address looks almost the same as the real one, a common trick.", 1.0)
        if params["new_account"] in staff_accounts:
            v.add("Context", "The new account belongs to a staff member.", 6.0)

    if action == "prepare_payment":
        sup = db.one("SELECT * FROM suppliers WHERE id=?", (params["supplier_id"],))
        amt = float(params["amount"])
        if sup["bank_changed_at"] and sup["bank_changed_at"] != sup["created_at"]:
            ago = _days_between(sup["bank_changed_at"], now)
            if ago <= 14:
                when = "earlier today" if ago == 0 else f"{ago} days ago"
                v.add("Context", f"{poss(sup['name'])} bank details were changed {when}.", 3.5)
                if (sup["bank_change_source"] or "").startswith("email:"):
                    v.add("Context", "That change was asked for by email, not confirmed with the supplier's verified contact.", 3.0)
                if sup["bank_changed_by"] == actor["id"]:
                    v.add("Context", f"{actor['name']} changed the details and is now paying the same account.", 1.5)
            elif (sup["bank_change_source"] or "").startswith("email:"):
                v.add("Context", f"{poss(sup['name'])} bank details were changed by email {ago} days ago "
                                 "and nobody has confirmed them with the supplier.", 4.0)
        if sup["created_at"][:10] == today:
            v.add("Context", f"{sup['name']} was only added as a supplier today.", 4.0)
            if sup["created_by"] == actor["id"]:
                v.add("Context", f"{actor['name']} added this supplier and is now paying them.", 2.0)
            if (sup["bank_change_source"] or "").startswith("claimed-owner:"):
                v.add("Context", "The request to pay came from someone claiming to be the owner on a number she doesn't use.", 3.0)
        if sup["bank_account"] in staff_accounts:
            v.add("Context", "The payment goes to an account that belongs to a staff member.", 6.0)
        limit = float(cfg["payment_limit"] or 0)
        if limit and amt > limit:
            v.add("Context", f"R{amt:,.0f} is above your R{limit:,.0f} limit for payments without a second look.", v.check_at)
        ab = amount_baseline(db, sup["id"])
        if ab:
            z = robust_z(amt, ab["median"], ab["mad"], floor=max(1.0, ab["median"] * 0.02))
            if z >= CHECK_AT:
                v.add("Behaviour", f"R{amt:,.0f} is about {amt / ab['median']:.0f}× the usual payment to "
                                   f"{sup['name']} (around R{ab['median']:,.0f}).", 2.5)
            v.metric = {"label": f"Payment size to {sup['name']}", "lo": round(ab["lo"]), "hi": round(ab["hi"]),
                        "today": amt, "unit": "R"}
        fc = supplier_forecast(db, sup["id"])
        if fc:
            v.add("Forecast", f"Shamar predicted the next {sup['name']} payment around "
                              f"{date.fromisoformat(fc['next']).strftime('%d %b')} for about R{fc['amount']:,.0f} "
                              f"(they're usually paid every {fc['every_days']:.0f} days).", 0)

    if action == "create_discount":
        past = [p.get("pct", 0) for p in _param_list(db, actor["id"], action)]
        usual = max(past) if past else 10
        pct = int(params.get("pct", 0))
        if pct >= usual * 2:
            v.add("Context", f"{pct}% is far above the {usual}% {actor['name']} normally gives.", 6.0)
        elif pct > usual:
            v.add("Context", f"{pct}% is more than the {usual}% {actor['name']} normally gives.", 3.0)
        if params.get("order_value", 0) >= 5000:
            v.add("Context", f"It's on a large order (R{params['order_value']:,.0f}).", 1.0)

    if action == "issue_refund":
        amts = [p.get("amount", 0) for p in _param_list(db, actor["id"], action)]
        amt = float(params.get("amount", 0))
        if amts:
            med = median(amts)
            mad = median([abs(a - med) for a in amts])
            z = robust_z(amt, med, mad, floor=max(1.0, med * 0.1))
            lo, hi = min(amts), max(amts)
            if amt > hi and z >= CHECK_AT:
                v.add("Behaviour", f"R{amt:,.0f} is far above {actor['name']}'s usual refunds (R{lo:,.0f}–R{hi:,.0f}).", 4.0)
            v.metric = {"label": "Refund size", "lo": lo, "hi": hi, "today": amt, "unit": "R"}
        if params.get("to_account"):
            v.add("Context", "The refund would go to a bank account instead of the customer's original card.", 4.0)
        if not params.get("order"):
            v.add("Context", "No order number was given to refund against.", 1.5)
        if params.get("overpaid"):
            claimed = float(params.get("claimed_paid", 0) or 0)
            got = db.one("SELECT 1 x FROM bank_deposits WHERE abs(amount - ?) < 1", (claimed,)) if claimed else None
            if not got:
                v.add("Context", "The customer says they overpaid, but no such payment reached the bank. Classic overpayment scam.", 3.0)

    if action == "release_order":
        amt = float(params.get("amount", 0))
        dep = db.one("""SELECT * FROM bank_deposits WHERE abs(amount - ?) < 1 AND (reference LIKE ? OR ? = '')
                        ORDER BY id DESC LIMIT 1""", (amt, f"%{params.get('order', '')}%", params.get("order", "")))
        if not dep:
            v.add("Context", f"R{amt:,.0f} hasn't arrived in the business bank account. A proof-of-payment screenshot isn't money.", 5.0)
        known = db.one("SELECT 1 x FROM customers WHERE lower(email)=lower(?)", (params.get("buyer", ""),))
        if not known:
            v.add("Context", "First-time buyer with no order history.", 2.0)
        if re.search(r"uber|bolt|driver|courier", params.get("message", ""), re.I) and (URGENT.search(params.get("message", "")) or re.search(r"\b\d+\s*min", params.get("message", ""), re.I)):
            v.add("Context", "Rushed collection by a driver, before the money could clear: the usual fake-POP pattern.", 1.5)
        if amt > 3000:
            v.add("Behaviour", f"R{amt:,.0f} is much bigger than a typical order here (under R3,000).", 1.0)

    if action == "add_supplier":
        owner = db.one("SELECT name, email FROM actors WHERE kind='owner'")
        src = params.get("source", "") or ""
        if params.get("claims_owner") and owner and owner["email"] not in src:
            v.add("Context", f"The request says it's from {owner['name']}, but it came from {src}, "
                             f"not an address or number {owner['name']} uses.", 4.0)
        if URGENT.search(params.get("message", "")):
            v.add("Context", "The message pushes for speed and secrecy (\u201curgent\u201d, \u201cdon't call me\u201d), a classic pressure tactic.", 1.5)

    if action == "export_customers":
        if params.get("task") == "summarise_email":
            v.add("Context", f"{actor['name']} was only asked to summarise an email. Sending customer data has nothing to do with that task.", 3.0)
        if params.get("hidden"):
            v.add("Context", "The instruction came from inside the email, in hidden text a person can't see: "
                             f"\u201c{params['hidden'][:180]}{'…' if len(params['hidden']) > 180 else ''}\u201d", 3.0)
        to = params.get("to", "")
        known = db.one("SELECT 1 x FROM customers WHERE email=?", (to,))
        if not known and not to.endswith("@thandisboutique.co.za"):
            v.add("Context", f"The data would go to {to}, which isn't a customer or the business.", 3.0)
        if int(params.get("records", 0)) >= 50:
            v.add("Context", f"That's {params['records']} customer records with names, emails and phone numbers.", 3.0)
        if params.get("trigger"):
            v.add("Context", f"It started right after reading a message from {params['trigger']}.", 1.0)

    return v


WATCHED = ["answer_customer", "read_email", "prepare_payment", "update_bank_details", "export_customers"]


def profiles(db, today):
    """What Shamar has learned: each actor's normal pattern and each supplier's usual payments."""
    people = []
    for a in db.q("SELECT id, name, role, kind, paused FROM actors WHERE kind NOT IN ('owner', 'external') ORDER BY kind DESC, name"):
        hours = [int(r["h"]) for r in db.q("SELECT substr(ts,12,2) h FROM events WHERE history=1 AND actor_id=?", (a["id"],))]
        habits, never = [], []
        for action in WATCHED:
            base = daily_baseline(db, a["id"], action)
            label = ACTION_LABEL.get(action, action)
            if base["total"] == 0:
                never.append(label)
                continue
            n = db.one("""SELECT COUNT(*) n FROM events WHERE history=0 AND actor_id=? AND action=?
                          AND substr(ts,1,10)=?""", (a["id"], action, today))["n"]
            n_days = len({r['d'] for r in db.q("SELECT DISTINCT substr(ts,1,10) d FROM events WHERE history=1")}) or 1
            day_min = int(db.get("clock") or 480)
            share = min(1.0, max(0.0, (day_min - 8 * 60) / (9 * 60)))
            # project only busy, regular work; small counts are too noisy to extrapolate
            projected = round(n / share) if share >= 0.15 and base["median"] >= 5 else None
            if base["hi"] == 0:
                forecast = f"Rare: about {round(base['total'] / n_days * 26, 1)} a month"
            elif projected is None and n > base["hi"]:
                forecast = f"Already {n}, more than the usual {base['lo']}–{base['hi']} a day"
            elif projected is None:
                forecast = (f"Expected about {base['median']:.0f} today ({base['lo']}–{base['hi']})" if base["median"] >= 1
                            else f"Usually {base['lo']}–{base['hi']} a day")
            elif projected > base["hi"]:
                forecast = f"On pace for about {projected} by closing, above the usual {base['lo']}–{base['hi']}"
            elif base["hi"] > 0 and projected < base["lo"]:
                forecast = f"On pace for about {projected} by closing, quieter than usual"
            else:
                forecast = f"On pace for about {projected} by closing, normal ({base['lo']}–{base['hi']})"
            habits.append({"label": label.capitalize(), "lo": base["lo"], "hi": base["hi"],
                           "projected": projected, "forecast": forecast,
                           "trend": "above" if (projected is not None and projected > base["hi"]) or n > base["hi"] else "normal",
                           "expected_now": round(base["median"] * share, 1), "expected_day": base["median"],
                           "median": base["median"], "today": n,
                           "per_month": round(base["total"] / n_days * 26, 1),
                           "status": "above" if n > base["hi"] else "normal"})
        people.append({**a, "habits": habits, "never": never,
                       "hours": f"{_percentile(hours, 0.05):02.0f}:00–{_percentile(hours, 0.95) + 1:02.0f}:00" if hours else "–",
                       "days": len({r['d'] for r in db.q("SELECT DISTINCT substr(ts,1,10) d FROM events WHERE history=1")})})
    suppliers = []
    for s in db.q("SELECT * FROM suppliers ORDER BY name"):
        ab = amount_baseline(db, s["id"])
        changed = s["bank_changed_at"] and s["bank_changed_at"] != s["created_at"]
        src = s["bank_change_source"] or ""
        fc = supplier_forecast(db, s["id"])
        suppliers.append({
            "forecast": fc,
            "id": s["id"], "name": s["name"], "payments": ab["n"] if ab else 0,
            "usual": [round(ab["lo"], -1), round(ab["hi"], -1)] if ab else None,
            "median": round(ab["median"], -1) if ab else None,
            "bank": "Added today" if s["created_at"][:10] == today else "Fake change reversed today" if src == "restored" else
                    "Changed today" if changed and s["bank_changed_at"][:10] == today else
                    "Unchanged for over a year" if not changed else f"Changed {s['bank_changed_at'][:10]}",
            "trust": "unconfirmed" if src.startswith("email:") else "restored" if src == "restored" else "confirmed",
        })
    return {"people": people, "suppliers": suppliers}
