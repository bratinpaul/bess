"""Keeps battery_master.asset_hierarchy in step with the master-data tables.

    tenant
    └ site                      (its primary owner in tenant_site)
      └ battery_system          (battery_system.site_id)
        ├ battery_container     (battery_container.battery_system_id)
        │ └ battery_pack        (battery_pack.container_id)
        │   └ battery_module    (battery_module.pack_id)
        ├ pcs                   (pcs.system_id)
        ├ ems_controller        (ems_controller.battery_system_id)
        └ hvac_unit             (hvac_unit.battery_system_id)

A node has its own UUID (asset_id); (asset_type, source_id) says which record it stands for:
asset_type is the table name and source_id the record's id. The routers call these helpers inside
their own transaction, so a failed save leaves the hierarchy untouched too.
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app import models

Node = models.AssetHierarchy


@dataclass(frozen=True)
class AssetSpec:
    model: type
    id_attr: str
    name_attr: str
    fallback_name: str  # used when the name column is empty, e.g. "Container 3"
    parent_type: Optional[str] = None
    parent_attr: Optional[str] = None  # column on this record holding the parent record's id


# parents come before their children (sync order)
SPECS: dict[str, AssetSpec] = {
    "tenant": AssetSpec(models.Tenant, "tenant_id", "name", "Tenant"),
    "site": AssetSpec(models.Site, "site_id", "site_name", "Site", "tenant"),  # parent: see _parent_id
    "battery_system": AssetSpec(models.BatterySystem, "battery_system_id", "system_name", "Battery system", "site", "site_id"),
    "battery_container": AssetSpec(
        models.BatteryContainer, "container_id", "container_number", "Container", "battery_system", "battery_system_id"
    ),
    "battery_pack": AssetSpec(models.BatteryPack, "pack_id", "pack_number", "Pack", "battery_container", "container_id"),
    "battery_module": AssetSpec(models.BatteryModule, "module_id", "serial_number", "Module", "battery_pack", "pack_id"),
    "pcs": AssetSpec(models.Pcs, "pcs_id", "pcs_code", "PCS", "battery_system", "system_id"),
    "ems_controller": AssetSpec(models.EmsController, "ems_id", "ems_code", "EMS", "battery_system", "battery_system_id"),
    "hvac_unit": AssetSpec(models.HvacUnit, "hvac_id", "hvac_code", "HVAC", "battery_system", "battery_system_id"),
}
ASSET_TYPES = tuple(SPECS)


class RecordNotFound(Exception):
    pass


def find_node(db: Session, asset_type: str, source_id: int) -> Optional[Node]:
    return db.query(Node).filter(Node.asset_type == asset_type, Node.source_id == source_id).one_or_none()


def _spec(asset_type: str) -> AssetSpec:
    if asset_type not in SPECS:
        raise ValueError(f"asset_type must be one of: {', '.join(ASSET_TYPES)}")
    return SPECS[asset_type]


def _parent_id(db: Session, asset_type: str, record) -> Optional[int]:
    if asset_type == "site":  # a site may have several owners; the primary one is its parent
        return (
            db.query(models.TenantSite.tenant_id)
            .filter(models.TenantSite.site_id == record.site_id, models.TenantSite.is_primary_owner.is_(True))
            .scalar()
        )
    spec = SPECS[asset_type]
    return getattr(record, spec.parent_attr) if spec.parent_attr else None


def sync_node(db: Session, asset_type: str, source_id: int) -> tuple[Node, bool]:
    """Create or refresh the node for one record (and its parent node if that is missing).

    Returns (node, created).
    """
    spec = _spec(asset_type)
    db.flush()  # the session doesn't autoflush; pending record / tenant_site changes must be visible
    record = db.get(spec.model, source_id)
    if record is None:
        raise RecordNotFound(f"{asset_type} {source_id} not found")
    parent = None
    parent_id = _parent_id(db, asset_type, record)
    if spec.parent_type and parent_id is not None:
        parent = find_node(db, spec.parent_type, parent_id) or sync_node(db, spec.parent_type, parent_id)[0]

    node = find_node(db, asset_type, source_id)
    created = node is None
    if created:
        node = Node(asset_type=asset_type, source_id=source_id)
        db.add(node)
    node.asset_name = getattr(record, spec.name_attr) or f"{spec.fallback_name} {source_id}"
    node.parent_asset_id = parent.asset_id if parent else None
    db.flush()
    db.refresh(node)  # load the generated asset_id
    return node, created


def _child_ids(db: Session, asset_type: str, source_id: int) -> list[tuple[str, int]]:
    """Records whose parent (by their own columns) is this record."""
    out: list[tuple[str, int]] = []
    if asset_type == "tenant":
        out += [("site", i) for (i,) in db.query(models.TenantSite.site_id).filter(
            models.TenantSite.tenant_id == source_id, models.TenantSite.is_primary_owner.is_(True))]
    for child_type, spec in SPECS.items():
        if spec.parent_type == asset_type and spec.parent_attr:
            id_col = getattr(spec.model, spec.id_attr)
            parent_col = getattr(spec.model, spec.parent_attr)
            out += [(child_type, i) for (i,) in db.query(id_col).filter(parent_col == source_id)]
    return out


def reattach_children(db: Session, asset_type: str, source_id: int) -> int:
    """Point existing child nodes back at this node (e.g. after it was deleted and added again)."""
    n = 0
    for child_type, child_id in _child_ids(db, asset_type, source_id):
        if find_node(db, child_type, child_id):
            sync_node(db, child_type, child_id)
            n += 1
    return n


def remove_node(db: Session, asset_type: str, source_id: int) -> bool:
    """Delete a node; the database empties the parent of its children (ON DELETE SET NULL)."""
    db.flush()
    deleted = db.query(Node).filter(Node.asset_type == asset_type, Node.source_id == source_id).delete(
        synchronize_session=False
    )
    db.expire_all()  # children's parent_asset_id changed in the database
    return bool(deleted)


def remove_nodes(db: Session, asset_type: str, source_ids: list[int]) -> None:
    """Delete several nodes, e.g. records a database cascade is about to delete."""
    if source_ids:
        db.flush()
        db.query(Node).filter(Node.asset_type == asset_type, Node.source_id.in_(source_ids)).delete(
            synchronize_session=False
        )
        db.expire_all()


def sync_all(db: Session) -> dict[str, int]:
    """Create or refresh nodes for every record of every asset type (parents first)."""
    counts = {"created": 0, "updated": 0}
    for asset_type, spec in SPECS.items():
        id_col = getattr(spec.model, spec.id_attr)
        for (source_id,) in db.query(id_col).order_by(id_col).all():
            _, created = sync_node(db, asset_type, source_id)
            counts["created" if created else "updated"] += 1
    return counts
