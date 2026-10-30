"""Reset the database and fill it with realistic demo data.

Usage:  python seed.py
All demo accounts use the password  demo1234
"""
import random
from datetime import timedelta

from werkzeug.security import generate_password_hash

import db as database
from app import ACTIVE_STATUSES, SLA_HOURS, create_app, due_from, now, ts

random.seed(7)

USERS = [
    # name, email, department, role
    ("Alex Morgan", "admin@helpdesk.demo", "IT", "admin"),
    ("Sam Patel", "sam@helpdesk.demo", "IT", "agent"),
    ("Jordan Lee", "jordan@helpdesk.demo", "IT", "agent"),
    ("Priya Nair", "priya@helpdesk.demo", "IT", "agent"),
    ("Olivia Brown", "olivia@helpdesk.demo", "Finance", "employee"),
    ("Marcus Chen", "marcus@helpdesk.demo", "Sales", "employee"),
    ("Fatima Ali", "fatima@helpdesk.demo", "Human Resources", "employee"),
    ("Daniel Okafor", "daniel@helpdesk.demo", "Operations", "employee"),
    ("Emily Tremblay", "emily@helpdesk.demo", "Marketing", "employee"),
    ("Noah Wilson", "noah@helpdesk.demo", "Finance", "employee"),
    ("Grace Kim", "grace@helpdesk.demo", "Sales", "employee"),
]

ISSUES = {
    "Hardware": [
        ("Laptop won't turn on", "My laptop shows a black screen when I press the power button. The charging light is on.", "High"),
        ("Second monitor not detected", "My second monitor stopped showing anything after I moved desks. Cable looks fine.", "Medium"),
        ("Printer on 3rd floor keeps jamming", "The shared printer near the kitchen jams on every job. Paper tray was refilled this morning.", "Medium"),
        ("Keyboard keys sticking", "Several keys on my keyboard stick or double-type. Could I get a replacement?", "Low"),
        ("Docking station not charging laptop", "When I plug into the dock my laptop says 'plugged in, not charging'.", "Medium"),
        ("Headset microphone not working", "People can't hear me on Teams calls with my headset. It works on my phone.", "Medium"),
        ("Laptop running very hot and slow", "Fan is loud all the time and apps take minutes to open.", "Medium"),
    ],
    "Software": [
        ("Outlook not syncing calendar", "Meetings I accept on my phone don't show up in Outlook on my laptop.", "Medium"),
        ("Excel crashes when opening budget file", "Excel freezes and closes whenever I open the Q3 budget workbook. Other files open fine.", "High"),
        ("Request to install Tableau", "I need Tableau Desktop for the monthly sales report. My manager approved it.", "Low"),
        ("Teams screen share shows black screen", "When I share my screen in Teams, others only see black.", "Medium"),
        ("Adobe Acrobat asking for licence", "Acrobat says my trial expired and I can't edit PDFs anymore.", "Low"),
        ("Windows update stuck at 35%", "Update has been stuck for over an hour and I can't use the laptop.", "High"),
        ("Payroll app shows error 500", "The payroll system shows 'Error 500' after login. Payroll is due tomorrow.", "Critical"),
    ],
    "Network": [
        ("Wi-Fi drops in meeting room B", "Wi-Fi disconnects every few minutes in meeting room B. Other rooms are fine.", "Medium"),
        ("VPN disconnects every hour", "When working from home the VPN drops roughly every hour and I lose my session.", "High"),
        ("Can't reach shared drive from home", "The S: drive won't open over VPN. It works in the office.", "Medium"),
        ("Whole office internet is down", "Nobody on the 2nd floor has internet. Wired and Wi-Fi both down.", "Critical"),
        ("Very slow internet in warehouse office", "Pages take 20+ seconds to load on the warehouse PCs.", "Medium"),
    ],
    "Account & Access": [
        ("Password reset for CRM", "I'm locked out of the CRM after too many attempts.", "High"),
        ("New hire account setup: starts Monday", "Please set up email, laptop and CRM access for our new sales rep starting Monday.", "Medium"),
        ("Access to Finance shared folder", "I need read access to the Finance > Reports folder for month-end.", "Low"),
        ("MFA prompt not arriving on new phone", "I got a new phone and the authenticator codes no longer work.", "High"),
        ("Remove access for departing employee", "Please disable accounts for a team member whose last day is Friday.", "Medium"),
        ("Locked out of email", "My email account says it's locked. I can't log in on any device.", "High"),
    ],
    "Other": [
        ("Phishing email reported", "I got an email asking me to 'verify payroll details' with a strange link. I didn't click it.", "High"),
        ("Conference room TV won't show laptop", "The TV in the boardroom says 'no signal' with the HDMI cable.", "Low"),
        ("Question about laptop refresh", "My laptop is 5 years old. When is it scheduled for replacement?", "Low"),
    ],
}

AGENT_REPLIES = [
    "Thanks for reporting this. I'm looking into it now.",
    "Could you send a screenshot of the error and tell me when it started?",
    "I've remoted in and applied a fix. Can you confirm it's working on your side?",
    "This is a known issue. A patch is going out today; I'll update you once it's applied.",
    "I've reset it on our end. Please sign out, sign back in and let me know.",
    "Swapped the hardware this morning. You should be good to go.",
]
USER_REPLIES = [
    "Thanks! That fixed it.",
    "Here's the screenshot. It started yesterday afternoon.",
    "Still happening after the restart, unfortunately.",
    "Works now, thank you for the quick help.",
]
INTERNAL_NOTES = [
    "Checked logs: same error on two other machines. Might be the latest update.",
    "Escalating to network vendor if it happens again.",
    "Warranty is still active, so we'll request a replacement unit.",
]


