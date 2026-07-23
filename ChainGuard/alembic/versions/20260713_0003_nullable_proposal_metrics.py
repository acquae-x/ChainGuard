"""P0-2/P1-10：方案业务指标可空 + 审批引用方案归档保留。

- proposals.total_cost / lead_time_impact / residual_risk / customer_impact /
  high_value_customers 与 approvals.cost_impact 改为可空（未知≠0）；
- proposals 增加 archived 列（重新推演时被审批引用的旧方案归档保留，满足审计追溯）；
- downgrade 时先把 NULL 归一化为旧默认值再收紧约束，保证 up→down→up 可实测。
"""

from alembic import op
import sqlalchemy as sa

revision = "20260713_0003"
down_revision = "20260712_0002"
branch_labels = None
depends_on = None

PROPOSAL_COLUMNS = (
    ("total_cost", sa.Float(), sa.text("0")),
    ("lead_time_impact", sa.Integer(), sa.text("0")),
    ("residual_risk", sa.String(20), sa.text("'medium'")),
    ("customer_impact", sa.Integer(), sa.text("0")),
    ("high_value_customers", sa.Integer(), sa.text("0")),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("proposals")}
    with op.batch_alter_table("proposals") as batch:
        for name, type_, _default in PROPOSAL_COLUMNS:
            batch.alter_column(name, existing_type=type_, nullable=True)
        if "archived" not in columns:
            batch.add_column(sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("approvals") as batch:
        batch.alter_column("cost_impact", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    proposals = sa.table("proposals", *(sa.column(name) for name, _type, _default in PROPOSAL_COLUMNS))
    for name, _type, default in PROPOSAL_COLUMNS:
        op.execute(proposals.update().where(sa.column(name).is_(None)).values({name: default}))
    approvals = sa.table("approvals", sa.column("cost_impact"))
    op.execute(approvals.update().where(sa.column("cost_impact").is_(None)).values(cost_impact=sa.text("0")))
    with op.batch_alter_table("proposals") as batch:
        for name, type_, _default in PROPOSAL_COLUMNS:
            batch.alter_column(name, existing_type=type_, nullable=False)
        batch.drop_column("archived")
    with op.batch_alter_table("approvals") as batch:
        batch.alter_column("cost_impact", existing_type=sa.Float(), nullable=False)
