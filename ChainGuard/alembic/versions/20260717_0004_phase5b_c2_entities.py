"""Phase 5B / C2 第一批：8 张结构化业务实体表（7 业务表 + tenant_configs）。

本批次必须成立的约束：
- 所有新表含 id/tenant_id/extra/created_at/updated_at，tenant_id 建索引；
- 租户内业务唯一键；跨业务表关联为 tenant-aware 复合外键（含 tenant_id）；
- tenant_configs 同一 (tenant, config_type) 只能一个 active 版本：部分唯一索引
  （SQLite/PostgreSQL 均支持）+ 仓储层事务校验双保险；
- downgrade 仅删除这 8 张新表，不触碰 data_records（只读迁移源留待后续 C2 落表）。
"""

from alembic import op
import sqlalchemy as sa

revision = "20260717_0004"
down_revision = "20260713_0003"
branch_labels = None
depends_on = None

def _common_columns() -> tuple[sa.Column, ...]:
    """Return fresh Column objects for each table.

    SQLAlchemy Column instances are table-owned and must not be reused between
    ``op.create_table`` calls.  Server defaults also keep raw SQL/data-migration
    inserts aligned with the ORM defaults.
    """
    return (
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "materials",
        sa.Column("material_id", sa.String(length=64), nullable=False),
        sa.Column("material_name", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("daily_consumption", sa.Float(), nullable=True),
        sa.Column("unit_cost", sa.Float(), nullable=True),
        sa.Column("is_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "material_id", name="uq_materials_biz"),
    )
    op.create_index(op.f("ix_materials_tenant_id"), "materials", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_materials_material_id"), "materials", ["material_id"], unique=False)

    op.create_table(
        "suppliers",
        sa.Column("supplier_id", sa.String(length=64), nullable=False),
        sa.Column("supplier_name", sa.String(length=200), nullable=True),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=120), nullable=True),
        sa.Column("reliability_score", sa.Float(), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "supplier_id", name="uq_suppliers_biz"),
    )
    op.create_index(op.f("ix_suppliers_tenant_id"), "suppliers", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_suppliers_supplier_id"), "suppliers", ["supplier_id"], unique=False)

    op.create_table(
        "customers",
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("customer_level", sa.String(length=16), nullable=True),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("contract", sa.String(length=120), nullable=True),
        sa.Column("owner", sa.String(length=120), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "customer_id", name="uq_customers_biz"),
    )
    op.create_index(op.f("ix_customers_tenant_id"), "customers", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_customers_customer_id"), "customers", ["customer_id"], unique=False)

    op.create_table(
        "tenant_configs",
        sa.Column("config_type", sa.String(length=60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("source", sa.String(length=30), nullable=False, server_default=sa.text("'expert'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "config_type", "version", name="uq_tenant_configs_version"),
        sa.CheckConstraint("version > 0", name="ck_tenant_configs_version_positive"),
        sa.CheckConstraint("source IN ('expert', 'calibrated')", name="ck_tenant_configs_source"),
    )
    op.create_index(op.f("ix_tenant_configs_tenant_id"), "tenant_configs", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tenant_configs_config_type"), "tenant_configs", ["config_type"], unique=False)
    op.create_index(
        "uq_tenant_config_active",
        "tenant_configs",
        ["tenant_id", "config_type"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "supplier_materials",
        sa.Column("supplier_material_id", sa.String(length=64), nullable=False),
        sa.Column("supplier_id", sa.String(length=64), nullable=False),
        sa.Column("material_id", sa.String(length=64), nullable=False),
        sa.Column("qualified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("supplier_rank", sa.Integer(), nullable=True),
        sa.Column("available_emergency_qty", sa.Float(), nullable=True),
        sa.Column("lead_time_hours", sa.Float(), nullable=True),
        sa.Column("emergency_cost_multiplier", sa.Float(), nullable=True),
        sa.Column("supplier_price", sa.Float(), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "supplier_id", "material_id", name="uq_supplier_materials_biz"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.supplier_id"], name="fk_supplier_materials_supplier"),
        sa.ForeignKeyConstraint(["tenant_id", "material_id"], ["materials.tenant_id", "materials.material_id"], name="fk_supplier_materials_material"),
    )
    op.create_index(op.f("ix_supplier_materials_tenant_id"), "supplier_materials", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_supplier_materials_supplier_material_id"), "supplier_materials", ["supplier_material_id"], unique=False)

    op.create_table(
        "sales_orders",
        sa.Column("sales_order_id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("order_status", sa.String(length=60), nullable=True),
        sa.Column("promised_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_amount", sa.Float(), nullable=True),
        sa.Column("gross_profit", sa.Float(), nullable=True),
        sa.Column("penalty_cost", sa.Float(), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "sales_order_id", name="uq_sales_orders_biz"),
        sa.ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.customer_id"], name="fk_sales_orders_customer"),
    )
    op.create_index(op.f("ix_sales_orders_tenant_id"), "sales_orders", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_sales_orders_sales_order_id"), "sales_orders", ["sales_order_id"], unique=False)

    op.create_table(
        "sales_order_lines",
        sa.Column("sales_order_line_id", sa.String(length=64), nullable=False),
        sa.Column("sales_order_id", sa.String(length=64), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.String(length=64), nullable=False),
        sa.Column("ordered_qty", sa.Float(), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "sales_order_id", "line_no", name="uq_sales_order_lines_biz"),
        sa.ForeignKeyConstraint(["tenant_id", "sales_order_id"], ["sales_orders.tenant_id", "sales_orders.sales_order_id"], name="fk_sales_order_lines_order"),
        sa.ForeignKeyConstraint(["tenant_id", "material_id"], ["materials.tenant_id", "materials.material_id"], name="fk_sales_order_lines_material"),
    )
    op.create_index(op.f("ix_sales_order_lines_tenant_id"), "sales_order_lines", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_sales_order_lines_sales_order_line_id"), "sales_order_lines", ["sales_order_line_id"], unique=False)

    op.create_table(
        "inventory",
        sa.Column("inventory_id", sa.String(length=64), nullable=False),
        sa.Column("material_id", sa.String(length=64), nullable=False),
        sa.Column("warehouse_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_name", sa.String(length=200), nullable=True),
        sa.Column("on_hand_qty", sa.Float(), nullable=True),
        sa.Column("available_qty", sa.Float(), nullable=True),
        sa.Column("safety_stock_qty", sa.Float(), nullable=True),
        sa.Column("in_transit_qty", sa.Float(), nullable=True),
        sa.Column("planned_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_arrival_at", sa.DateTime(timezone=True), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "inventory_id", name="uq_inventory_biz"),
        sa.ForeignKeyConstraint(["tenant_id", "material_id"], ["materials.tenant_id", "materials.material_id"], name="fk_inventory_material"),
    )
    op.create_index(op.f("ix_inventory_tenant_id"), "inventory", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_inventory_inventory_id"), "inventory", ["inventory_id"], unique=False)


def downgrade() -> None:
    # 反向删除：先删子表（含 FK），再删父表；不触碰 data_records。
    op.drop_table("inventory")
    op.drop_table("sales_order_lines")
    op.drop_table("sales_orders")
    op.drop_table("supplier_materials")
    op.drop_index("uq_tenant_config_active", table_name="tenant_configs")
    op.drop_table("tenant_configs")
    op.drop_table("customers")
    op.drop_table("suppliers")
    op.drop_table("materials")
