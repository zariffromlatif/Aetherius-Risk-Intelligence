CREATE TABLE IF NOT EXISTS operator_client_assignments (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  operator_user_id UUID NOT NULL REFERENCES operator_users(id),
  client_id UUID NOT NULL REFERENCES clients(id),
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_operator_client UNIQUE (operator_user_id, client_id)
);

CREATE INDEX IF NOT EXISTS ix_operator_client_assignments_client ON operator_client_assignments(client_id);
