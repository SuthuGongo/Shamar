import re

from . import gateway

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ACCOUNT = re.compile(r"\b\d{8,13}\b")
HIDDEN = re.compile(r"<span[^>]*style=[\"'][^\"']*(?:color:\s*(?:#fff\b|#ffffff|white)|font-size:\s*[01](?:px|pt)?\b|display:\s*none)"
                    r"[^\"']*[\"'][^>]*>(.*?)</span>|<!--(.*?)-->", re.I | re.S)
TO_AI = re.compile(r"\b(ai|assistant|lindi|bot|copilot|chatgpt)\b", re.I)


def find_instruction(db, text):
    """What a naive assistant would 'obey' in this message (or None)."""
    t = text.lower()
    addr = EMAIL.search(text)
    wants_send = re.search(r"\b(send|email|e-mail|export|forward|share|mail|copy)\b", t)
    about_customers = re.search(r"\b(customer|customers|client|clients|shopper|shoppers)\b", t)
    data_words = re.search(r"\b(list|data|details|records|database|info|information|numbers|emails|contacts)\b", t)
    if addr and wants_send and about_customers and data_words:
        return {"type": "export", "to": addr.group(0)}

    pct = re.search(r"(\d{1,3})\s*(%|percent)", t)
    if pct and re.search(r"discount|off\b|code|coupon|promo", t):
        val = re.search(r"r\s?(\d[\d ,]{2,})", t)
        return {"type": "discount", "pct": int(pct.group(1)),
                "order_value": float(val.group(1).replace(",", "").replace(" ", "")) if val else 0}
    if re.search(r"\brefund\b", t):
        amt = re.search(r"r\s?(\d[\d ,]{1,})", t)
        if amt:
            acc_m = ACCOUNT.search(text)
            order = re.search(r"#\s?(\d{3,6})", t)
            over = re.search(r"over\s?paid|paid too much|by mistake|accidentally|instead of", t)
            amounts = [float(x.replace(",", "").replace(" ", "")) for x in re.findall(r"r\s?(\d[\d ,]{1,})", t)]
            return {"type": "refund", "amount": float(amt.group(1).replace(",", "").replace(" ", "")) if not over else
                    (max(amounts) - min(amounts) if len(amounts) >= 2 else amounts[0]),
                    "to_account": acc_m.group(0) if acc_m else None, "order": order.group(1) if order else None,
                    "overpaid": bool(over), "claimed_paid": max(amounts) if over and amounts else 0}

    acc = ACCOUNT.search(text)
    if acc and re.search(r"\b(bank|account|banking)\b", t) and re.search(r"\b(change|update|new|replace|switch)\b", t):
        for s in db.q("SELECT id, name FROM suppliers"):
            first_word = s["name"].lower().split()[0]
            if first_word in t:
                return {"type": "bank", "supplier_id": s["id"], "supplier": s["name"], "account": acc.group(0)}
    return None


def write_reply(db, text):
    t = text.lower()
    for item, keyword, plural in (("Blue shweshwe dress", "shweshwe", "blue shweshwe dresses"),
                                  ("Leather sandals", "sandal", "pairs of leather sandals")):
        if keyword in t:
            m = re.search(r"size\s*(\w+)", t)
            rows = db.q("SELECT * FROM stock WHERE name=?", (item,))
            if m:
                size = m.group(1).upper()
                row = next((r for r in rows if r["size"] == size), None)
                if row and row["qty"] > 0:
                    return f"Yes! We have {row['qty']} {plural} in size {size} at R{row['price']:,.0f}."
                in_stock = ", ".join(r["size"] for r in rows if r["qty"] > 0)
                return f"Sorry, {item.lower()} in size {size} is sold out. We have sizes {in_stock}."
            in_stock = ", ".join(f"{r['size']} ({r['qty']})" for r in rows if r["qty"] > 0)
            return f"{item} is R{rows[0]['price']:,.0f}. In stock: {in_stock}."
    if re.search(r"return|refund|exchange", t):
        return "You can return or exchange unworn items within 14 days with your slip."
    if re.search(r"deliver|shipping|courier", t):
        return "We deliver across Gauteng in 1 to 2 working days, and nationwide in 3 to 5. Delivery is R80."
    if re.search(r"saturday|sunday|open|close|hours|time", t):
        return "We're open Monday to Friday 08:00 to 17:00, and Saturday 09:00 to 15:00."
    if re.search(r"order|#\d+", t):
        num = re.search(r"#?(\d{3,6})", t)
        n = f"#{num.group(1)}" if num else "your order"
        return f"Order {n} left yesterday with Ubuntu Courier. It should arrive in 1 to 2 days."
    if re.search(r"\b(pay|card|eft|snapscan|cash)\b", t):
        return "We take card, EFT and SnapScan. Cash in store only."
    if re.search(r"where|address|located|location", t):
        return "We're at Shop 12, Maponya Mall, Soweto."
    if re.search(r"\b(hi|hello|hey|sawubona|dumela|molo)\b", t):
        return "Hi! I'm Lindi, Thandi's Boutique's assistant. How can I help?"
    if re.search(r"thank", t):
        return "You're welcome! Enjoy your day."
    return "Thanks for your message! Sipho will get back to you shortly."


