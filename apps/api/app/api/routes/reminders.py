from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import current_profile, get_session
from app.core.config import get_settings
from app.models.enums import ReminderProviderKind, ReminderStatus
from app.models.opportunity import Opportunity
from app.models.ops import Reminder
from app.models.user import StudentProfile
from app.reminders.apple_shortcuts import SHORTCUT_RECIPE
from app.reminders.base import ReminderPayload
from app.reminders.registry import all_providers, get_provider
from app.schemas import entities as E

router = APIRouter(tags=["reminders"])


@router.get("/reminders/providers", response_model=list[E.ReminderProviderInfo])
def list_providers() -> list[E.ReminderProviderInfo]:
    return [
        E.ReminderProviderInfo(
            slug=p.slug,
            label=p.label,
            description=p.description,
            requires_user_action=p.requires_user_action,
        )
        for p in all_providers()
    ]


@router.get("/reminders", response_model=list[E.ReminderItem])
def list_reminders(
    db: Session = Depends(get_session), profile: StudentProfile = Depends(current_profile)
) -> list[E.ReminderItem]:
    rows = db.scalars(
        select(Reminder)
        .where(Reminder.profile_id == profile.id)
        .order_by(Reminder.due_on.nullslast())
    ).all()
    return [ser.reminder_item(r) for r in rows]


@router.post("/reminders", response_model=E.ReminderItem, status_code=201)
def create_reminder(
    payload: E.ReminderIn,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.ReminderItem:
    opp = db.get(Opportunity, payload.opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    if opp.deadline is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "This opportunity has no known deadline, so there is nothing to remind you about. "
                "Add one manually if you know it."
            ),
        )
    try:
        provider = ReminderProviderKind(payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown provider {payload.provider!r}.") from exc

    settings = get_settings()
    reminder = Reminder(
        profile_id=profile.id,
        opportunity_id=opp.id,
        title=opp.title,
        due_on=opp.deadline,
        # Defaulted, never hard-coded, so this becomes user-configurable later.
        offsets_days=payload.offsets_days or list(settings.default_reminder_offsets_days),
        provider=provider,
        url=opp.application_url or opp.source_url,
        documents=list(opp.documents_required or []),
        notes=payload.notes,
    )
    db.add(reminder)
    db.flush()
    return ser.reminder_item(reminder)


@router.delete("/reminders/{reminder_id}", status_code=204)
def delete_reminder(
    reminder_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> None:
    row = db.get(Reminder, reminder_id)
    if row is not None and row.profile_id == profile.id:
        db.delete(row)
        db.flush()


def _payload_for(db: Session, reminder: Reminder) -> ReminderPayload:
    opp = db.get(Opportunity, reminder.opportunity_id) if reminder.opportunity_id else None
    return ReminderPayload(
        title=reminder.title,
        due_on=reminder.due_on,
        due_at=reminder.due_at,
        url=reminder.url,
        application_url=(opp.application_url if opp else None) or reminder.url,
        documents=list(reminder.documents or []),
        notes=reminder.notes,
        offsets_days=list(reminder.offsets_days or []),
        opportunity_id=str(reminder.opportunity_id) if reminder.opportunity_id else None,
    )


@router.get("/reminders/{reminder_id}/export.ics")
def export_ics(
    reminder_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> Response:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Reminder not found.")
    export = get_provider("ics").export(_payload_for(db, reminder))
    reminder.status = ReminderStatus.EXPORTED
    reminder.exported_at = datetime.now(UTC)
    reminder.external_id = export.external_id
    db.flush()
    return Response(
        content=export.body or "",
        media_type=export.content_type,
        headers={"Content-Disposition": f'attachment; filename="{export.filename}"'},
    )


@router.get("/reminders/{reminder_id}/shortcut")
def export_shortcut(
    reminder_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> dict[str, object]:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Reminder not found.")
    export = get_provider("apple_shortcuts").export(_payload_for(db, reminder))
    reminder.status = ReminderStatus.EXPORTED
    reminder.exported_at = datetime.now(UTC)
    db.flush()
    return {
        "payload": export.payload,
        "instructions": export.instructions,
        "shortcut_recipe": SHORTCUT_RECIPE,
    }


@router.get("/reminders/apple/availability")
def apple_availability() -> dict[str, object]:
    """Can this machine write to Reminders right now?

    Asked before the button is shown, so an unavailable integration says why
    instead of failing when the student presses it.
    """
    from app.reminders.apple_reminders import availability

    state = availability()
    return {
        "available": state.available,
        "reason": state.reason,
        "needs_permission": state.needs_permission,
    }


@router.post("/reminders/{reminder_id}/apple")
def send_to_apple_reminders(
    reminder_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> dict[str, object]:
    """Create the alerts in the Reminders app on this Mac."""
    from app.reminders.apple_reminders import AppleRemindersProvider, AppleRemindersUnavailable

    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Reminder not found.")

    try:
        export = AppleRemindersProvider().export(_payload_for(db, reminder))
    except AppleRemindersUnavailable as exc:
        # 409, not 500: the request was fine, the environment is not ready.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    reminder.provider = ReminderProviderKind.APPLE_REMINDERS
    reminder.status = ReminderStatus.EXPORTED
    reminder.exported_at = datetime.now(UTC)
    db.flush()
    return {"created": export.payload["created"], "note": export.instructions}
