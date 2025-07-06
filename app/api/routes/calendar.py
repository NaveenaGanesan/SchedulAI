"""
Calendar-related routes

Contains endpoints for calendar operations, availability checking, and event management.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from datetime import datetime, timedelta
from typing import List

from app.api.dependencies import get_agent_service
from app.models.api import CalendarAvailabilityResponse
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/upcoming")
async def get_upcoming_meetings(
    days_ahead: int = 7,
    agent = Depends(get_agent_service)
):
    """Get upcoming meetings from calendar"""
    
    try:
        if days_ahead < 1 or days_ahead > 30:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="days_ahead must be between 1 and 30"
            )
        
        start_date = datetime.now()
        end_date = start_date.replace(hour=23, minute=59, second=59) + timedelta(days=days_ahead)
        
        events = agent.google_service.get_calendar_events(start_date, end_date)
        
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


@router.get("/availability", response_model=CalendarAvailabilityResponse)
async def get_calendar_availability(
    participant_emails: str,  # Comma-separated emails
    days_ahead: int = 7,
    duration_minutes: int = 30,
    agent = Depends(get_agent_service)
):
    """Check calendar availability for specified participants"""
    
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
        
        logger.info(f"Checking availability for {len(emails)} participants over {days_ahead} days")
        
        # Calculate date range
        start_date = datetime.now()
        end_date = start_date + timedelta(days=days_ahead)
        
        # Get availability data
        availability_result = agent._get_calendar_availability(
            emails, 
            start_date.isoformat(), 
            end_date.isoformat(), 
            duration_minutes
        )
        
        if not availability_result.get("success", False):
            return CalendarAvailabilityResponse(
                success=False,
                error=availability_result.get("error", "Failed to fetch availability")
            )
        
        return CalendarAvailabilityResponse(
            success=True,
            availability_data=availability_result.get("availability_data", [])
        )
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error checking calendar availability: {str(e)}")
        return CalendarAvailabilityResponse(
            success=False,
            error=f"Failed to check availability: {str(e)}"
        )


@router.post("/events")
async def create_calendar_event(
    title: str,
    description: str = "",
    start_time: str = "",
    end_time: str = "",
    attendees: List[str] = [],
    location: str = "",
    agent = Depends(get_agent_service)
):
    """Create a new calendar event"""
    
    try:
        if not all([title, start_time, end_time]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="title, start_time, and end_time are required"
            )
        
        # Validate datetime formats
        try:
            start_dt = datetime.fromisoformat(start_time)
            end_dt = datetime.fromisoformat(end_time)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid datetime format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"
            )
        
        if start_dt >= end_dt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_time must be before end_time"
            )
        
        logger.info(f"Creating calendar event: {title}")
        
        result = agent._create_calendar_event(
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            attendees=attendees,
            location=location
        )
        
        if not result.get("success", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to create calendar event")
            )
        
        logger.info(f"Calendar event created successfully: {result.get('event_id')}")
        return result
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error creating calendar event: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create calendar event: {str(e)}"
        ) 