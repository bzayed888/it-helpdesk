-- IT Helpdesk schema (SQLite)
DROP TABLE IF EXISTS activity;
DROP TABLE IF EXISTS comments;
DROP TABLE IF EXISTS tickets;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    department    TEXT    NOT NULL DEFAULT 'General',
    role          TEXT    NOT NULL DEFAULT 'employee'
                  CHECK (role IN ('employee', 'agent', 'admin')),
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE tickets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL,
    description  TEXT    NOT NULL,
    category     TEXT    NOT NULL
                 CHECK (category IN ('Hardware', 'Software', 'Network', 'Account & Access', 'Other')),
    priority     TEXT    NOT NULL
                 CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
    status       TEXT    NOT NULL DEFAULT 'Open'
                 CHECK (status IN ('Open', 'In Progress', 'Waiting on User', 'Resolved', 'Closed')),
    requester_id INTEGER NOT NULL REFERENCES users(id),
    assignee_id  INTEGER REFERENCES users(id),
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    due_at       TEXT    NOT NULL,
    resolved_at  TEXT
);

CREATE TABLE comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_id  INTEGER NOT NULL REFERENCES users(id),
    body       TEXT    NOT NULL,
    internal   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);

CREATE TABLE activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    actor_id   INTEGER NOT NULL REFERENCES users(id),
    action     TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE INDEX idx_tickets_status   ON tickets(status);
CREATE INDEX idx_tickets_assignee ON tickets(assignee_id);
CREATE INDEX idx_tickets_requester ON tickets(requester_id);
CREATE INDEX idx_comments_ticket  ON comments(ticket_id);
CREATE INDEX idx_activity_ticket  ON activity(ticket_id);
