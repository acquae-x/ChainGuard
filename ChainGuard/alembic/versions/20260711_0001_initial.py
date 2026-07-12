"""初始业务表迁移：使用显式 Alembic 操作创建全部 Phase 1 表。"""

from alembic import op
import sqlalchemy as sa

revision = "20260711_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 显式创建全部 Phase 1 表与索引。
    op.create_table('approvals',
    sa.Column('proposal_id', sa.String(length=64), nullable=False),
    sa.Column('incident_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('risk_level', sa.String(length=20), nullable=False),
    sa.Column('summary', sa.String(length=255), nullable=False),
    sa.Column('cost_impact', sa.Float(), nullable=False),
    sa.Column('submitter', sa.String(length=100), nullable=False),
    sa.Column('waiting_hours', sa.Float(), nullable=False),
    sa.Column('cc_role_codes', sa.JSON(), nullable=False),
    sa.Column('transferred_to', sa.String(length=100), nullable=True),
    sa.Column('countersigned', sa.Boolean(), nullable=False),
    sa.Column('history', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_approvals_incident_id'), 'approvals', ['incident_id'], unique=False)
    op.create_index(op.f('ix_approvals_proposal_id'), 'approvals', ['proposal_id'], unique=False)
    op.create_index(op.f('ix_approvals_tenant_id'), 'approvals', ['tenant_id'], unique=False)
    op.create_table('audit_logs',
    sa.Column('time', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('user_name', sa.String(length=100), nullable=False),
    sa.Column('role_code', sa.String(length=40), nullable=False),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('target_type', sa.String(length=50), nullable=False),
    sa.Column('target_id', sa.String(length=64), nullable=False),
    sa.Column('target_name', sa.String(length=255), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_target_id'), 'audit_logs', ['target_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_target_type'), 'audit_logs', ['target_type'], unique=False)
    op.create_index(op.f('ix_audit_logs_tenant_id'), 'audit_logs', ['tenant_id'], unique=False)
    op.create_table('custom_fields',
    sa.Column('object_type', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=False),
    sa.Column('field_type', sa.String(length=30), nullable=False),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_custom_fields_object_type'), 'custom_fields', ['object_type'], unique=False)
    op.create_index(op.f('ix_custom_fields_tenant_id'), 'custom_fields', ['tenant_id'], unique=False)
    op.create_table('data_records',
    sa.Column('resource_type', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_data_records_resource_type'), 'data_records', ['resource_type'], unique=False)
    op.create_index(op.f('ix_data_records_tenant_id'), 'data_records', ['tenant_id'], unique=False)
    op.create_table('experience_cards',
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_experience_cards_tenant_id'), 'experience_cards', ['tenant_id'], unique=False)
    op.create_table('import_jobs',
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('import_type', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('options', sa.JSON(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_import_jobs_tenant_id'), 'import_jobs', ['tenant_id'], unique=False)
    op.create_table('incidents',
    sa.Column('code', sa.String(length=80), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('type', sa.String(length=60), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('owner', sa.String(length=100), nullable=False),
    sa.Column('source_risk_ids', sa.JSON(), nullable=False),
    sa.Column('loss', sa.Float(), nullable=False),
    sa.Column('cost', sa.Float(), nullable=False),
    sa.Column('notes', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_incidents_code'), 'incidents', ['code'], unique=False)
    op.create_index(op.f('ix_incidents_tenant_id'), 'incidents', ['tenant_id'], unique=False)
    op.create_table('jobs',
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('resource_id', sa.String(length=64), nullable=False),
    sa.Column('idempotency_key', sa.String(length=160), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('error_code', sa.String(length=30), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_idempotency_key'), 'jobs', ['idempotency_key'], unique=False)
    op.create_index(op.f('ix_jobs_kind'), 'jobs', ['kind'], unique=False)
    op.create_index(op.f('ix_jobs_resource_id'), 'jobs', ['resource_id'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_index(op.f('ix_jobs_tenant_id'), 'jobs', ['tenant_id'], unique=False)
    op.create_table('notification_messages',
    sa.Column('user_id', sa.String(length=64), nullable=True),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('target', sa.String(length=255), nullable=False),
    sa.Column('read', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notification_messages_tenant_id'), 'notification_messages', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_notification_messages_user_id'), 'notification_messages', ['user_id'], unique=False)
    op.create_table('proposals',
    sa.Column('incident_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('tag', sa.String(length=30), nullable=False),
    sa.Column('total_cost', sa.Float(), nullable=False),
    sa.Column('lead_time_impact', sa.Integer(), nullable=False),
    sa.Column('residual_risk', sa.String(length=20), nullable=False),
    sa.Column('customer_impact', sa.Integer(), nullable=False),
    sa.Column('high_value_customers', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('views', sa.JSON(), nullable=False),
    sa.Column('constraints', sa.JSON(), nullable=False),
    sa.Column('explanation', sa.JSON(), nullable=False),
    sa.Column('modified', sa.Boolean(), nullable=False),
    sa.Column('draft', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_proposals_incident_id'), 'proposals', ['incident_id'], unique=False)
    op.create_index(op.f('ix_proposals_tenant_id'), 'proposals', ['tenant_id'], unique=False)
    op.create_table('risks',
    sa.Column('code', sa.String(length=80), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('type', sa.String(length=50), nullable=False),
    sa.Column('object_type', sa.String(length=50), nullable=False),
    sa.Column('object_name', sa.String(length=200), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('rule', sa.String(length=255), nullable=False),
    sa.Column('found_at', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('incident_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_risks_code'), 'risks', ['code'], unique=False)
    op.create_index(op.f('ix_risks_tenant_id'), 'risks', ['tenant_id'], unique=False)
    op.create_table('tasks',
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('source', sa.String(length=100), nullable=False),
    sa.Column('incident_id', sa.String(length=64), nullable=True),
    sa.Column('assignee', sa.String(length=100), nullable=False),
    sa.Column('role_code', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('due_at', sa.String(length=40), nullable=False),
    sa.Column('priority', sa.String(length=20), nullable=False),
    sa.Column('checklist', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_incident_id'), 'tasks', ['incident_id'], unique=False)
    op.create_index(op.f('ix_tasks_tenant_id'), 'tasks', ['tenant_id'], unique=False)
    op.create_table('tenants',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('industry', sa.String(length=100), nullable=False),
    sa.Column('scale', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('plan', sa.String(length=30), nullable=False),
    sa.Column('trial_end_at', sa.String(length=40), nullable=False),
    sa.Column('demo_data_flag', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('roles',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('builtin', sa.Boolean(), nullable=False),
    sa.Column('permissions', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'code')
    )
    op.create_index(op.f('ix_roles_tenant_id'), 'roles', ['tenant_id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('account', sa.String(length=160), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('phone', sa.String(length=30), nullable=False),
    sa.Column('email', sa.String(length=160), nullable=False),
    sa.Column('dept_id', sa.String(length=64), nullable=False),
    sa.Column('role_id', sa.String(length=64), nullable=False),
    sa.Column('role_code', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('data_scope', sa.String(length=30), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'account')
    )
    op.create_index(op.f('ix_users_account'), 'users', ['account'], unique=False)
    op.create_index(op.f('ix_users_tenant_id'), 'users', ['tenant_id'], unique=False)
    # Phase 1 表与索引创建完成。


def downgrade() -> None:
    # 按依赖逆序删除全部 Phase 1 表与索引。
    op.drop_index(op.f('ix_users_tenant_id'), table_name='users')
    op.drop_index(op.f('ix_users_account'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_roles_tenant_id'), table_name='roles')
    op.drop_table('roles')
    op.drop_table('tenants')
    op.drop_index(op.f('ix_tasks_tenant_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_incident_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_risks_tenant_id'), table_name='risks')
    op.drop_index(op.f('ix_risks_code'), table_name='risks')
    op.drop_table('risks')
    op.drop_index(op.f('ix_proposals_tenant_id'), table_name='proposals')
    op.drop_index(op.f('ix_proposals_incident_id'), table_name='proposals')
    op.drop_table('proposals')
    op.drop_index(op.f('ix_notification_messages_user_id'), table_name='notification_messages')
    op.drop_index(op.f('ix_notification_messages_tenant_id'), table_name='notification_messages')
    op.drop_table('notification_messages')
    op.drop_index(op.f('ix_jobs_tenant_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_resource_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_kind'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_idempotency_key'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_incidents_tenant_id'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_code'), table_name='incidents')
    op.drop_table('incidents')
    op.drop_index(op.f('ix_import_jobs_tenant_id'), table_name='import_jobs')
    op.drop_table('import_jobs')
    op.drop_index(op.f('ix_experience_cards_tenant_id'), table_name='experience_cards')
    op.drop_table('experience_cards')
    op.drop_index(op.f('ix_data_records_tenant_id'), table_name='data_records')
    op.drop_index(op.f('ix_data_records_resource_type'), table_name='data_records')
    op.drop_table('data_records')
    op.drop_index(op.f('ix_custom_fields_tenant_id'), table_name='custom_fields')
    op.drop_index(op.f('ix_custom_fields_object_type'), table_name='custom_fields')
    op.drop_table('custom_fields')
    op.drop_index(op.f('ix_audit_logs_tenant_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_target_type'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_target_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_approvals_tenant_id'), table_name='approvals')
    op.drop_index(op.f('ix_approvals_proposal_id'), table_name='approvals')
    op.drop_index(op.f('ix_approvals_incident_id'), table_name='approvals')
    op.drop_table('approvals')
    # Phase 1 表与索引删除完成。
