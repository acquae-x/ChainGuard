"""Persist worker leases, retry state, and the submitted timeout budget."""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0012"
down_revision = "20260723_0011"
branch_labels = None
depends_on = None


def _add_job_columns(table: str, default_timeout: float) -> None:
    with op.batch_alter_table(table) as batch:
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
        batch.add_column(sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("timeout_seconds", sa.Float(), nullable=False, server_default=str(default_timeout)))
        batch.add_column(sa.Column("claimed_by", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("requester_id", sa.String(length=64), nullable=False, server_default=""))
        batch.create_index(f"ix_{table}_available_at", ["available_at"], unique=False)
        batch.create_index(f"ix_{table}_lease_expires_at", ["lease_expires_at"], unique=False)
    op.execute(sa.text(f"UPDATE {table} SET available_at = updated_at WHERE available_at IS NULL"))
    with op.batch_alter_table(table) as batch:
        batch.alter_column("available_at", existing_type=sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    _add_job_columns("jobs", 60.0)
    _add_job_columns("import_jobs", 30.0)


def _drop_job_columns(table: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_index(f"ix_{table}_lease_expires_at")
        batch.drop_index(f"ix_{table}_available_at")
        batch.drop_column("requester_id")
        batch.drop_column("lease_expires_at")
        batch.drop_column("claimed_by")
        batch.drop_column("timeout_seconds")
        batch.drop_column("available_at")
        batch.drop_column("max_attempts")
        batch.drop_column("attempts")


def downgrade() -> None:
    _drop_job_columns("import_jobs")
    _drop_job_columns("jobs")
