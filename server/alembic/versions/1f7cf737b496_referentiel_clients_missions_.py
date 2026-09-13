"""referentiel : clients, missions facturables, affectations avec TJM

Revision ID: 1f7cf737b496
Revises: d4a1c9f7b311
Create Date: 2026-09-13 15:26:30.391383

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '1f7cf737b496'
down_revision: Union[str, Sequence[str], None] = 'd4a1c9f7b311'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Cree le referentiel clients et enrichit missions et affectations.

    Migration additive : aucune colonne existante n'est touchee. Les trois
    colonnes non nulles ajoutees a `project` recoivent un server_default,
    sans quoi l'ajout echouerait sur les 13 lignes deja presentes.
    """
    op.create_table(
        "client",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("siren", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("contact_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("contact_email", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("client", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_client_name"), ["name"], unique=True)

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("code", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column("client_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("billable", sa.Boolean(), nullable=False, server_default=sa.text("1"))
        )
        batch_op.add_column(sa.Column("start_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("end_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("sold_days", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "status",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="active",
            )
        )
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch_op.create_unique_constraint("uq_project_code", ["code"])
        batch_op.create_foreign_key("fk_project_client", "client", ["client_id"], ["id"])

    # Reprise des donnees : seules les activites internes ne sont pas
    # facturables. Les formations sont vendues a des clients (Simplon, Ynov)
    # et comptent donc comme production.
    op.execute("UPDATE project SET billable = 0 WHERE category = 'Interne'")

    with op.batch_alter_table("userprojectlink", schema=None) as batch_op:
        batch_op.add_column(sa.Column("daily_rate", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("start_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("end_date", sa.Date(), nullable=True))


def downgrade() -> None:
    """Retire le referentiel. Les valeurs saisies dans ces colonnes sont perdues."""
    with op.batch_alter_table("userprojectlink", schema=None) as batch_op:
        batch_op.drop_column("end_date")
        batch_op.drop_column("start_date")
        batch_op.drop_column("daily_rate")

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint("fk_project_client", type_="foreignkey")
        batch_op.drop_constraint("uq_project_code", type_="unique")
        for colonne in (
            "created_at", "status", "sold_days", "end_date",
            "start_date", "billable", "client_id", "code",
        ):
            batch_op.drop_column(colonne)

    with op.batch_alter_table("client", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_client_name"))
    op.drop_table("client")
