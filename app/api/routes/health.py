"""
Health check routes

Contains endpoints for monitoring application health and status.
"""

from fastapi import APIRouter, Depends
from datetime import datetime

from app.api.dependencies import get_agent_service, get_google_service, get_settings
from app.models.api import HealthResponse
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/", response_model=dict)
async def root():
    """Root endpoint with API overview"""
    logger.info("Root endpoint accessed")
    
    return {
        "message": "SchedulAI API", 
        "version": "1.0.0",
        "features": ["OpenAI Function Calling", "Google Calendar & Gmail", "Autonomous Scheduling"],
        "status": "active",
        "architecture": "Layered Architecture with Domain Separation",
        "endpoints": {
            "health": "/health",
            "schedule": "/meetings/schedule",
            "proposals": "/meetings/proposal/{proposal_id}",
            "confirm": "/meetings/confirm/{proposal_id}",
            "upcoming": "/calendar/upcoming",
            "availability": "/calendar/availability",
            "tools": "/meetings/agent-tools",
            "docs": "/docs"
        }
    }


@router.get("/health", response_model=HealthResponse)
async def health_check(
    agent = Depends(get_agent_service),
    settings = Depends(get_settings)
):
    """Comprehensive health check endpoint"""
    logger.info("Health check requested")
    
    try:
        # Validate Google services
        logger.debug("Checking Google services...")
        google_status = agent.google_service.validate_services()
        
        # Check OpenAI connection
        logger.debug("Checking OpenAI configuration...")
        openai_status = bool(settings.OPENAI_API_KEY)
        
        all_healthy = (
            google_status.get('calendar', False) and 
            google_status.get('gmail', False) and 
            openai_status
        )
        
        health_status = "healthy" if all_healthy else "unhealthy"
        
        logger.info(f"Health check completed - Status: {health_status}")
        if not all_healthy:
            logger.warning(f"Some services are unhealthy: {google_status}")
        
        return HealthResponse(
            status=health_status,
            services={
                "google_calendar": google_status.get('calendar', False),
                "gmail_api": google_status.get('gmail', False),
                "openai_agent": openai_status,
                "function_calling": True
            },
            agent_tools_count=len(agent.tools),
            config={
                "debug_mode": settings.DEBUG,
                "log_level": settings.LOG_LEVEL
            },
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return HealthResponse(
            status="unhealthy",
            services={},
            error=str(e),
            timestamp=datetime.now().isoformat()
        ) 