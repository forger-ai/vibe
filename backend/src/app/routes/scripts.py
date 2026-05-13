from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import Script, utcnow
from app.routes.common import get_or_404
from app.schemas import ScriptCreate, ScriptUpdate
from app.services.scripts import (
    delete_script_files,
    move_script_files,
    normalize_script_language,
    read_script_env,
    read_script_source,
    slugify_script,
    write_script_files,
)

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


@router.get("")
def list_scripts(session: Session = Depends(get_session)) -> list[dict]:
    scripts = session.exec(select(Script).order_by(Script.name)).all()
    return [_payload(script) for script in scripts]


@router.get("/{script_id}")
def get_script(script_id: str, session: Session = Depends(get_session)) -> dict:
    return _payload(get_or_404(session, Script, script_id))


@router.post("")
def create_script(payload: ScriptCreate, session: Session = Depends(get_session)) -> dict:
    slug = slugify_script(payload.slug or payload.name)
    _ensure_slug_available(session, slug)
    script = Script(
        name=payload.name,
        slug=slug,
        description=payload.description,
        language=normalize_script_language(payload.language),
        main_task_md=payload.main_task_md,
        metadata_json=payload.metadata_json,
    )
    session.add(script)
    session.commit()
    session.refresh(script)
    write_script_files(script, payload.source_code, payload.env_text)
    return _payload(script)


@router.patch("/{script_id}")
def update_script(script_id: str, payload: ScriptUpdate, session: Session = Depends(get_session)) -> dict:
    script = get_or_404(session, Script, script_id)
    updates = payload.model_dump(exclude_unset=True)
    old_slug = script.slug
    if "slug" in updates and updates["slug"] is not None:
        next_slug = slugify_script(updates["slug"])
        if next_slug != script.slug:
            _ensure_slug_available(session, next_slug)
            script.slug = next_slug
    if "name" in updates and updates["name"] is not None:
        script.name = updates["name"]
    if "description" in updates:
        script.description = updates["description"]
    if "language" in updates and updates["language"] is not None:
        script.language = normalize_script_language(updates["language"])
    if "main_task_md" in updates and updates["main_task_md"] is not None:
        script.main_task_md = updates["main_task_md"]
    if "metadata_json" in updates and updates["metadata_json"] is not None:
        script.metadata_json = updates["metadata_json"]
    script.updated_at = utcnow()
    session.add(script)
    session.commit()
    session.refresh(script)
    move_script_files(old_slug, script)
    write_script_files(script, updates.get("source_code"), updates.get("env_text"))
    return _payload(script)


@router.delete("/{script_id}", status_code=204)
def delete_script(script_id: str, session: Session = Depends(get_session)) -> None:
    script = get_or_404(session, Script, script_id)
    delete_script_files(script)
    session.delete(script)
    session.commit()


def _payload(script: Script) -> dict:
    return {
        "id": script.id,
        "name": script.name,
        "slug": script.slug,
        "description": script.description,
        "language": script.language,
        "main_task_md": script.main_task_md,
        "metadata_json": script.metadata_json,
        "source_code": read_script_source(script),
        "env_text": read_script_env(script),
        "created_at": script.created_at.isoformat(),
        "updated_at": script.updated_at.isoformat(),
    }


def _ensure_slug_available(session: Session, slug: str) -> None:
    existing = session.exec(select(Script).where(Script.slug == slug)).first()
    if existing:
        raise ValueError("script slug already exists")
