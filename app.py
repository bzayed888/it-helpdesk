"""IT Helpdesk: a small ticketing system for an office IT team.

Employees log tickets, IT agents work them, and admins manage users.
Run `flask --app app init-db` then `python seed.py` for demo data.
"""
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db as database
from db import execute, query

CATEGORIES = ["Hardware", "Software", "Network", "Account & Access", "Other"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Open", "In Progress", "Waiting on User", "Resolved", "Closed"]
ACTIVE_STATUSES = ("Open", "In Progress", "Waiting on User")
ROLES = ["employee", "agent", "admin"]

# Response targets (service level agreement) in hours, by priority.
SLA_HOURS = {"Critical": 4, "High": 8, "Medium": 24, "Low": 72}

TS = "%Y-%m-%d %H:%M:%S"


def now():
    return datetime.now().replace(microsecond=0)


def ts(dt):
    return dt.strftime(TS)


def parse(value):
    return datetime.strptime(value, TS) if value else None


def due_from(created, priority):
    return created + timedelta(hours=SLA_HOURS[priority])


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------
def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", secrets.token_hex(32)),
        DATABASE=os.environ.get("HELPDESK_DB", os.path.join(app.root_path, "helpdesk.db")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(database.close_db)

    @app.cli.command("init-db")
    def init_db_command():
        """Create empty tables."""
        database.init_db()
        print("Initialized the database.")

    register_hooks(app)
    register_filters(app)
    register_routes(app)
    return app


# --------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def is_staff():
    return g.user is not None and g.user["role"] in ("agent", "admin")


def register_hooks(app):
    @app.before_request
    def load_user():
        uid = session.get("user_id")
        g.user = query("SELECT * FROM users WHERE id = ?", (uid,), one=True) if uid else None

    @app.before_request
    def csrf_protect():
        """Every POST form must carry the session's CSRF token."""
        if request.method == "POST" and not app.config.get("TESTING_NO_CSRF"):
            token = session.get("csrf_token")
            if not token or token != request.form.get("csrf_token"):
                abort(400, "Invalid or missing form token. Refresh the page and try again.")

    @app.context_processor
    def inject():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        return {
            "csrf_token": session["csrf_token"],
            "is_staff": is_staff(),
            "CATEGORIES": CATEGORIES,
            "PRIORITIES": PRIORITIES,
            "STATUSES": STATUSES,
            "SLA_HOURS": SLA_HOURS,
        }

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        return resp


# --------------------------------------------------------------------------
# Template filters
# --------------------------------------------------------------------------
def register_filters(app):
    @app.template_filter("when")
    def when(value):
        dt = parse(value)
        return dt.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ") if dt else "—"

    @app.template_filter("ago")
    def ago(value):
        dt = parse(value)
        if not dt:
            return "—"
        secs = (now() - dt).total_seconds()
        future = secs < 0
        secs = abs(secs)
        if secs < 60:
            return "just now"
        for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
            if secs >= size:
                n = int(secs // size)
                return f"in {n}{unit}" if future else f"{n}{unit} ago"
        return "just now"

    @app.template_filter("slug")
    def slug(value):
        return (value or "").lower().replace(" ", "-").replace("&", "and")


def sla_state(ticket):
    """Return ('met'|'breached'|'due-soon'|'on-track', label) for a ticket."""
    due = parse(ticket["due_at"])
    if ticket["status"] in ("Resolved", "Closed"):
        done = parse(ticket["resolved_at"]) or parse(ticket["updated_at"])
        return ("met", "SLA met") if done <= due else ("breached", "SLA missed")
    left = (due - now()).total_seconds()
    if left < 0:
        return "breached", "Overdue"
    if left < 2 * 3600:
        return "due-soon", "Due soon"
    return "on-track", "On track"


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
def register_routes(app):

    # ---------- auth ----------
    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            dept = request.form.get("department", "").strip() or "General"
            pw = request.form.get("password", "")
            error = None
            if not name or not email or not pw:
                error = "Name, email and password are required."
            elif len(pw) < 8:
                error = "Password must be at least 8 characters."
            elif query("SELECT 1 FROM users WHERE email = ?", (email,), one=True):
                error = "An account with that email already exists."
            if error:
                flash(error, "error")
            else:
                uid = execute(
                    "INSERT INTO users (name, email, department, role, password_hash, created_at) "
                    "VALUES (?, ?, ?, 'employee', ?, ?)",
                    (name, email, dept, generate_password_hash(pw), ts(now())),
                )
                session.clear()
                session["user_id"] = uid
                flash("Welcome! Your account is ready.", "success")
                return redirect(url_for("tickets"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            pw = request.form.get("password", "")
            user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
            if user and check_password_hash(user["password_hash"], pw):
                session.clear()
                session["user_id"] = user["id"]
                nxt = request.args.get("next", "")
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = url_for("home")
                return redirect(nxt)
            flash("Incorrect email or password.", "error")
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def home():
        return redirect(url_for("dashboard" if is_staff() else "tickets"))

    # ---------- tickets ----------
    @app.route("/tickets")
    @login_required
    def tickets():
        f = {k: request.args.get(k, "") for k in ("status", "priority", "category", "assignee", "q")}
        where, args = [], []

        if not is_staff():
            where.append("t.requester_id = ?")
            args.append(g.user["id"])

        if f["status"] == "active" or f["status"] == "":
            where.append(f"t.status IN ({','.join('?' * len(ACTIVE_STATUSES))})")
            args.extend(ACTIVE_STATUSES)
        elif f["status"] in STATUSES:
            where.append("t.status = ?")
            args.append(f["status"])
        if f["priority"] in PRIORITIES:
            where.append("t.priority = ?")
            args.append(f["priority"])
        if f["category"] in CATEGORIES:
            where.append("t.category = ?")
            args.append(f["category"])
        if is_staff():
            if f["assignee"] == "me":
                where.append("t.assignee_id = ?")
                args.append(g.user["id"])
            elif f["assignee"] == "none":
                where.append("t.assignee_id IS NULL")
        if f["q"]:
            where.append("(t.title LIKE ? OR t.description LIKE ? OR CAST(t.id AS TEXT) = ?)")
            like = f"%{f['q']}%"
            args.extend([like, like, f["q"].lstrip("#")])

        sql = (
            "SELECT t.*, r.name AS requester, a.name AS assignee FROM tickets t "
            "JOIN users r ON r.id = t.requester_id "
            "LEFT JOIN users a ON a.id = t.assignee_id "
            + ("WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY CASE WHEN t.status IN ('Resolved','Closed') THEN 1 ELSE 0 END, "
            "CASE t.priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, "
            "t.due_at"
        )
        rows = [dict(r, sla=sla_state(r)) for r in query(sql, args)]
        return render_template("tickets.html", tickets=rows, f=f)

    @app.route("/tickets/new", methods=["GET", "POST"])
    @login_required
    def new_ticket():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            desc = request.form.get("description", "").strip()
            cat = request.form.get("category")
            pri = request.form.get("priority")
            if not title or not desc or cat not in CATEGORIES or pri not in PRIORITIES:
                flash("Please fill in every field.", "error")
                return render_template("new_ticket.html", form=request.form)
            created = now()
            tid = execute(
                "INSERT INTO tickets (title, description, category, priority, status, requester_id, "
                "created_at, updated_at, due_at) VALUES (?, ?, ?, ?, 'Open', ?, ?, ?, ?)",
                (title[:120], desc, cat, pri, g.user["id"], ts(created), ts(created),
                 ts(due_from(created, pri))),
            )
            log(tid, "created the ticket")
            flash(f"Ticket #{tid} submitted. IT will be in touch.", "success")
            return redirect(url_for("ticket", tid=tid))
        return render_template("new_ticket.html", form={})

    def load_ticket(tid):
        t = query(
            "SELECT t.*, r.name AS requester, r.email AS requester_email, r.department, "
            "a.name AS assignee FROM tickets t JOIN users r ON r.id = t.requester_id "
            "LEFT JOIN users a ON a.id = t.assignee_id WHERE t.id = ?", (tid,), one=True)
        if t is None:
            abort(404)
        if not is_staff() and t["requester_id"] != g.user["id"]:
            abort(403)
        return t

    def log(tid, action):
        execute("INSERT INTO activity (ticket_id, actor_id, action, created_at) VALUES (?, ?, ?, ?)",
                (tid, g.user["id"], action, ts(now())))

    @app.route("/tickets/<int:tid>")
    @login_required
    def ticket(tid):
        t = load_ticket(tid)
        comments = query(
            "SELECT c.*, u.name AS author, u.role AS author_role FROM comments c "
            "JOIN users u ON u.id = c.author_id WHERE c.ticket_id = ? "
            + ("" if is_staff() else "AND c.internal = 0 ")
            + "ORDER BY c.created_at", (tid,))
        activity = query(
            "SELECT a.*, u.name AS actor FROM activity a JOIN users u ON u.id = a.actor_id "
            "WHERE a.ticket_id = ? ORDER BY a.created_at DESC, a.id DESC", (tid,))
        agents = query("SELECT id, name FROM users WHERE role IN ('agent','admin') ORDER BY name")
        return render_template("ticket.html", t=t, sla=sla_state(t), comments=comments,
                               activity=activity, agents=agents)

    @app.post("/tickets/<int:tid>/comment")
    @login_required
    def comment(tid):
        t = load_ticket(tid)
        body = request.form.get("body", "").strip()
        internal = 1 if (is_staff() and request.form.get("internal")) else 0
        if not body:
            flash("Comment can't be empty.", "error")
            return redirect(url_for("ticket", tid=tid))
        stamp = ts(now())
        execute("INSERT INTO comments (ticket_id, author_id, body, internal, created_at) VALUES (?, ?, ?, ?, ?)",
                (tid, g.user["id"], body, internal, stamp))
        # A reply from the employee puts a waiting ticket back in the queue.
        if not is_staff() and t["status"] == "Waiting on User":
            execute("UPDATE tickets SET status = 'In Progress', updated_at = ? WHERE id = ?", (stamp, tid))
            log(tid, "replied, status Waiting on User → In Progress")
        else:
            execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (stamp, tid))
            log(tid, "added an internal note" if internal else "added a comment")
        return redirect(url_for("ticket", tid=tid) + "#comments")

    @app.post("/tickets/<int:tid>/update")
    @role_required("agent", "admin")
    def update_ticket(tid):
        t = load_ticket(tid)
        status = request.form.get("status", t["status"])
        priority = request.form.get("priority", t["priority"])
        assignee = request.form.get("assignee_id") or None
        if status not in STATUSES or priority not in PRIORITIES:
            abort(400)
        if assignee is not None:
            assignee = int(assignee)
            if not query("SELECT 1 FROM users WHERE id = ? AND role IN ('agent','admin')", (assignee,), one=True):
                abort(400)

        changes, stamp = [], now()
        resolved_at, due_at = t["resolved_at"], t["due_at"]
        if status != t["status"]:
            changes.append(f"status {t['status']} → {status}")
            if status in ("Resolved", "Closed") and not resolved_at:
                resolved_at = ts(stamp)
            elif status in ACTIVE_STATUSES:
                resolved_at = None
        if priority != t["priority"]:
            changes.append(f"priority {t['priority']} → {priority}")
            due_at = ts(due_from(parse(t["created_at"]), priority))
        if assignee != t["assignee_id"]:
            name = query("SELECT name FROM users WHERE id = ?", (assignee,), one=True)["name"] if assignee else "nobody"
            changes.append(f"assigned to {name}")
            if t["status"] == "Open" and status == "Open" and assignee:
                status = "In Progress"
                changes.append("status Open → In Progress")

        if changes:
            execute("UPDATE tickets SET status=?, priority=?, assignee_id=?, due_at=?, resolved_at=?, updated_at=? "
                    "WHERE id=?", (status, priority, assignee, due_at, resolved_at, ts(stamp), tid))
            log(tid, "changed " + ", ".join(changes))
            flash("Ticket updated.", "success")
        return redirect(url_for("ticket", tid=tid))

    @app.post("/tickets/<int:tid>/take")
    @role_required("agent", "admin")
    def take_ticket(tid):
        t = load_ticket(tid)
        status = "In Progress" if t["status"] == "Open" else t["status"]
        execute("UPDATE tickets SET assignee_id=?, status=?, updated_at=? WHERE id=?",
                (g.user["id"], status, ts(now()), tid))
        log(tid, "took the ticket" + (", status Open → In Progress" if status != t["status"] else ""))
        return redirect(request.form.get("back") or url_for("ticket", tid=tid))

    # ---------- dashboard ----------
    @app.route("/dashboard")
    @role_required("agent", "admin")
    def dashboard():
        active = f"status IN ({','.join('?' * len(ACTIVE_STATUSES))})"
        stamp = ts(now())
        week_ago = ts(now() - timedelta(days=7))

        kpi = {
            "open": query(f"SELECT COUNT(*) n FROM tickets WHERE {active}", ACTIVE_STATUSES, one=True)["n"],
            "unassigned": query(f"SELECT COUNT(*) n FROM tickets WHERE {active} AND assignee_id IS NULL",
                                ACTIVE_STATUSES, one=True)["n"],
            "overdue": query(f"SELECT COUNT(*) n FROM tickets WHERE {active} AND due_at < ?",
                             (*ACTIVE_STATUSES, stamp), one=True)["n"],
            "resolved_week": query("SELECT COUNT(*) n FROM tickets WHERE resolved_at >= ?",
                                   (week_ago,), one=True)["n"],
        }
        res = query("SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 24) avg_h, "
                    "AVG(CASE WHEN resolved_at <= due_at THEN 1.0 ELSE 0 END) met "
                    "FROM tickets WHERE resolved_at IS NOT NULL", one=True)
        kpi["avg_hours"] = round(res["avg_h"] or 0, 1)
        kpi["sla_met"] = round((res["met"] or 0) * 100)

        by_status = {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) n FROM tickets GROUP BY status")}
        by_cat = {r["category"]: r["n"] for r in query(
            "SELECT category, COUNT(*) n FROM tickets WHERE created_at >= ? GROUP BY category",
            (ts(now() - timedelta(days=56)),))}
        by_pri_open = {r["priority"]: r["n"] for r in query(
            f"SELECT priority, COUNT(*) n FROM tickets WHERE {active} GROUP BY priority", ACTIVE_STATUSES)}

        # Created vs resolved per week, last 8 weeks (Mon-start weeks).
        today = now().replace(hour=0, minute=0, second=0)
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=7)
        weeks, created, resolved = [], [], []
        for i in range(8):
            a, b = start + timedelta(weeks=i), start + timedelta(weeks=i + 1)
            weeks.append(a.strftime("%b %d").replace(" 0", " "))
            created.append(query("SELECT COUNT(*) n FROM tickets WHERE created_at >= ? AND created_at < ?",
                                 (ts(a), ts(b)), one=True)["n"])
            resolved.append(query("SELECT COUNT(*) n FROM tickets WHERE resolved_at >= ? AND resolved_at < ?",
                                  (ts(a), ts(b)), one=True)["n"])

        workload = query(
            f"SELECT u.name, SUM(CASE WHEN t.{active} THEN 1 ELSE 0 END) open_n, "
            "SUM(CASE WHEN t.resolved_at >= ? THEN 1 ELSE 0 END) resolved_n "
            "FROM users u LEFT JOIN tickets t ON t.assignee_id = u.id "
            "WHERE u.role IN ('agent','admin') GROUP BY u.id ORDER BY open_n DESC, u.name",
            (*ACTIVE_STATUSES, ts(now() - timedelta(days=30))))

        urgent = [dict(r, sla=sla_state(r)) for r in query(
            f"SELECT t.*, a.name AS assignee FROM tickets t LEFT JOIN users a ON a.id = t.assignee_id "
            f"WHERE t.{active} ORDER BY t.due_at LIMIT 6", ACTIVE_STATUSES)]

        charts = {
            "status": {"labels": STATUSES, "data": [by_status.get(s, 0) for s in STATUSES]},
            "category": {"labels": CATEGORIES, "data": [by_cat.get(c, 0) for c in CATEGORIES]},
            "priority": {"labels": PRIORITIES, "data": [by_pri_open.get(p, 0) for p in PRIORITIES]},
            "weekly": {"labels": weeks, "created": created, "resolved": resolved},
        }
        return render_template("dashboard.html", kpi=kpi, charts=charts, workload=workload, urgent=urgent)

    # ---------- admin ----------
    @app.route("/admin/users", methods=["GET", "POST"])
    @role_required("admin")
    def users():
        if request.method == "POST":
            uid = int(request.form.get("user_id", 0))
            role = request.form.get("role")
            if role not in ROLES:
                abort(400)
            if uid == g.user["id"] and role != "admin":
                flash("You can't remove your own admin role.", "error")
            else:
                execute("UPDATE users SET role = ? WHERE id = ?", (role, uid))
                flash("Role updated.", "success")
            return redirect(url_for("users"))
        rows = query(
            "SELECT u.*, (SELECT COUNT(*) FROM tickets t WHERE t.requester_id = u.id) submitted, "
            "(SELECT COUNT(*) FROM tickets t WHERE t.assignee_id = u.id AND t.status IN "
            "('Open','In Progress','Waiting on User')) assigned "
            "FROM users u ORDER BY CASE u.role WHEN 'admin' THEN 0 WHEN 'agent' THEN 1 ELSE 2 END, u.name")
        return render_template("users.html", users=rows, roles=ROLES)

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, msg="You don't have access to that page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, msg="That page or ticket doesn't exist."), 404

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, msg=getattr(e, "description", "Bad request.")), 400


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
