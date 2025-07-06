"""
Meeting-related routes

Contains endpoints for scheduling, managing, and confirming meetings.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from typing import Dict, Any

from app.api.dependencies import get_agent_service
from app.models import (
    ScheduleMeetingRequest, MeetingRequest, MeetingPriority, 
    Participant, UserPreferences
)
from app.models.api import MeetingProposalResponse, ProposalStatusResponse
from app.core.logging import get_logger
from app.core.exceptions import AgentException

logger = get_logger(__name__)
router = APIRouter()


@router.post("/schedule", response_model=MeetingProposalResponse)
async def schedule_meeting(
    request: ScheduleMeetingRequest,
    agent = Depends(get_agent_service)
):
    """
    Schedule a new meeting using AI agent with function calling
    
    The organizer is the person requesting the meeting (usually the API user).
    Participants are additional attendees who will be invited.
    User preferences apply to the organizer and take priority in scheduling decisions.
    """
    
    logger.info(f"Meeting scheduling requested: '{request.title}' ({request.duration_minutes}min)")
    
    try:        
        # Handle organizer - if not provided, create a default one
        if request.organizer is None:
            logger.info("No organizer provided, creating default organizer")
            organizer_obj = Participant(
                name="API User",
                email="api.user@example.com",
                timezone=request.user_preferences.get("timezone", "UTC") if request.user_preferences else "UTC",
                role="organizer"
            )
        else:
            if "name" not in request.organizer or "email" not in request.organizer:
                logger.error(f"Invalid organizer data: {request.organizer}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Organizer must have 'name' and 'email'"
                )
            
            organizer_obj = Participant(
                name=request.organizer["name"],
                email=request.organizer["email"],
                timezone=request.organizer.get("timezone", "UTC"),
                preferences=request.organizer.get("preferences", {}),
                role="organizer"
            )
            logger.debug(f"Added organizer: {request.organizer['name']} ({request.organizer['email']})")
        
        # Create participants list
        logger.debug(f"Processing {len(request.participants)} additional participants...")
        participant_objects = []
        for i, p in enumerate(request.participants):
            if "name" not in p or "email" not in p:
                logger.error(f"Invalid participant data at index {i}: {p}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Each participant must have 'name' and 'email'"
                )
            
            participant_objects.append(Participant(
                name=p["name"],
                email=p["email"],
                timezone=p.get("timezone", "UTC"),
                preferences=p.get("preferences", {}),
                role=p.get("role", "attendee")
            ))
            logger.debug(f"Added participant: {p['name']} ({p['email']})")
        
        # Create meeting request
        logger.debug("Creating meeting request object...")
        meeting_request = MeetingRequest(
            title=request.title,
            description=request.description,
            duration_minutes=request.duration_minutes,
            organizer=organizer_obj,
            participants=participant_objects,
            priority=MeetingPriority(request.priority),
            preferred_days=request.preferred_days
        )
        
        logger.info(f"Total attendees: {len(meeting_request.get_all_participants())} (1 organizer + {len(request.participants)} participants)")
        
        # Create user preferences if provided (these are the organizer's preferences)
        preferences = None
        if request.user_preferences:
            logger.debug("Processing organizer preferences...")
            preferences = UserPreferences(**request.user_preferences)
        
        # Use AI agent to schedule the meeting
        logger.info("Delegating to AI agent for scheduling...")
        result = agent.schedule_meeting(meeting_request, preferences)
        
        if not result["success"]:
            logger.error(f"Meeting scheduling failed: {result.get('error', 'Unknown error')}")
            return MeetingProposalResponse(
                success=False,
                error=result.get("error", "Unknown error")
            )
        
        logger.info(f"Meeting scheduled successfully: {result.get('proposal_id', 'No ID')}")
        return MeetingProposalResponse(
            success=True,
            proposal_id=result.get("proposal_id"),
            suggested_slots=result.get("suggested_slots"),
            reasoning=result.get("reasoning"),
            agent_message=result.get("agent_message")
        )
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        
        logger.error(f"Unexpected error in schedule_meeting: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/confirm/{proposal_id}")
async def confirm_meeting(
    proposal_id: str, 
    selected_slot_index: int, 
    confirmed_by: str = "api_user",
    agent = Depends(get_agent_service)
):
    """Confirm a meeting proposal by selecting a time slot"""
    
    logger.info(f"Meeting confirmation requested: {proposal_id} (slot {selected_slot_index})")
    
    try:
        result = agent.confirm_meeting(proposal_id, selected_slot_index)
        
        if not result["success"]:
            logger.error(f"Meeting confirmation failed: {result.get('error', 'Unknown error')}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        logger.info(f"Meeting confirmed successfully: {proposal_id}")
        return result
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/proposal/{proposal_id}", response_model=ProposalStatusResponse)
async def get_proposal_status(
    proposal_id: str,
    agent = Depends(get_agent_service)
):
    """Get the status of a meeting proposal"""
    
    try:
        if proposal_id not in agent.proposals:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proposal not found"
            )
        
        proposal = agent.proposals[proposal_id]
        
        return ProposalStatusResponse(
            proposal_id=proposal_id,
            status=proposal.status,
            meeting_title=proposal.meeting_request.title,
            participants=[p.email for p in proposal.meeting_request.get_all_participants()],
            suggested_slots=[
                {
                    "index": i,
                    "start_time": slot.start_time.isoformat(),
                    "end_time": slot.end_time.isoformat(),
                    "formatted": f"{slot.start_time.strftime('%A, %B %d at %I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}"
                }
                for i, slot in enumerate(proposal.suggested_slots)
            ],
            reasoning=proposal.reasoning,
            created_at=proposal.created_at.isoformat()
        )
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/check-email-responses/{proposal_id}")
async def check_email_responses(
    proposal_id: str, 
    query: str = "",
    agent = Depends(get_agent_service)
):
    """Check for email responses related to meeting proposals"""
    
    try:
        result = agent._check_email_responses(proposal_id, query)
        return result
        
    except Exception as e:
        logger.error(f"Error checking email responses: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check email responses: {str(e)}"
        )


@router.get("/agent-tools")
async def get_agent_tools(agent = Depends(get_agent_service)):
    """Get information about available AI agent tools"""
    
    return {
        "tools": [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "parameters": list(tool["function"]["parameters"]["properties"].keys())
            }
            for tool in agent.tools
        ],
        "total_tools": len(agent.tools)
    }


# @router.post("/natural-language-schedule")
# async def natural_language_schedule(query: str):
    """Future endpoint for natural language meeting scheduling"""
    
    # Placeholder for future NLP integration
    return {
        "message": "Natural language processing not yet implemented",
        "query": query,
        "status": "coming_soon"
    } 