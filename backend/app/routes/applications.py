from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime
import uuid
import os
import shutil
from pathlib import Path

from ..models.database import get_db
from ..models.application import Application, ApplicationStatus, ApplicationSource, ApplicationPriority
from ..models.setting import Setting as SettingModel
from ..services.openai_service import OpenAIService
from ..schemas import (
    ApplicationCreate, 
    ApplicationUpdate, 
    Application as ApplicationSchema, 
    ApplicationFilter,
    CompanyInfo
)

router = APIRouter()

# Create uploads directory if it doesn't exist
UPLOADS_DIR = Path("uploads/resumes")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

COVER_LETTERS_DIR = Path("uploads/cover_letters")
COVER_LETTERS_DIR.mkdir(parents=True, exist_ok=True)

def generate_id():
    return str(uuid.uuid4())

def save_upload_file(file: UploadFile, application_id: str, upload_dir: Path) -> tuple[str, str]:
    """Save upload file and return original filename and file path"""
    # Generate unique filename for file system
    file_extension = Path(file.filename).suffix if file.filename else '.pdf'
    system_filename = f"{application_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{file_extension}"
    file_path = upload_dir / system_filename
    
    # Save file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Return original filename for database, actual file path for system
    original_filename = file.filename if file.filename else f"resume{file_extension}"
    return original_filename, str(file_path)

@router.post("/", response_model=ApplicationSchema)
async def create_application(
    company_name: str = Form(...),
    job_title: str = Form(...),
    job_id: str = Form(...),
    job_url: str = Form(...),
    portal_url: Optional[str] = Form(None),
    status: ApplicationStatus = Form(ApplicationStatus.APPLIED),
    priority: ApplicationPriority = Form(ApplicationPriority.MEDIUM),
    date_applied: datetime = Form(...),
    email_used: str = Form(...),
    source: ApplicationSource = Form(...),
    notes: Optional[str] = Form(None),
    resume: UploadFile = File(...),
    cover_letter: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """Create a new job application with resume file upload"""
    
    # Validate file type
    allowed_extensions = {'.pdf', '.doc', '.docx'}
    file_extension = Path(resume.filename).suffix.lower() if resume.filename else ''
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Generate application ID
    application_id = generate_id()
    
    # Save resume file
    resume_filename, resume_file_path = save_upload_file(resume, application_id, UPLOADS_DIR)

    # Save cover letter file if provided
    cover_letter_filename = None
    cover_letter_file_path = None
    if cover_letter and cover_letter.filename:
        # Validate file type for cover letter
        if Path(cover_letter.filename).suffix.lower() not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid cover letter file type. Allowed: {', '.join(allowed_extensions)}"
            )
        cover_letter_filename, cover_letter_file_path = save_upload_file(cover_letter, application_id, COVER_LETTERS_DIR)

    # Create application
    db_application = Application(
        id=application_id,
        company_name=company_name,
        job_title=job_title,
        job_id=job_id,
        job_url=job_url,
        portal_url=portal_url,
        status=status,
        priority=priority,
        date_applied=date_applied,
        email_used=email_used,
        resume_filename=resume_filename,
        resume_file_path=resume_file_path,
        cover_letter_filename=cover_letter_filename,
        cover_letter_file_path=cover_letter_file_path,
        source=source,
        notes=notes
    )
    
    db.add(db_application)
    db.commit()
    db.refresh(db_application)
    return db_application