def main():
    app = create_app()
    with app.app_context():
        database.init_db()
        db = database.get_db()
        t0 = now()
        pw = generate_password_hash("demo1234")
        for name, email, dept, role in USERS:
            db.execute("INSERT INTO users (name, email, department, role, password_hash, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (name, email, dept, role, pw, ts(t0 - timedelta(days=90))))
        users = {r["email"]: dict(r) for r in db.execute("SELECT * FROM users")}
        agents = [u for u in users.values() if u["role"] in ("agent", "admin")]
        employees = [u for u in users.values() if u["role"] == "employee"]
        pool = [(cat, *issue) for cat, issues in ISSUES.items() for issue in issues]

        def act(tid, who, text, when):
            db.execute("INSERT INTO activity (ticket_id, actor_id, action, created_at) VALUES (?, ?, ?, ?)",
                       (tid, who["id"], text, ts(when)))

        def note(tid, who, body, when, internal=0):
            db.execute("INSERT INTO comments (ticket_id, author_id, body, internal, created_at) VALUES (?, ?, ?, ?, ?)",
                       (tid, who["id"], body, internal, ts(when)))

        n_tickets = 130
        fresh = random.sample(pool, 20)
        for i in range(n_tickets):
            cat, title, desc, pri = fresh[i] if i < 20 else random.choice(pool)
            if random.random() < 0.25:  # some users over/under-prioritize
                pri = random.choice(["Low", "Medium", "High"])
            # Spread over the last 8 weeks, newer weeks a bit busier; weekdays, office hours.
            age_days = int(random.triangular(0, 56, 10))
            created = (t0 - timedelta(days=age_days)).replace(hour=random.randint(8, 16), minute=random.randint(0, 59), second=0)
            while created.weekday() >= 5:
                created -= timedelta(days=1)
            if i < 20:  # a steady stream of fresh tickets so the live queue is busy
                created = t0 - timedelta(minutes=random.randint(15, 60 * 70))
            if created > t0:
                created = t0 - timedelta(minutes=random.randint(20, 300))
            requester = random.choice(employees)
            due = due_from(created, pri)
            # Keep most of the live queue inside its SLA (a real team clears the worst first).
            if i < 20 and due < t0 and random.random() < 0.75:
                created = t0 - timedelta(minutes=random.randint(10, int(SLA_HOURS[pri] * 60 * 0.8)))
                due = due_from(created, pri)
            hours_old = (t0 - created).total_seconds() / 3600

            # Older tickets are almost all resolved; recent ones mostly still active.
            if hours_old > 24 * 7:
                status = random.choices(["Closed", "Resolved", "Waiting on User", "In Progress"], [62, 36, 1, 1])[0]
            elif hours_old > 48:
                status = random.choices(["Resolved", "Closed", "In Progress", "Waiting on User", "Open"], [58, 27, 8, 5, 2])[0]
            else:
                status = random.choices(["Open", "In Progress", "Waiting on User", "Resolved"], [35, 35, 10, 20])[0]

            agent = None if status == "Open" and random.random() < 0.7 else random.choice(agents)
            resolved_at = None
            if status in ("Resolved", "Closed"):
                # ~85% inside SLA, the rest late.
                sla = SLA_HOURS[pri]
                hrs = random.uniform(0.3, sla * 0.95) if random.random() < 0.85 else random.uniform(sla * 1.1, sla * 2.5)
                resolved_at = min(created + timedelta(hours=hrs), t0 - timedelta(minutes=5))
            updated = resolved_at or min(created + timedelta(hours=random.uniform(0.5, max(1, hours_old * 0.8))), t0)

            cur = db.execute(
                "INSERT INTO tickets (title, description, category, priority, status, requester_id, assignee_id, "
                "created_at, updated_at, due_at, resolved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (title, desc, cat, pri, status, requester["id"], agent["id"] if agent else None,
                 ts(created), ts(updated), ts(due), ts(resolved_at) if resolved_at else None))
            tid = cur.lastrowid
            act(tid, requester, "created the ticket", created)
            step = created + timedelta(minutes=random.randint(10, 90))
            if agent:
                step = min(step, t0)
                act(tid, agent, "took the ticket, status Open → In Progress", step)
                note(tid, agent, random.choice(AGENT_REPLIES[:2]), step + timedelta(minutes=2))
                if random.random() < 0.3:
                    note(tid, agent, random.choice(INTERNAL_NOTES), step + timedelta(minutes=8), internal=1)
                    act(tid, agent, "added an internal note", step + timedelta(minutes=8))
            if status == "Waiting on User" and agent:
                act(tid, agent, "changed status In Progress → Waiting on User", step + timedelta(minutes=5))
            if resolved_at and agent:
                if random.random() < 0.6:
                    note(tid, agent, random.choice(AGENT_REPLIES[2:]), resolved_at - timedelta(minutes=10))
                act(tid, agent, "changed status In Progress → Resolved", resolved_at)
                if random.random() < 0.5:
                    note(tid, requester, random.choice([USER_REPLIES[0], USER_REPLIES[3]]), resolved_at + timedelta(minutes=random.randint(5, 50)))
                if status == "Closed":
                    act(tid, agent, "changed status Resolved → Closed", min(resolved_at + timedelta(hours=random.randint(20, 48)), t0))

        db.commit()
        active = db.execute(f"SELECT COUNT(*) FROM tickets WHERE status IN {ACTIVE_STATUSES}").fetchone()[0]
        print(f"Seeded {len(USERS)} users and {n_tickets} tickets ({active} active).")
        print("Log in with admin@helpdesk.demo / demo1234")


if __name__ == "__main__":
    main()
