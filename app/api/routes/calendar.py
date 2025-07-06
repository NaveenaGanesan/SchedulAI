"""
Calendar API Routes

Simple calendar endpoints:
1. Get current user email from Google APIs
2. Get upcoming meetings (with optional email parameter)
3. Check availability for participants

No authentication validation - uses existing Google credentials directly.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_agent_service
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/current-user")
async def get_current_user():
    """
    Get the current user's email address from Google APIs
    
    Calls Google OAuth2 API to get the authenticated user's information.
    """
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        import pickle
        import os
        
        # Load credentials from token file
        token_file = "token.pickle"
        if not os.path.exists(token_file):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No credentials found. Please run authentication first."
            )
        
        with open(token_file, 'rb') as token:
            credentials = pickle.load(token)
        
        # Get user info from Google
        service = build('oauth2', 'v2', credentials=credentials)
        user_info = service.userinfo().get().execute()
        
        email = user_info.get('email', '')
        name = user_info.get('name', '')
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not retrieve user email from Google"
            )
        
        return {
            "email": email,
            "name": name,
            "message": f"Current user: {name} ({email})"
        }
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error getting current user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get current user: {str(e)}"
        )


@router.get("/upcoming")
async def get_upcoming_meetings(
    email: Optional[str] = None,  # Optional: defaults to current user
    days_ahead: int = 7,
    agent = Depends(get_agent_service)
):
    """
    Get upcoming meetings from calendar
    
    **Parameters:**
    - email: Optional email address (if not provided, gets current user from /current-user)
    - days_ahead: Number of days ahead to fetch (1-30, default: 7)
    """
    
    try:
        if days_ahead < 1 or days_ahead > 30:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="days_ahead must be between 1 and 30"
            )
        
        # Get current user email if not provided
        if not email:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            import pickle
            import os
            
            # Load credentials and get current user
            token_file = "token.pickle"
            if not os.path.exists(token_file):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="No credentials found. Please run authentication first."
                )
            
            with open(token_file, 'rb') as token:
                credentials = pickle.load(token)
            
            service = build('oauth2', 'v2', credentials=credentials)
            user_info = service.userinfo().get().execute()
            email = user_info.get('email', '')
            
            if not email:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Could not get current user email"
                )
        
        logger.info(f"Fetching upcoming meetings for: {email}")
        
        start_date = datetime.now()
        end_date = start_date.replace(hour=23, minute=59, second=59) + timedelta(days=days_ahead)
        
        # Call Google Calendar API directly
        events = agent.google_service.get_calendar_events(start_date, end_date, email)
        
        meetings = [
            {
                "id": event.id,
                "title": event.title,
                "description": event.description,
                "start_time": event.start_time.isoformat(),
                "end_time": event.end_time.isoformat(),
                "attendees": event.attendees,
                "location": event.location,
                "formatted": f"{event.start_time.strftime('%A, %B %d at %I:%M %p')} - {event.end_time.strftime('%I:%M %p')}"
            }
            for event in events
        ]
        
        return {
            "meetings": meetings,
            "total_count": len(meetings),
            "user_email": email,
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": days_ahead
            }
        }
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error fetching upcoming meetings: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch upcoming meetings: {str(e)}"
        )


@router.get("/availability")
async def get_calendar_availability(
    participant_emails: str,  # Comma-separated emails
    days_ahead: int = 7,
    duration_minutes: int = 30,
    agent = Depends(get_agent_service)
):
    """
    Check calendar availability for participants
    
    **Parameters:**
    - participant_emails: Comma-separated email addresses (e.g., "user1@gmail.com,user2@gmail.com")
    - days_ahead: Number of days ahead to check (1-30, default: 7)
    - duration_minutes: Meeting duration in minutes (15-480, default: 30)
    
    Calls Google Calendar APIs directly for availability data.
    """
    
    try:
        if days_ahead < 1 or days_ahead > 30:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="days_ahead must be between 1 and 30"
            )
        
        if duration_minutes < 15 or duration_minutes > 480:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="duration_minutes must be between 15 and 480"
            )
        
        # Parse participant emails
        emails = [email.strip() for email in participant_emails.split(",") if email.strip()]
        if not emails:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one participant email is required"
            )
        
        logger.info(f"Checking availability for {len(emails)} participants: {emails}")
        
        # Calculate date range
        start_date = datetime.now()
        end_date = start_date + timedelta(days=days_ahead)
        
        # Get availability data directly from Google Calendar
        availability_result = agent._get_calendar_availability(
            emails, 
            start_date.isoformat(), 
            end_date.isoformat(), 
            duration_minutes
        )
        
        if not availability_result.get("success", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=availability_result.get("error", "Failed to fetch availability")
            )
        
        return {
            "success": True,
            "availability_data": availability_result.get("availability_data", []),
            "participants": emails,
            "duration_minutes": duration_minutes,
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": days_ahead
            }
        }
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error checking calendar availability: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check availability: {str(e)}"
        ) 