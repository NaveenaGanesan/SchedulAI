"""
SchedulAI Services Module

This module contains the core services for the SchedulAI application:
- GoogleService: Unified Google Calendar and Gmail API integration
- SchedulingAgent: AI agent with OpenAI function calling capabilities

The services follow a clean architecture pattern with proper separation of concerns.
"""

from app.services.google_service import GoogleService
from app.services.agent_service import SchedulingAgent

__all__ = [
    "GoogleService",
    "SchedulingAgent"
]

# Service factory functions for dependency injection
def create_google_service() -> GoogleService:
    """Factory function to create GoogleService instance"""
    return GoogleService()

def create_scheduling_agent() -> SchedulingAgent:
    """Factory function to create SchedulingAgent instance"""
    return SchedulingAgent() 