def answer(db, q):
    """Lindi handles one customer message. Every action goes through Shamar."""
    lindi = db.one("SELECT * FROM actors WHERE id='lindi'")
    if lindi["paused"]:
        return {"paused": True, "level": "hold", "outcome": "waiting",
                "message": "Lindi is paused by the owner. Sipho will reply soon.", "query": q}

    ins = find_instruction(db, q["text"])
    if ins and ins["type"] == "export":
        n = db.one("SELECT COUNT(*) n FROM customers")["n"]
        res = gateway.act(db, "lindi", "export_customers",
                          {"records": n, "to": ins["to"], "query_id": q["id"], "trigger": q["email"]},
                          f"Tried to email {n} customer records to {ins['to']}")
        res.update(query=q, tricked=True)
        return res

    if ins and ins["type"] == "bank":
        res = gateway.deny(db, "lindi", "update_bank_details",
                           {"supplier_id": ins["supplier_id"], "new_account": ins["account"],
                            "query_id": q["id"], "trigger": q["email"]},
                           f"Tried to change {ins['supplier']}'s bank account to ••{ins['account'][-4:]}",
                           "AI assistants are not allowed to change bank details.")
        res.update(query=q, tricked=True)
        return res

    if ins and ins["type"] in ("discount", "refund"):
        if ins["type"] == "discount":
            res = gateway.act(db, "lindi", "create_discount",
                              {"pct": ins["pct"], "order_value": ins["order_value"], "customer": q["email"],
                               "query_id": q["id"], "trigger": q["email"]},
                              f"Tried to give {q['customer']} a {ins['pct']}% discount code")
            reply = f"Here's your {ins['pct']}% code: THANDI{ins['pct']}. Enjoy!"
        else:
            res = gateway.act(db, "lindi", "issue_refund",
                              {"amount": ins["amount"], "to_account": ins["to_account"], "order": ins["order"],
                               "overpaid": ins.get("overpaid"), "claimed_paid": ins.get("claimed_paid"),
                               "customer": q["email"], "query_id": q["id"], "trigger": q["email"]},
                              f"Tried to refund R{ins['amount']:,.0f} to {q['customer']}" +
                              (f" (account ••{ins['to_account'][-4:]})" if ins["to_account"] else ""))
            reply = f"Done! Your refund of R{ins['amount']:,.0f} is on its way to your original card."
        if res["outcome"] != "blocked":
            db.run("UPDATE customer_queries SET status='answered', reply=?, event_id=? WHERE id=?", (reply, res["event_id"], q["id"]))
        res.update(query=q, tricked=res["outcome"] == "blocked", reply=reply if res["outcome"] != "blocked" else None)
        return res

    reply = write_reply(db, q["text"])
    res = gateway.act(db, "lindi", "answer_customer",
                      {"query_id": q["id"], "to": q["email"], "reply": reply},
                      f"Answered {q['customer']}: “{q['text'][:40]}{'…' if len(q['text']) > 40 else ''}”")
    res.update(query=q, reply=reply)
    return res


def answer_next(db):
    q = db.one("SELECT * FROM customer_queries WHERE status='new' ORDER BY id LIMIT 1")
    if not q:
        return {"done": True, "message": "No new customer questions."}
    return answer(db, q)


def split_hidden(body):
    """Split an email into what a person sees and what's hidden from them (but not from an AI)."""
    body = body or ""
    hidden = " ".join((a or b).strip() for a, b in HIDDEN.findall(body))
    return HIDDEN.sub("", body).strip(), hidden


def _summary(mail, visible):
    skip = re.compile(r"^(hi|hello|hey|good (morning|afternoon|day)|dear|kind regards|regards|thanks|thank you|cheers)\b", re.I)
    lines = [l.strip() for l in visible.splitlines() if l.strip() and not (skip.match(l.strip()) and len(l.strip()) < 30)]
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(lines))
    return f"{mail['from_name']}: " + " ".join(sentences[:2])[:240]


def summarise(db, mail):
    """Sipho asks Lindi to summarise an email. Lindi reads everything in it, including hidden text."""
    if db.one("SELECT paused FROM actors WHERE id='lindi'")["paused"]:
        return {"paused": True, "level": "hold", "outcome": "waiting", "score": "-", "reasons": [],
                "message": "Lindi is paused by the owner, so she can't summarise emails right now."}
    visible, hidden = split_hidden(mail["body"])
    ins = find_instruction(db, f"{mail['subject']}\n{visible}\n{hidden}") if (hidden or TO_AI.search(visible)) else None
    base = {"email_id": mail["id"], "task": "summarise_email", "trigger": mail["from_addr"], "subject": mail["subject"]}
    if hidden:
        base["hidden"] = hidden[:300]
    if ins and ins["type"] == "export":
        n = db.one("SELECT COUNT(*) n FROM customers")["n"]
        res = gateway.act(db, "lindi", "export_customers", {**base, "records": n, "to": ins["to"]},
                          f"Tried to email {n} customer records to {ins['to']} while summarising an email")
        res.update(tricked=True, hidden=hidden)
        return res
    if ins and ins["type"] == "bank":
        res = gateway.deny(db, "lindi", "update_bank_details",
                           {**base, "supplier_id": ins["supplier_id"], "new_account": ins["account"]},
                           f"Tried to change {ins['supplier']}'s bank account to ••{ins['account'][-4:]} while summarising an email",
                           "AI assistants are not allowed to change bank details.")
        res.update(tricked=True, hidden=hidden)
        return res
    res = gateway.act(db, "lindi", "summarise_email", base, f"Summarised “{mail['subject']}” for Sipho")
    res.update(summary=_summary(mail, visible))
    return res
