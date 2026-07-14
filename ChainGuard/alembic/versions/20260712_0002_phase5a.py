"""Phase 5A trace, notification, and token-revocation persistence."""

from alembic import op
import sqlalchemy as sa

revision = "20260712_0002"
down_revision = "20260711_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "must_change_password" not in {item["name"] for item in inspector.get_columns("users")}:
        op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    existing = set(inspector.get_table_names())
    if "decision_details" not in existing:
        op.create_table("decision_details", sa.Column("incident_id", sa.String(64), nullable=False), sa.Column("job_id", sa.String(64), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("id", sa.String(64), primary_key=True), sa.Column("tenant_id", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
        for name, column in (("ix_decision_details_tenant_id", "tenant_id"), ("ix_decision_details_incident_id", "incident_id"), ("ix_decision_details_job_id", "job_id")): op.create_index(name, "decision_details", [column])
    if "decision_audits" not in existing:
        op.create_table("decision_audits", sa.Column("incident_id", sa.String(64), nullable=False), sa.Column("decision_id", sa.String(100), nullable=False), sa.Column("entry", sa.JSON(), nullable=False), sa.Column("id", sa.String(64), primary_key=True), sa.Column("tenant_id", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
        for name, column in (("ix_decision_audits_tenant_id", "tenant_id"), ("ix_decision_audits_incident_id", "incident_id"), ("ix_decision_audits_decision_id", "decision_id")): op.create_index(name, "decision_audits", [column])
    if "notification_rules" not in existing:
        op.create_table("notification_rules", sa.Column("event_type", sa.String(80), nullable=False), sa.Column("recipient_strategy", sa.JSON(), nullable=False), sa.Column("channels", sa.JSON(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("id", sa.String(64), primary_key=True), sa.Column("tenant_id", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
        for name, column in (("ix_notification_rules_tenant_id", "tenant_id"), ("ix_notification_rules_event_type", "event_type")): op.create_index(name, "notification_rules", [column])
    for table in ("revoked_tokens", "refresh_tokens"):
        if table not in existing:
            op.create_table(table, sa.Column("jti", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(64), nullable=False), sa.Column("tenant_id", sa.String(64), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
            for column in ("user_id", "tenant_id", "expires_at"): op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table, indexes in (("refresh_tokens", ["ix_refresh_tokens_expires_at", "ix_refresh_tokens_tenant_id", "ix_refresh_tokens_user_id"]), ("revoked_tokens", ["ix_revoked_tokens_expires_at", "ix_revoked_tokens_tenant_id", "ix_revoked_tokens_user_id"]), ("notification_rules", ["ix_notification_rules_event_type", "ix_notification_rules_tenant_id"]), ("decision_audits", ["ix_decision_audits_decision_id", "ix_decision_audits_incident_id", "ix_decision_audits_tenant_id"]), ("decision_details", ["ix_decision_details_job_id", "ix_decision_details_incident_id", "ix_decision_details_tenant_id"])):
        for index in indexes: op.drop_index(index, table_name=table)
        op.drop_table(table)
    op.drop_column("users", "must_change_password")
