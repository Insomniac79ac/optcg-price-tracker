from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CardTag, CollectionItemGroup, CollectionItemTag, CollectorGroup, CollectorTag
from app.schemas import (
    CollectorGroupCreateIn,
    CollectorGroupOut,
    CollectorGroupUpdateIn,
    CollectorTagCreateIn,
    CollectorTagOut,
    CollectorTagUpdateIn,
)
from app.services.collector import generate_unique_slug, validate_color

router = APIRouter(prefix="/collector", tags=["collector"])


def _get_tag_or_404(db: Session, tag_id: int) -> CollectorTag:
    tag = db.get(CollectorTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


def _get_group_or_404(db: Session, group_id: int) -> CollectorGroup:
    group = db.get(CollectorGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


def _validated_color_or_400(color: str | None) -> str | None:
    try:
        return validate_color(color)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- tags --------------------------------------------------------------


@router.get("/tags", response_model=list[CollectorTagOut])
def list_tags(db: Session = Depends(get_db)):
    return db.scalars(select(CollectorTag).order_by(CollectorTag.name)).all()


@router.post("/tags", response_model=CollectorTagOut, status_code=201)
def create_tag(body: CollectorTagCreateIn, db: Session = Depends(get_db)):
    color = _validated_color_or_400(body.color)

    existing = db.scalar(select(CollectorTag).where(CollectorTag.name == body.name))
    if existing is not None:
        raise HTTPException(status_code=409, detail="A tag with this name already exists")

    tag = CollectorTag(
        name=body.name,
        slug=generate_unique_slug(db, CollectorTag, body.name),
        color=color,
        description=body.description,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.patch("/tags/{tag_id}", response_model=CollectorTagOut)
def update_tag(tag_id: int, body: CollectorTagUpdateIn, db: Session = Depends(get_db)):
    tag = _get_tag_or_404(db, tag_id)
    updates = body.model_dump(exclude_unset=True)

    if "color" in updates:
        updates["color"] = _validated_color_or_400(updates["color"])

    if "name" in updates and updates["name"] != tag.name:
        existing = db.scalar(
            select(CollectorTag).where(
                CollectorTag.name == updates["name"], CollectorTag.id != tag_id
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="A tag with this name already exists")
        updates["slug"] = generate_unique_slug(db, CollectorTag, updates["name"], exclude_id=tag_id)

    for field, value in updates.items():
        setattr(tag, field, value)

    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = _get_tag_or_404(db, tag_id)
    db.execute(delete(CardTag).where(CardTag.tag_id == tag_id))
    db.execute(delete(CollectionItemTag).where(CollectionItemTag.tag_id == tag_id))
    db.delete(tag)
    db.commit()
    return None


# --- groups --------------------------------------------------------------


@router.get("/groups", response_model=list[CollectorGroupOut])
def list_groups(db: Session = Depends(get_db)):
    return db.scalars(
        select(CollectorGroup).order_by(CollectorGroup.sort_order, CollectorGroup.name)
    ).all()


@router.post("/groups", response_model=CollectorGroupOut, status_code=201)
def create_group(body: CollectorGroupCreateIn, db: Session = Depends(get_db)):
    existing = db.scalar(select(CollectorGroup).where(CollectorGroup.name == body.name))
    if existing is not None:
        raise HTTPException(status_code=409, detail="A group with this name already exists")

    group = CollectorGroup(
        name=body.name,
        slug=generate_unique_slug(db, CollectorGroup, body.name),
        description=body.description,
        sort_order=body.sort_order,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.patch("/groups/{group_id}", response_model=CollectorGroupOut)
def update_group(group_id: int, body: CollectorGroupUpdateIn, db: Session = Depends(get_db)):
    group = _get_group_or_404(db, group_id)
    updates = body.model_dump(exclude_unset=True)

    if "name" in updates and updates["name"] != group.name:
        existing = db.scalar(
            select(CollectorGroup).where(
                CollectorGroup.name == updates["name"], CollectorGroup.id != group_id
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="A group with this name already exists")
        updates["slug"] = generate_unique_slug(
            db, CollectorGroup, updates["name"], exclude_id=group_id
        )

    for field, value in updates.items():
        setattr(group, field, value)

    db.commit()
    db.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: int, db: Session = Depends(get_db)):
    group = _get_group_or_404(db, group_id)
    db.execute(delete(CollectionItemGroup).where(CollectionItemGroup.group_id == group_id))
    db.delete(group)
    db.commit()
    return None
