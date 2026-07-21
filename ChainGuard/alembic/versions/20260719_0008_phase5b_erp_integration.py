"""Phase 5B E01/E02 tenant-scoped encrypted ERP integration configuration."""

from alembic import op
import sqlalchemy as sa


revision = "20260719_0008"
down_revision = "20260719_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_integration_configs",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("credential_ciphertext", sa.Text(), nullable=True),
        sa.Column("connection_params", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(30), nullable=False, server_default="not_tested"),
        sa.Column("last_test_error", sa.String(255), nullable=True),
        sa.Column("available_resources", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_erp_integration_configs_tenant"),
    )
    op.create_index("ix_erp_integration_configs_tenant_id", "erp_integration_configs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_erp_integration_configs_tenant_id", table_name="erp_integration_configs")
    op.drop_table("erp_integration_configs")
