"""Phase 5B E-3 tenant-scoped experience lifecycle."""

from alembic import op
import sqlalchemy as sa


revision = "20260719_0006"
down_revision = "20260718_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("experience_cards") as batch:
        batch.add_column(sa.Column("source_job_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("source_incident_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("source_proposal_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("dedupe_key", sa.String(160), nullable=True))
        batch.add_column(sa.Column("outcome", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("references", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.create_unique_constraint("uq_experience_cards_tenant_source_job", ["tenant_id", "source_job_id"])
    for name, columns in (("source_job_id", ["source_job_id"]), ("source_incident_id", ["source_incident_id"]), ("source_proposal_id", ["source_proposal_id"]), ("dedupe_key", ["dedupe_key"])):
        op.create_index(f"ix_experience_cards_{name}", "experience_cards", columns)


def downgrade() -> None:
    for name in ("dedupe_key", "source_proposal_id", "source_incident_id", "source_job_id"):
        op.drop_index(f"ix_experience_cards_{name}", table_name="experience_cards")
    with op.batch_alter_table("experience_cards") as batch:
        batch.drop_constraint("uq_experience_cards_tenant_source_job", type_="unique")
        batch.drop_column("references")
        batch.drop_column("metrics")
        batch.drop_column("outcome")
        batch.drop_column("dedupe_key")
        batch.drop_column("source_proposal_id")
        batch.drop_column("source_incident_id")
        batch.drop_column("source_job_id")
