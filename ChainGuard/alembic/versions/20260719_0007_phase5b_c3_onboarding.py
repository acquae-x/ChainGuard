"""Phase 5B C3 tenant-scoped onboarding resume state."""

from alembic import op
import sqlalchemy as sa


revision = "20260719_0007"
down_revision = "20260719_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarding_states",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_step", sa.String(40), nullable=False, server_default="welcome"),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("progress", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_onboarding_states_tenant"),
    )
    op.create_index("ix_onboarding_states_tenant_id", "onboarding_states", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_onboarding_states_tenant_id", table_name="onboarding_states")
    op.drop_table("onboarding_states")
