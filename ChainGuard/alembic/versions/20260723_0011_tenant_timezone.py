"""Persist the IANA timezone used for each tenant's calendar metrics."""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0011"
down_revision = "20260720_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # UTC is deliberately the migration default: existing tenants have no
    # trustworthy location metadata, and UTC preserves their historical KPI
    # boundaries until an administrator explicitly configures the tenant zone.
    with op.batch_alter_table("tenants") as batch:
        batch.add_column(
            sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC")
        )

    # The shipped demo tenant is the one tenant whose business locale is known.
    op.execute(
        sa.text("UPDATE tenants SET timezone = 'Asia/Shanghai' WHERE id = 'tenant-demo'")
    )


def downgrade() -> None:
    with op.batch_alter_table("tenants") as batch:
        batch.drop_column("timezone")
