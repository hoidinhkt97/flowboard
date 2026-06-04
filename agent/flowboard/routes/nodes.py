from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Account, Asset, Board, Edge, Node, Request
from flowboard.db.scoping import owned_or_404
from flowboard.deps import get_current_account
from flowboard.short_id import generate_unique_short_id

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

NodeType = Literal[
    "character",
    "image",
    "video",
    "prompt",
    "note",
    "visual_asset",
    # Storyboard = thin image-node wrapper. Backend treats it the same as
    # `image` for storage / dispatch — see frontend/src/lib/storyboardPrompt.ts
    # for the template that drives gen_image.
    "Storyboard",
]
NodeStatus = Literal["idle", "queued", "running", "done", "error"]

_COORD_MIN = -1_000_000.0
_COORD_MAX = 1_000_000.0
_SIZE_MAX = 100_000.0


class NodeCreate(BaseModel):
    board_id: int
    type: NodeType
    x: float = Field(default=0.0, ge=_COORD_MIN, le=_COORD_MAX)
    y: float = Field(default=0.0, ge=_COORD_MIN, le=_COORD_MAX)
    w: float = Field(default=240.0, gt=0, le=_SIZE_MAX)
    h: float = Field(default=160.0, gt=0, le=_SIZE_MAX)
    data: dict = {}
    status: NodeStatus = "idle"


class NodeUpdate(BaseModel):
    x: Optional[float] = Field(default=None, ge=_COORD_MIN, le=_COORD_MAX)
    y: Optional[float] = Field(default=None, ge=_COORD_MIN, le=_COORD_MAX)
    w: Optional[float] = Field(default=None, gt=0, le=_SIZE_MAX)
    h: Optional[float] = Field(default=None, gt=0, le=_SIZE_MAX)
    data: Optional[dict] = None
    status: Optional[NodeStatus] = None


@router.post("")
def create_node(body: NodeCreate, acct: Account = Depends(get_current_account)):
    with get_session() as s:
        # Verify the board exists AND belongs to this account.
        owned_or_404(s, Board, body.board_id, acct.id)
        short_id = generate_unique_short_id(s, body.board_id)
        node = Node(
            board_id=body.board_id,
            account_id=acct.id,
            short_id=short_id,
            type=body.type,
            x=body.x,
            y=body.y,
            w=body.w,
            h=body.h,
            data=body.data,
            status=body.status,
        )
        s.add(node)
        s.commit()
        s.refresh(node)
        return node


@router.patch("/{node_id}")
def update_node(node_id: int, body: NodeUpdate, acct: Account = Depends(get_current_account)):
    """Partial update.

    The `data` field is **shallow-merged** into the existing JSON
    column rather than wholesale-replaced — earlier behavior dropped
    any sibling field the caller forgot to list, which silently erased
    `aspectRatio`, `aiBrief`, and other state every time the frontend
    sent a partial update. Merge is the natural REST PATCH semantic
    and prevents that whole class of regression.

    Merge depth is **one level** — patch keys at the top level of
    `data` are merged with existing keys, but if a key's value is
    itself a dict, the new dict REPLACES the old one (no recursive
    merge). All current FlowboardNodeData fields are scalars / arrays,
    so this matches the schema. If a future field needs nested-merge
    semantics, switch to a recursive walker here and update this
    docstring.

    Sentinel: a value of `null` in the data patch deletes the key. So
    callers that want to clear `aiBrief` after a regen pass
    `{aiBrief: null}` (still merge-safe — no risk of accidentally
    nuking unrelated fields). Missing keys are preserved.

    Non-`data` fields (`x`, `y`, `w`, `h`, `status`) keep the original
    setattr-replace semantic — no merge applied.
    """
    with get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise HTTPException(404, "node not found")
        # Verify account owns the board this node belongs to.
        owned_or_404(s, Board, node.board_id, acct.id)
        patch = body.model_dump(exclude_unset=True)
        for k, v in patch.items():
            if k == "data" and isinstance(v, dict):
                merged = dict(node.data or {})
                for dk, dv in v.items():
                    if dv is None:
                        merged.pop(dk, None)
                    else:
                        merged[dk] = dv
                node.data = merged
            else:
                setattr(node, k, v)
        s.add(node)
        s.commit()
        s.refresh(node)
        return node


@router.delete("/{node_id}")
def delete_node(node_id: int, acct: Account = Depends(get_current_account)):
    """Delete a node + cascade.

    Edges are owned by the graph — delete them outright.
    Request + Asset rows are *historical* (activity feed, media cache)
    and have a nullable `node_id` FK. Detach them (set node_id=NULL)
    rather than delete, so:
      - the activity feed still shows the historical generation entries
      - saved References pointing at this node's media keep working
        (Asset row survives, and `/media/{id}` still resolves to the
        cached file on disk).

    Skipping this detach step caused a FOREIGN KEY constraint failure
    that aborted the whole transaction — the user saw the node vanish
    locally (optimistic via applyNodeChanges) but reload restored it
    because the backend never actually deleted it.
    """
    with get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise HTTPException(404, "node not found")
        # Verify account owns the board this node belongs to.
        owned_or_404(s, Board, node.board_id, acct.id)
        # Detach historical children FIRST so the FK constraint is satisfied.
        orphan_requests = s.exec(
            select(Request).where(Request.node_id == node_id)
        ).all()
        for r in orphan_requests:
            r.node_id = None
            s.add(r)
        orphan_assets = s.exec(
            select(Asset).where(Asset.node_id == node_id)
        ).all()
        for a in orphan_assets:
            a.node_id = None
            s.add(a)
        # Edges go with the node.
        edges = s.exec(
            select(Edge).where((Edge.source_id == node_id) | (Edge.target_id == node_id))
        ).all()
        for e in edges:
            s.delete(e)
        s.delete(node)
        s.commit()
        return {
            "ok": True,
            "deleted_edges": [e.id for e in edges],
            "detached_requests": len(orphan_requests),
            "detached_assets": len(orphan_assets),
        }
