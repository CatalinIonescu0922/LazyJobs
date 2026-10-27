from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from ..cv import read_cv
from ..db import get_db
from ..llm import extract_profile
from ..models import Profile, User
from ..schemas import ProfileResponse, ProfileUpdate
from ..session import current_user
from ..storage import store_cv

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
def get_profile(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    profile = _get_or_create_profile(db, user)
    return _profile_response(profile)


@router.post("/cv", response_model=ProfileResponse)
async def upload_cv(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    text, content = await read_cv(file)
    extracted = extract_profile(text)
    profile = _get_or_create_profile(db, user)

    profile.cv_filename = file.filename or "cv"
    profile.cv_text = text
    profile.full_name = extracted.full_name
    profile.headline = extracted.headline
    profile.summary = extracted.summary
    profile.titles = extracted.titles
    profile.skills = extracted.skills
    profile.years_experience = extracted.years_experience
    profile.country = extracted.country
    profile.city = extracted.city
    profile.salary_currency = extracted.salary_currency
    store_cv(user.id, profile.cv_filename, content)
    db.commit()
    db.refresh(profile)
    return _profile_response(profile)


@router.patch("", response_model=ProfileResponse)
def update_profile(
    update: ProfileUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    profile = _get_or_create_profile(db, user)
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return _profile_response(profile)


def _get_or_create_profile(db: Session, user: User) -> Profile:
    if user.profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
        db.flush()
        return profile
    return user.profile


def _profile_response(profile: Profile) -> ProfileResponse:
    response = ProfileResponse.model_validate(profile)
    return response.model_copy(update={"has_cv": bool(profile.cv_filename)})
