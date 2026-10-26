import json

from . import gateway, lindi
from .seed import ts_on, demo_day

EARLY_QUERIES = [
    ("Nomsa K.", "nomsa.k@example.com", "Hi, is the blue shweshwe dress available in size L?"),
    ("Thabo M.", "thabo.m@example.com", "What time do you open on Saturday?"),
    ("Precious N.", "precious.n@example.com", "Can I exchange sandals that are too small?"),
    ("Karabo D.", "karabo.d@example.com", "Do you deliver to Pretoria?"),
    ("Lwazi P.", "lwazi.p@example.com", "Has order #1038 been sent?"),
    ("Ama B.", "ama.b@example.com", "Do you take SnapScan?"),
    ("Zanele M.", "zanele.m@example.com", "Leather sandals size 38, are they in stock?"),
    ("Bongani S.", "bongani.s@example.com", "Where is your shop?"),
    ("Lerato T.", "lerato.t@example.com", "Thank you, my order arrived!"),
    ("Kagiso R.", "kagiso.r@example.com", "Do you deliver to Soweto?"),
]

EARLY_EMAILS = [
    ("Ubuntu Courier", "billing@ubuntucourier.co.za", "Invoice INV-5521", "Hi, please find invoice INV-5521 for October deliveries: R1,480. Thanks!"),
    ("SARS eFiling", "noreply@sars.gov.za", "Reminder: VAT201 due 25 November", "This is a reminder that your VAT201 return is due on 25 November."),
    ("Nomsa K.", "nomsa.k@example.com", "Order #1044 question", "Hi Sipho, can you gift-wrap my order? Thanks, Nomsa"),
]


def run(db):
    """A normal morning (07:00-08:00) that already happened before the demo starts."""
    day = demo_day()
    db.set("clock", 7 * 60)
    ids = []
    for i, (name, addr, subject, body) in enumerate(EARLY_EMAILS):
        ids.append(db.run("""INSERT INTO inbox(to_actor, ts, from_name, from_addr, subject, body, ask)
                             VALUES ('sipho',?,?,?,?,?,?)""",
                          (ts_on(day, 6 * 60 + 30 + i * 7), name, addr, subject, body, json.dumps({"type": "none"}))))
    for name, email, text in EARLY_QUERIES[:5]:
        qid = db.run("INSERT INTO customer_queries(customer, email, text) VALUES (?,?,?)", (name, email, text))
        lindi.answer(db, db.one("SELECT * FROM customer_queries WHERE id=?", (qid,)))
    for eid in ids:
        gateway.act(db, "sipho", "read_email", {"email_id": eid}, f"Read “{db.one('SELECT subject FROM inbox WHERE id=?', (eid,))['subject']}”")
        lindi.summarise(db, db.one("SELECT * FROM inbox WHERE id=?", (eid,)))
    r = gateway.act(db, "sipho", "prepare_payment", {"supplier_id": "ubuntu", "amount": 1480, "reference": "INV-5521"},
                    "Prepared R1,480 to Ubuntu Courier")
    for name, email, text in EARLY_QUERIES[5:]:
        qid = db.run("INSERT INTO customer_queries(customer, email, text) VALUES (?,?,?)", (name, email, text))
        lindi.answer(db, db.one("SELECT * FROM customer_queries WHERE id=?", (qid,)))
    gateway.approve_payment(db, "thandi", r["payment_id"])
    db.set("clock", max(int(db.get("clock")), 8 * 60))
