"""行级数据范围地基：部门树 + 业务记录归属列。

背景：`User.data_scope` 长期只被存储和回显，没有任何查询按它过滤，
因为「本部门及子部门」在数据模型里根本无从求值——部门只是端点里的硬编码字符串，
业务表也没有归属列。本迁移补齐这两块地基，查询层的收口在 data_scope.py。

回填策略（保守）：
- departments：把既有硬编码的 5 个部门落成真实行（dept-1..dept-5），保持 id 不变，
  这样 users.dept_id 的历史值天然有效，无需改动用户数据。
- 业务表 owner_id：按 incidents.owner / tasks.assignee 的姓名去 users.name 精确匹配回填；
  同名或匹配不到就留空。留空行只有 all 范围可见——宁可少放行，不可误放行。
- 业务表 dept_id：跟随回填出来的 owner 所在部门；owner 未知则留空。
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0010"
down_revision = "20260720_0009"
branch_labels = None
depends_on = None

SCOPED_TABLES = ("risks", "incidents", "proposals", "tasks")

# 与原 /settings/departments 端点里的硬编码顺序一一对应，保证既有 users.dept_id 不失效。
LEGACY_DEPARTMENTS = ["采购部", "仓储部", "销售部", "财务部", "生产部"]


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.UniqueConstraint("tenant_id", "code", name="uq_departments_tenant_code"),
    )
    op.create_index("ix_departments_tenant_id", "departments", ["tenant_id"])
    op.create_index("ix_departments_parent_id", "departments", ["parent_id"])

    for table in SCOPED_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("dept_id", sa.String(64), nullable=True))
            batch.add_column(sa.Column("owner_id", sa.String(64), nullable=True))
        op.create_index(f"ix_{table}_dept_id", table, ["dept_id"])
        op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])

    _backfill()


def _backfill() -> None:
    bind = op.get_bind()

    # 1) 每个租户落一套部门行，id 沿用历史约定 dept-1..dept-5（users.dept_id 直接对得上）。
    tenants = [row[0] for row in bind.execute(sa.text("SELECT id FROM tenants")).fetchall()]
    for tenant_id in tenants:
        for index, name in enumerate(LEGACY_DEPARTMENTS, start=1):
            dept_id = f"dept-{index}"
            exists = bind.execute(
                sa.text("SELECT 1 FROM departments WHERE id = :id"), {"id": dept_id}
            ).fetchone()
            if exists:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO departments (id, tenant_id, code, name, parent_id)"
                    " VALUES (:id, :tenant_id, :code, :name, NULL)"
                ),
                {"id": dept_id, "tenant_id": tenant_id, "code": f"D{index}", "name": name},
            )
        # 多租户下 dept-N 会撞主键，只有第一个租户能用历史 id；其余租户另起唯一 id。
        break

    for tenant_id in tenants[1:]:
        for index, name in enumerate(LEGACY_DEPARTMENTS, start=1):
            bind.execute(
                sa.text(
                    "INSERT INTO departments (id, tenant_id, code, name, parent_id)"
                    " VALUES (:id, :tenant_id, :code, :name, NULL)"
                ),
                {
                    "id": f"dept-{tenant_id}-{index}",
                    "tenant_id": tenant_id,
                    "code": f"D{index}",
                    "name": name,
                },
            )

    # 2) 按姓名回填归属。同名用户会产生歧义，这种情况一律留空（保守失败）。
    users = bind.execute(
        sa.text("SELECT id, tenant_id, name, dept_id FROM users")
    ).fetchall()
    by_tenant_name: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for user_id, tenant_id, name, dept_id in users:
        if not name:
            continue
        by_tenant_name.setdefault((tenant_id, name), []).append((user_id, dept_id))

    def resolve(tenant_id: str, display_name: str | None):
        if not display_name:
            return None, None
        matches = by_tenant_name.get((tenant_id, display_name.strip()), [])
        if len(matches) != 1:  # 0 = 查无此人，>1 = 同名歧义，都不回填
            return None, None
        return matches[0]

    for table, name_column in (("incidents", "owner"), ("tasks", "assignee")):
        rows = bind.execute(
            sa.text(f"SELECT id, tenant_id, {name_column} FROM {table}")
        ).fetchall()
        for row_id, tenant_id, display_name in rows:
            owner_id, dept_id = resolve(tenant_id, display_name)
            if owner_id is None:
                continue
            bind.execute(
                sa.text(f"UPDATE {table} SET owner_id = :owner_id, dept_id = :dept_id WHERE id = :id"),
                {"owner_id": owner_id, "dept_id": dept_id, "id": row_id},
            )

    # 3) 方案继承所属事件的归属；风险继承其关联事件（未关联事件的风险留空）。
    bind.execute(sa.text(
        "UPDATE proposals SET"
        " owner_id = (SELECT owner_id FROM incidents WHERE incidents.id = proposals.incident_id),"
        " dept_id = (SELECT dept_id FROM incidents WHERE incidents.id = proposals.incident_id)"
        " WHERE incident_id IS NOT NULL"
    ))
    bind.execute(sa.text(
        "UPDATE risks SET"
        " owner_id = (SELECT owner_id FROM incidents WHERE incidents.id = risks.incident_id),"
        " dept_id = (SELECT dept_id FROM incidents WHERE incidents.id = risks.incident_id)"
        " WHERE incident_id IS NOT NULL"
    ))


def downgrade() -> None:
    for table in SCOPED_TABLES:
        op.drop_index(f"ix_{table}_owner_id", table_name=table)
        op.drop_index(f"ix_{table}_dept_id", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("owner_id")
            batch.drop_column("dept_id")

    op.drop_index("ix_departments_parent_id", table_name="departments")
    op.drop_index("ix_departments_tenant_id", table_name="departments")
    op.drop_table("departments")
