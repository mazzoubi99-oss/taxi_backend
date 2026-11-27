BEGIN;

CREATE TABLE IF NOT EXISTS account_deletion_requests (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    requested_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
