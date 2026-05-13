from __future__ import annotations

from typing import TypeVar

from fastapi import HTTPException
from sqlmodel import Session

T = TypeVar("T")


def get_or_404(session: Session, model: type[T], item_id: str) -> T:
    item = session.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not_found")
    return item
