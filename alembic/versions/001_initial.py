"""Create initial tables with PostGIS

Revision ID: 001
Revises: 
Create Date: 2026-09-11

"""
import sqlalchemy as sa
from geoalchemy2 import Geography

from alembic import op

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable PostGIS extension
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis_topology")

    # Create locations table
    op.create_table(
        'locations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lon', sa.Float(), nullable=False),
        sa.Column('geom', Geography(geometry_type='POINT', srid=4326, spatial_index=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_locations_name', 'locations', ['name'], unique=False)
    op.create_index('ix_locations_created_at', 'locations', ['created_at'], unique=False)

    # Create forecast_snapshots table
    op.create_table(
        'forecast_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('raw_json', sa.JSON(), nullable=False),
        sa.Column('temp', sa.Float(), nullable=True),
        sa.Column('precip', sa.Float(), nullable=True),
        sa.Column('wind', sa.Float(), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='open-meteo'),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_forecast_snapshots_location_fetched', 'forecast_snapshots', ['location_id', 'fetched_at'], unique=False)
    op.create_index('ix_forecast_snapshots_fetched_at', 'forecast_snapshots', ['fetched_at'], unique=False)

    # Create disaster_events table
    op.create_table(
        'disaster_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('geom', Geography(geometry_type='POINT', srid=4326, spatial_index=True), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('raw_json', sa.JSON(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_disaster_events_type_severity', 'disaster_events', ['type', 'severity'], unique=False)
    op.create_index('ix_disaster_events_fetched_at', 'disaster_events', ['fetched_at'], unique=False)
    op.create_index('ix_disaster_events_source', 'disaster_events', ['source'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_disaster_events_source', table_name='disaster_events')
    op.drop_index('ix_disaster_events_fetched_at', table_name='disaster_events')
    op.drop_index('ix_disaster_events_type_severity', table_name='disaster_events')
    op.drop_table('disaster_events')
    op.drop_index('ix_forecast_snapshots_fetched_at', table_name='forecast_snapshots')
    op.drop_index('ix_forecast_snapshots_location_fetched', table_name='forecast_snapshots')
    op.drop_table('forecast_snapshots')
    op.drop_index('ix_locations_created_at', table_name='locations')
    op.drop_index('ix_locations_name', table_name='locations')
    op.drop_table('locations')
    op.execute("DROP EXTENSION IF EXISTS postgis_topology")
    op.execute("DROP EXTENSION IF EXISTS postgis")