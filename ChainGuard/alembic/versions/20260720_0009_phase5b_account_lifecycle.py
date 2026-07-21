"""Phase 5B 收尾批：账户完善（找回密码 / 邀请码 / OIDC SSO / 账号级锁定）。"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0009"
down_revision = "20260719_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("sso_subject", sa.String(255), nullable=False, server_default=""))

    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("mode", sa.String(20), nullable=False, server_default="manual_admin"),
        sa.Column("channel", sa.String(20), nullable=False, server_default="none"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("request_ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_reset_requests_tenant_id", "password_reset_requests", ["tenant_id"])
    op.create_index("ix_password_reset_requests_user_id", "password_reset_requests", ["user_id"])
    op.create_index("ix_password_reset_requests_token_hash", "password_reset_requests", ["token_hash"])
    op.create_index("ix_password_reset_requests_status", "password_reset_requests", ["status"])
    op.create_index("ix_password_reset_requests_expires_at", "password_reset_requests", ["expires_at"])

    op.create_table(
        "invitation_codes",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("code_prefix", sa.String(8), nullable=False, server_default=""),
        sa.Column("role_id", sa.String(64), nullable=False),
        sa.Column("role_code", sa.String(40), nullable=False),
        sa.Column("dept_id", sa.String(64), nullable=False, server_default="dept-1"),
        sa.Column("data_scope", sa.String(30), nullable=False, server_default="custom"),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("revoked_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_invitation_codes_code_hash"),
    )
    op.create_index("ix_invitation_codes_tenant_id", "invitation_codes", ["tenant_id"])
    op.create_index("ix_invitation_codes_code_hash", "invitation_codes", ["code_hash"])
    op.create_index("ix_invitation_codes_status", "invitation_codes", ["status"])
    op.create_index("ix_invitation_codes_expires_at", "invitation_codes", ["expires_at"])

    op.create_table(
        "invitation_redemptions",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("invitation_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("user_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("role_code", sa.String(40), nullable=False, server_default=""),
        sa.Column("request_ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invitation_redemptions_tenant_id", "invitation_redemptions", ["tenant_id"])
    op.create_index("ix_invitation_redemptions_invitation_id", "invitation_redemptions", ["invitation_id"])
    op.create_index("ix_invitation_redemptions_user_id", "invitation_redemptions", ["user_id"])

    op.create_table(
        "sso_configs",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("issuer", sa.String(255), nullable=False, server_default=""),
        sa.Column("client_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("authorization_endpoint", sa.String(500), nullable=False, server_default=""),
        sa.Column("token_endpoint", sa.String(500), nullable=False, server_default=""),
        sa.Column("redirect_uri", sa.String(500), nullable=False, server_default=""),
        sa.Column("scopes", sa.String(200), nullable=False, server_default="openid email profile"),
        sa.Column("email_claim", sa.String(80), nullable=False, server_default="email"),
        sa.Column("subject_claim", sa.String(80), nullable=False, server_default="sub"),
        sa.Column("allowed_domains", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("auto_provision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_role_code", sa.String(40), nullable=False, server_default="auditor"),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
    )

    op.create_table(
        "sso_login_states",
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("redirect_uri", sa.String(500), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("state"),
    )
    op.create_index("ix_sso_login_states_tenant_id", "sso_login_states", ["tenant_id"])
    op.create_index("ix_sso_login_states_expires_at", "sso_login_states", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_sso_login_states_expires_at", table_name="sso_login_states")
    op.drop_index("ix_sso_login_states_tenant_id", table_name="sso_login_states")
    op.drop_table("sso_login_states")
    op.drop_table("sso_configs")
    op.drop_index("ix_invitation_redemptions_user_id", table_name="invitation_redemptions")
    op.drop_index("ix_invitation_redemptions_invitation_id", table_name="invitation_redemptions")
    op.drop_index("ix_invitation_redemptions_tenant_id", table_name="invitation_redemptions")
    op.drop_table("invitation_redemptions")
    op.drop_index("ix_invitation_codes_expires_at", table_name="invitation_codes")
    op.drop_index("ix_invitation_codes_status", table_name="invitation_codes")
    op.drop_index("ix_invitation_codes_code_hash", table_name="invitation_codes")
    op.drop_index("ix_invitation_codes_tenant_id", table_name="invitation_codes")
    op.drop_table("invitation_codes")
    op.drop_index("ix_password_reset_requests_expires_at", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_status", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_token_hash", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_user_id", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_tenant_id", table_name="password_reset_requests")
    op.drop_table("password_reset_requests")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("sso_subject")
        batch.drop_column("last_failed_login_at")
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_count")
