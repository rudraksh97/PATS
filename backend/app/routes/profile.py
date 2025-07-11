from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..models.database import get_db
from ..models.profile import Profile as ProfileModel
from ..schemas import Profile, ProfileCreate, ProfileUpdate

router = APIRouter()

PROFILE_ID = 1

@router.get("/", response_model=Profile)
def get_profile(db: Session = Depends(get_db)):
    """
    Retrieve the user profile.
    """
    profile = db.query(ProfileModel).filter(ProfileModel.id == PROFILE_ID).first()
    if not profile:
        # Return a default empty profile if none exists
        return Profile(id=PROFILE_ID, full_name="", email=None, headline="", linkedin_url=None)
    return profile

@router.post("/", response_model=Profile)
def upsert_profile(profile_data: ProfileCreate, db: Session = Depends(get_db)):
    """
    Create or update the user profile.
    """
    profile = db.query(ProfileModel).filter(ProfileModel.id == PROFILE_ID).first()
    
    update_data = profile_data.model_dump(exclude_unset=True)
    if 'linkedin_url' in update_data and update_data['linkedin_url']:
        update_data['linkedin_url'] = str(update_data['linkedin_url'])

    if profile:
        # Update existing profile
        for key, value in update_data.items():
            setattr(profile, key, value)
    else:
        # Create new profile
        profile = ProfileModel(id=PROFILE_ID, **update_data)
        db.add(profile)
        
    db.commit()
    db.refresh(profile)
    return profile 