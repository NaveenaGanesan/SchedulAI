"""
API request and response models

Contains Pydantic models for API endpoint requests and responses.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime


class ScheduleMeetingRequest(BaseModel):
    """API request model for scheduling meetings"""
    title: str = Field(..., min_length=1, max_length=200, description="Meeting title")
    description: str = Field("", max_length=1000, description="Meeting description")
    duration_minutes: int = Field(30, ge=15, le=480, description="Duration in minutes")
    organizer: Optional[Dict[str, str]] = Field(None, description="Meeting organizer details")
    participants: List[Dict[str, str]] = Field(default_factory=list, description="Additional participants")
    priority: str = Field("medium", description="Meeting priority: low, medium, high, urgent")
    preferred_days: List[str] = Field(default_factory=list, description="Organizer's preferred days")
    user_preferences: Optional[Dict[str, Any]] = Field(None, description="Organizer's scheduling preferences")
    
    @validator('priority')
    def validate_priority(cls, v):
        valid_priorities = ["low", "medium", "high", "urgent"]
        if v not in valid_priorities:
            raise ValueError(f"Priority must be one of: {valid_priorities}")
        return v


class HealthResponse(BaseModel):
    """Health check response model"""
    status: str
    services: Dict[str, bool]
    agent_tools_count: Optional[int] = None
    config: Optional[Dict[str, Any]] = None
    timestamp: str
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response model"""
    detail: str
    error_code: Optional[str] = None
    timestamp: Optional[str] = None


class MeetingProposalResponse(BaseModel):
    """Meeting proposal API response"""
    success: bool
    proposal_id: Optional[str] = None
    suggested_slots: Optional[List[Dict[str, Any]]] = None
    reasoning: Optional[str] = None
    agent_message: Optional[str] = None
    error: Optional[str] = None


class ProposalStatusResponse(BaseModel):
    """Proposal status API response"""
    proposal_id: str
    status: str
    meeting_title: str
    participants: List[str]
    suggested_slots: List[Dict[str, Any]]
    reasoning: str
    created_at: str


class CalendarAvailabilityResponse(BaseModel):
    """Calendar availability API response"""
    success: bool
    availability_data: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None 