@router.get("/{application_id}/resume")
async def download_resume(application_id: str, db: Session = Depends(get_db)):
    """Download resume file for an application"""
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    
    file_path = Path(application.resume_file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Resume file not found")
    
    return FileResponse(
        path=file_path,
        filename=application.resume_filename,
        media_type='application/octet-stream'
    )

@router.get("/{application_id}/cover-letter")
async def download_cover_letter(application_id: str, db: Session = Depends(get_db)):
    """Download cover letter file for an application"""
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None or not application.cover_letter_file_path:
        raise HTTPException(status_code=404, detail="Cover letter not found")
    
    file_path = Path(application.cover_letter_file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Cover letter file not found")
    
    return FileResponse(
        path=file_path,
        filename=application.cover_letter_filename,
        media_type='application/octet-stream'
    )

@router.get("/", response_model=List[ApplicationSchema])
def get_applications(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    company_name: Optional[str] = None,
    status: Optional[ApplicationStatus] = None,
    priority: Optional[ApplicationPriority] = None,
    source: Optional[ApplicationSource] = None,
    email_used: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all applications with optional filtering"""
    query = db.query(Application)
    
    # Apply filters
    if company_name:
        query = query.filter(Application.company_name.ilike(f"%{company_name}%"))
    if status:
        query = query.filter(Application.status == status)
    if priority:
        query = query.filter(Application.priority == priority)
    if source:
        query = query.filter(Application.source == source)
    if email_used:
        query = query.filter(Application.email_used.ilike(f"%{email_used}%"))
    
    applications = query.offset(skip).limit(limit).all()
    return applications

@router.get("/recent/", response_model=List[ApplicationSchema])
def get_recent_applications(db: Session = Depends(get_db)):
    """Get the 5 most recent applications"""
    applications = db.query(Application).order_by(Application.created_at.desc()).limit(5).all()
    return applications

@router.get("/company-info/", response_model=Optional[CompanyInfo])
def get_company_info(company_name: str, db: Session = Depends(get_db)):
    """Get portal_url and source for a given company from the most recent application."""
    application = db.query(Application) \
        .filter(Application.company_name.ilike(f"%{company_name}%")) \
        .order_by(Application.date_applied.desc()) \
        .first()
    
    if application:
        return CompanyInfo(
            portal_url=application.portal_url,
            source=application.source
        )
    return None

@router.get("/{application_id}/", response_model=ApplicationSchema)
def get_application(application_id: str, db: Session = Depends(get_db)):
    """Get a specific application by ID"""
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application

@router.put("/{application_id}", response_model=ApplicationSchema)
def update_application(
    application_id: str,
    application_update: ApplicationUpdate,
    db: Session = Depends(get_db)
):
    """Update an existing application"""
    db_application = db.query(Application).filter(Application.id == application_id).first()
    if db_application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    
    update_data = application_update.model_dump(exclude_unset=True)
    if 'job_url' in update_data and update_data['job_url']:
        update_data['job_url'] = str(update_data['job_url'])
    if 'portal_url' in update_data and update_data['portal_url']:
        update_data['portal_url'] = str(update_data['portal_url'])

    for field, value in update_data.items():
        setattr(db_application, field, value)
    
    db_application.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_application)
    return db_application

@router.delete("/{application_id}")
def delete_application(application_id: str, db: Session = Depends(get_db)):
    """Delete an application"""
    db_application = db.query(Application).filter(Application.id == application_id).first()
    if db_application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    
    db.delete(db_application)
    db.commit()
    return {"message": "Application deleted successfully"}

@router.get("/search/", response_model=List[ApplicationSchema])
def search_applications(
    q: str = Query(..., description="Search query"),
    db: Session = Depends(get_db)
):
    """Search applications by company name, job title, or job ID"""
    query = db.query(Application).filter(
        or_(
            Application.company_name.ilike(f"%{q}%"),
            Application.job_title.ilike(f"%{q}%"),
            Application.job_id.ilike(f"%{q}%")
        )
    )
    applications = query.all()
    return applications

@router.get("/analytics/summary")
def get_application_analytics(db: Session = Depends(get_db)):
    """Get analytics summary for applications"""
    total_applications = db.query(Application).count()
    
    # Applications by status
    status_counts = {}
    for status in ApplicationStatus:
        count = db.query(Application).filter(Application.status == status).count()
        status_counts[status.value] = count
    
    # Applications by source
    source_counts = {}
    for source in ApplicationSource:
        count = db.query(Application).filter(Application.source == source).count()
        source_counts[source.value] = count
    
    # Success rate (interviews + offers / total)
    successful = db.query(Application).filter(
        Application.status.in_([ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER])
    ).count()
    success_rate = (successful / total_applications * 100) if total_applications > 0 else 0
    
    return {
        "total_applications": total_applications,
        "applications_by_status": status_counts,
        "applications_by_source": source_counts,
        "success_rate": round(success_rate, 2)
    }

@router.post("/parse-url/")
async def parse_job_url(
    url: str = Form(...),
    db: Session = Depends(get_db)
):
    """Parse job URL using OpenAI to extract job details"""
    
    print(f"[DEBUG] Attempting to parse URL: {url}")
    
    # Get OpenAI API key from settings
    api_key_setting = db.query(SettingModel).filter(SettingModel.key == "openai_api_key").first()
    if not api_key_setting or not api_key_setting.value:
        print("[DEBUG] No API key found in settings")
        raise HTTPException(
            status_code=400, 
            detail="OpenAI API key not configured. Please set your API key in Settings."
        )
    
    print(f"[DEBUG] Found API key in settings (length: {len(api_key_setting.value)})")
    
    try:
        # Initialize OpenAI service
        openai_service = OpenAIService(api_key_setting.value)
        print("[DEBUG] OpenAI service initialized")
        
        # Test API key validity
        print("[DEBUG] Testing API key validity...")
        api_key_valid = openai_service.test_api_key()
        print(f"[DEBUG] API key test result: {api_key_valid}")
        
        if not api_key_valid:
            raise HTTPException(
                status_code=400,
                detail="Invalid OpenAI API key. Please check your API key in Settings."
            )
        
        # Parse the job URL
        print("[DEBUG] Starting URL parsing...")
        job_details = openai_service.parse_job_url(url)
        print(f"[DEBUG] URL parsing result: {job_details}")
        
        if not job_details:
            raise HTTPException(
                status_code=400,
                detail="Unable to extract job details from the provided URL. This might be because the page uses JavaScript to load content dynamically, or the page structure is not recognized. Please try manually entering the job details or use a different URL."
            )
        
        print("[DEBUG] Successfully parsed URL")
        return job_details
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Exception in parse_job_url: {str(e)}")
        print(f"[ERROR] Exception type: {type(e)}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while parsing the job URL. Please try again."
        ) 