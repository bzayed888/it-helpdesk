import re
import sys
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db as database  # noqa: E402
from app import create_app, now, ts  # noqa: E402


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"), "SECRET_KEY": "test"})
    with app.app_context():
        database.init_db()
        pw = generate_password_hash("password123")
        for name, email, role in [("Ada Admin", "admin@t.test", "admin"), ("Al Agent", "agent@t.test", "agent"),
                                  ("Eve Employee", "eve@t.test", "employee"), ("Bob Employee", "bob@t.test", "employee")]:
            database.execute("INSERT INTO users (name, email, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                             (name, email, role, pw, ts(now())))
    return app


def token(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(client, email):
    t = token(client)
    return client.post("/login", data={"email": email, "password": "password123", "csrf_token": t})


def new_ticket(client, title="Printer jammed", priority="High", category="Hardware"):
    t = token(client, "/tickets/new")
    r = client.post("/tickets/new", data={"title": title, "description": "It keeps jamming.",
                                          "category": category, "priority": priority, "csrf_token": t})
    return int(r.headers["Location"].rsplit("/", 1)[1])


def row(app, sql, args=()):
    with app.app_context():
        return database.query(sql, args, one=True)


def test_login_required(app):
    c = app.test_client()
    assert c.get("/tickets").status_code == 302
    assert c.get("/dashboard").status_code == 302


def test_bad_password_rejected(app):
    c = app.test_client()
    t = token(c)
    r = c.post("/login", data={"email": "eve@t.test", "password": "wrong", "csrf_token": t})
    assert b"Incorrect email or password" in r.data


def test_post_without_csrf_token_is_rejected(app):
    c = app.test_client()
    r = c.post("/login", data={"email": "eve@t.test", "password": "password123"})
    assert r.status_code == 400


def test_register_creates_employee_with_hashed_password(app):
    c = app.test_client()
    t = token(c, "/register")
    c.post("/register", data={"name": "New Person", "email": "new@t.test", "password": "longenough1", "csrf_token": t})
    u = row(app, "SELECT * FROM users WHERE email = 'new@t.test'")
    assert u["role"] == "employee"
    assert u["password_hash"] != "longenough1"


def test_ticket_gets_sla_due_time(app):
    c = app.test_client()
    login(c, "eve@t.test")
    tid = new_ticket(c, priority="Critical")
    t = row(app, "SELECT (julianday(due_at) - julianday(created_at)) * 24 AS h, status FROM tickets WHERE id = ?", (tid,))
    assert round(t["h"]) == 4
    assert t["status"] == "Open"


def test_employee_cannot_see_other_employees_ticket(app):
    c = app.test_client()
    login(c, "eve@t.test")
    tid = new_ticket(c)
    other = app.test_client()
    login(other, "bob@t.test")
    assert other.get(f"/tickets/{tid}").status_code == 403
    assert b"Printer jammed" not in other.get("/tickets").data


def test_employee_cannot_open_dashboard_or_update(app):
    c = app.test_client()
    login(c, "eve@t.test")
    tid = new_ticket(c)
    assert c.get("/dashboard").status_code == 403
    t = token(c, f"/tickets/{tid}")
    r = c.post(f"/tickets/{tid}/update", data={"status": "Closed", "priority": "Low", "csrf_token": t})
    assert r.status_code == 403


def test_agent_resolves_ticket_and_history_is_logged(app):
    emp = app.test_client()
    login(emp, "eve@t.test")
    tid = new_ticket(emp)
    agent = app.test_client()
    login(agent, "agent@t.test")
    t = token(agent, f"/tickets/{tid}")
    agent.post(f"/tickets/{tid}/update", data={"status": "Resolved", "priority": "High", "assignee_id": "2", "csrf_token": t})
    tk = row(app, "SELECT status, resolved_at, assignee_id FROM tickets WHERE id = ?", (tid,))
    assert tk["status"] == "Resolved" and tk["resolved_at"] and tk["assignee_id"] == 2
    log = row(app, "SELECT action FROM activity WHERE ticket_id = ? ORDER BY id DESC", (tid,))
    assert "Open → Resolved" in log["action"]


def test_priority_change_recalculates_due_time(app):
    emp = app.test_client()
    login(emp, "eve@t.test")
    tid = new_ticket(emp, priority="Low")
    agent = app.test_client()
    login(agent, "agent@t.test")
    t = token(agent, f"/tickets/{tid}")
    agent.post(f"/tickets/{tid}/update", data={"status": "Open", "priority": "High", "assignee_id": "", "csrf_token": t})
    h = row(app, "SELECT (julianday(due_at) - julianday(created_at)) * 24 AS h FROM tickets WHERE id = ?", (tid,))["h"]
    assert round(h) == 8


def test_internal_notes_hidden_from_requester(app):
    emp = app.test_client()
    login(emp, "eve@t.test")
    tid = new_ticket(emp)
    agent = app.test_client()
    login(agent, "agent@t.test")
    t = token(agent, f"/tickets/{tid}")
    agent.post(f"/tickets/{tid}/comment", data={"body": "Secret IT-only note", "internal": "1", "csrf_token": t})
    agent.post(f"/tickets/{tid}/comment", data={"body": "Public reply to Eve", "csrf_token": t})
    page = emp.get(f"/tickets/{tid}").data
    assert b"Public reply to Eve" in page
    assert b"Secret IT-only note" not in page
    assert b"Secret IT-only note" in agent.get(f"/tickets/{tid}").data


def test_employee_reply_moves_waiting_ticket_back_to_in_progress(app):
    emp = app.test_client()
    login(emp, "eve@t.test")
    tid = new_ticket(emp)
    agent = app.test_client()
    login(agent, "agent@t.test")
    t = token(agent, f"/tickets/{tid}")
    agent.post(f"/tickets/{tid}/update", data={"status": "Waiting on User", "priority": "High", "assignee_id": "2", "csrf_token": t})
    t = token(emp, f"/tickets/{tid}")
    emp.post(f"/tickets/{tid}/comment", data={"body": "Here is the screenshot", "csrf_token": t})
    assert row(app, "SELECT status FROM tickets WHERE id = ?", (tid,))["status"] == "In Progress"


def test_search_input_is_parameterized(app):
    c = app.test_client()
    login(c, "agent@t.test")
    r = c.get("/tickets", query_string={"q": "' OR 1=1 --", "status": "all"})
    assert r.status_code == 200
    assert b"No tickets here" in r.data


def test_only_admin_can_change_roles(app):
    agent = app.test_client()
    login(agent, "agent@t.test")
    assert agent.get("/admin/users").status_code == 403
    admin = app.test_client()
    login(admin, "admin@t.test")
    t = token(admin, "/admin/users")
    admin.post("/admin/users", data={"user_id": "3", "role": "agent", "csrf_token": t})
    assert row(app, "SELECT role FROM users WHERE id = 3")["role"] == "agent"


def test_open_redirect_blocked(app):
    c = app.test_client()
    t = token(c)
    r = c.post("/login?next=//evil.example", data={"email": "eve@t.test", "password": "password123", "csrf_token": t})
    assert r.headers["Location"] == "/"
