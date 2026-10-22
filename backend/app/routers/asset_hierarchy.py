import re
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth.tenant_scope import principal_of
from app.database import get_db
from app.hierarchy import ASSET_TYPES, find_node, reattach_children, RecordNotFound, remove_node, sync_all, sync_node

router = APIRouter(prefix="/api/asset-hierarchy", tags=["asset-hierarchy"])

Node = models.AssetHierarchy

# nodes are addressed by the record they stand for: /{asset_type}/{source_id}


def _check_type(asset_type: str) -> None:
    if asset_type not in ASSET_TYPES:
        raise HTTPException(status_code=422, detail=f"asset_type must be one of: {', '.join(ASSET_TYPES)}")


def _all(db: Session) -> dict[UUID, Node]:
    return {n.asset_id: n for n in db.query(Node)}


def _scoped(nodes: dict[UUID, Node], request: Request) -> dict[UUID, Node]:
    """A tenant-scoped caller (Tenant Viewer) sees only its tenant's node and everything under it."""
    p = principal_of(request)
    if p is None or p.tenant_id is None:
        return nodes
    keep = {a for a, n in nodes.items() if n.asset_type == "tenant" and n.source_id == p.tenant_id}
    frontier = set(keep)
    while frontier:
        frontier = {a for a, n in nodes.items() if n.parent_asset_id in frontier and a not in keep}
        keep |= frontier
    return {a: n for a, n in nodes.items() if a in keep}


def _child_counts(nodes: dict[UUID, Node]) -> dict[UUID, int]:
    counts: dict[UUID, int] = {}
    for n in nodes.values():
        if n.parent_asset_id:
            counts[n.parent_asset_id] = counts.get(n.parent_asset_id, 0) + 1
    return counts


def _out(n: Node, nodes: dict[UUID, Node], counts: dict[UUID, int]) -> schemas.AssetNodeOut:
    out = schemas.AssetNodeOut.model_validate(n)
    parent = nodes.get(n.parent_asset_id) if n.parent_asset_id else None
    if parent:
        out.parent_asset_type = parent.asset_type
        out.parent_source_id = parent.source_id
        out.parent_name = parent.asset_name
    out.child_count = counts.get(n.asset_id, 0)
    return out


_TYPE_ORDER = {t: i for i, t in enumerate(ASSET_TYPES)}


def _natural(text: str) -> list:
    """'MODULE-2' before 'MODULE-10'."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text.lower())]


def _sort_key(n: Node):
    return (_TYPE_ORDER.get(n.asset_type, 99), _natural(n.asset_name or ""), n.source_id)


@router.get("", response_model=list[schemas.AssetNodeOut])
def list_nodes(
    request: Request,
    asset_type: Optional[str] = None,
    parent_asset_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
):
    """Flat list of nodes, optionally filtered by type and/or parent node."""
    nodes = _scoped(_all(db), request)
    counts = _child_counts(nodes)
    rows = [
        n for n in nodes.values()
        if (asset_type is None or n.asset_type == asset_type)
        and (parent_asset_id is None or n.parent_asset_id == parent_asset_id)
    ]
    return [_out(n, nodes, counts) for n in sorted(rows, key=_sort_key)]


@router.get("/tree", response_model=list[schemas.AssetTreeNode])
def get_tree(request: Request, db: Session = Depends(get_db)):
    """Nested tree from the root nodes (nodes without a parent) down."""
    nodes = _scoped(_all(db), request)
    children: dict[Optional[UUID], list[Node]] = {}
    for n in sorted(nodes.values(), key=_sort_key):
        parent = n.parent_asset_id if n.parent_asset_id in nodes else None
        children.setdefault(parent, []).append(n)

    def build(n: Node) -> schemas.AssetTreeNode:
        return schemas.AssetTreeNode(
            asset_id=n.asset_id,
            asset_type=n.asset_type,
            source_id=n.source_id,
            asset_name=n.asset_name,
            external_id=n.external_id,
            children=[build(c) for c in children.get(n.asset_id, [])],
        )

    return [build(n) for n in children.get(None, [])]


@router.post("/sync", response_model=schemas.AssetSyncResult)
def sync_existing(db: Session = Depends(get_db)):
    """Create (or refresh) the nodes for every existing record of every asset type."""
    result = sync_all(db)
    db.commit()
    return result


@router.get("/{asset_type}/{source_id}", response_model=schemas.AssetNodeDetail)
def get_node(asset_type: str, source_id: int, request: Request, db: Session = Depends(get_db)):
    """One node with its path up to the root and its direct children."""
    _check_type(asset_type)
    node = find_node(db, asset_type, source_id)
    nodes = _scoped(_all(db), request)
    if not node or node.asset_id not in nodes:
        raise HTTPException(status_code=404, detail="Asset not found in the hierarchy")
    counts = _child_counts(nodes)
    out = schemas.AssetNodeDetail(**_out(node, nodes, counts).model_dump())
    ancestors, parent_id = [], node.parent_asset_id
    while parent_id in nodes and len(ancestors) < 10:
        ancestors.insert(0, _out(nodes[parent_id], nodes, counts))
        parent_id = nodes[parent_id].parent_asset_id
    out.ancestors = ancestors
    out.children = [
        _out(n, nodes, counts) for n in sorted(nodes.values(), key=_sort_key) if n.parent_asset_id == node.asset_id
    ]
    return out


@router.post("", response_model=schemas.AssetNodeOut, status_code=201)
def add_node(payload: schemas.AssetNodeCreate, db: Session = Depends(get_db)):
    """Add the node for an existing record (e.g. one created before the hierarchy was kept)."""
    if find_node(db, payload.asset_type, payload.source_id):
        raise HTTPException(status_code=409, detail="This asset is already in the hierarchy")
    try:
        node, _ = sync_node(db, payload.asset_type, payload.source_id)
        reattach_children(db, payload.asset_type, payload.source_id)
    except RecordNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    db.commit()
    nodes = _all(db)
    return _out(nodes[node.asset_id], nodes, _child_counts(nodes))


@router.delete("/{asset_type}/{source_id}", status_code=204)
def delete_node(asset_type: str, source_id: int, db: Session = Depends(get_db)):
    """Remove a node (the record itself stays); its children are left without a parent."""
    _check_type(asset_type)
    if not remove_node(db, asset_type, source_id):
        raise HTTPException(status_code=404, detail="Asset not found in the hierarchy")
    db.commit()
    return None
