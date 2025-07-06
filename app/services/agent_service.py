import json
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
import openai

from app.models import (
    MeetingRequest, MeetingProposal, TimeSlot, CalendarEvent,
    EmailMessage, AvailabilityRequest, UserPreferences,
    ToolCall, FunctionCall, AgentResponse, AgentAction
)
from app.config import config
from app.services.google_service import GoogleService
from app.core.logging import get_logger

logger = get_logger(__name__)

class SchedulingAgent:
    """AI Agent that uses OpenAI function calling for meeting scheduling with multi-user support"""
    
    def __init__(self):
        logger.info("Initializing SchedulAI Agent...")
        
        # Initialize OpenAI client
        if not config.OPENAI_API_KEY:
            logger.error("OpenAI API key not found in configuration")
            raise ValueError("OpenAI API key is required")
        
        logger.debug("Setting up OpenAI client...")
        self.client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        
        # Initialize Google service with multi-user support
        logger.debug("Setting up Google services...")
        self.google_service = GoogleService()
        
        # Initialize proposal storage
        self.proposals: Dict[str, MeetingProposal] = {}
        
        # Define available tools/functions
        logger.debug("Setting up agent tools...")
        self.tools = self._define_tools()
        self.tool_functions = self._define_tool_functions()
        
        logger.info(f"SchedulAI Agent initialized with {len(self.tools)} tools")
        logger.debug(f"Available tools: {[tool['function']['name'] for tool in self.tools]}")
    
    def _define_tools(self) -> List[Dict[str, Any]]:
        """Define OpenAI function calling tools with multi-user support"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_authenticated_users",
                    "description": "Get list of all authenticated users who can access their calendars",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function", 
                "function": {
                    "name": "get_calendar_availability",
                    "description": "Get calendar availability for participants. Only authenticated users will show real availability data.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "participant_emails": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of participant email addresses (mix of authenticated and external users allowed)"
                            },
                            "start_date": {
                                "type": "string",
                                "format": "date-time",
                                "description": "Start date in ISO format"
                            },
                            "end_date": {
                                "type": "string", 
                                "format": "date-time",
                                "description": "End date in ISO format"
                            },
                            "duration_minutes": {
                                "type": "integer",
                                "description": "Required meeting duration in minutes"
                            }
                        },
                        "required": ["participant_emails", "start_date", "end_date", "duration_minutes"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "analyze_optimal_slots",
                    "description": "Analyze availability data and recommend optimal meeting slots",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "availability_data": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "participant_email": {"type": "string"},
                                        "free_slots": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "start_time": {"type": "string"},
                                                    "end_time": {"type": "string"},
                                                    "available": {"type": "boolean"}
                                                }
                                            }
                                        },
                                        "busy_slots": {
                                            "type": "array", 
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "start_time": {"type": "string"},
                                                    "end_time": {"type": "string"}
                                                }
                                            }
                                        }
                                    }
                                },
                                "description": "Availability data for all participants"
                            },
                            "meeting_requirements": {
                                "type": "object",
                                "properties": {
                                    "duration_minutes": {"type": "integer"},
                                    "priority": {"type": "string"},
                                    "preferred_days": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    },
                                    "user_preferences": {
                                        "type": "object",
                                        "properties": {
                                            "work_start_hour": {"type": "integer"},
                                            "work_end_hour": {"type": "integer"},
                                            "timezone": {"type": "string"},
                                            "buffer_time_minutes": {"type": "integer"}
                                        }
                                    }
                                },
                                "description": "Meeting requirements including priority, duration, preferences"
                            },
                            "max_suggestions": {
                                "type": "integer",
                                "default": 3,
                                "description": "Maximum number of slot suggestions to return"
                            }
                        },
                        "required": ["availability_data", "meeting_requirements"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_calendar_event",
                    "description": "Create a calendar event for confirmed meeting. Specify which authenticated user should create the event.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Meeting title"},
                            "description": {"type": "string", "description": "Meeting description"},
                            "start_time": {"type": "string", "format": "date-time"},
                            "end_time": {"type": "string", "format": "date-time"},
                            "attendees": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Attendee email addresses"
                            },
                            "location": {"type": "string", "description": "Meeting location"},
                            "organizer_email": {
                                "type": "string", 
                                "description": "Email of authenticated user who should create the event (usually the meeting organizer)"
                            }
                        },
                        "required": ["title", "start_time", "end_time", "attendees", "organizer_email"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "send_meeting_email",
                    "description": "Send meeting proposal or confirmation email from a specific authenticated user",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Recipient email addresses"
                            },
                            "subject": {"type": "string", "description": "Email subject"},
                            "body": {"type": "string", "description": "Email body content"},
                            "html_body": {"type": "string", "description": "HTML version of email body"},
                            "email_type": {
                                "type": "string",
                                "enum": ["proposal", "confirmation", "cancellation", "reminder"],
                                "description": "Type of email being sent"
                            },
                            "sender_email": {
                                "type": "string",
                                "description": "Email of authenticated user who should send the email (usually the meeting organizer)"
                            }
                        },
                        "required": ["to", "subject", "body", "email_type", "sender_email"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "check_email_responses",
                    "description": "Check for email responses related to meeting proposals from a specific authenticated user's inbox",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "proposal_id": {"type": "string", "description": "Meeting proposal ID"},
                            "query": {"type": "string", "description": "Search query for emails"},
                            "max_results": {"type": "integer", "default": 10},
                            "user_email": {
                                "type": "string",
                                "description": "Email of authenticated user whose inbox to check"
                            }
                        },
                        "required": ["proposal_id", "user_email"]
                    }
                }
            }
        ]
    
    def _define_tool_functions(self) -> Dict[str, Callable]:
        """Map tool names to actual function implementations"""
        return {
            "get_authenticated_users": self._get_authenticated_users,
            "get_calendar_availability": self._get_calendar_availability,
            "analyze_optimal_slots": self._analyze_optimal_slots,
            "create_calendar_event": self._create_calendar_event,
            "send_meeting_email": self._send_meeting_email,
            "check_email_responses": self._check_email_responses
        }
    
    def schedule_meeting(self, meeting_request: MeetingRequest, 
                         user_preferences: Optional[UserPreferences] = None) -> Dict[str, Any]:
        """Main agent method to schedule a meeting using function calling"""
        
        proposal_id = str(uuid.uuid4())
        
        # Create system message for the agent
        system_message = self._create_system_message(user_preferences)
        
        # Create user message with meeting request
        user_message = self._create_meeting_request_message(meeting_request)
        
        try:
            # Initial conversation with the agent
            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                tools=self.tools,
                tool_choice="auto",
                temperature=0.3
            )
            
            # Process the agent's response and execute tools
            result = self._process_agent_response(response, proposal_id, meeting_request)
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Agent error: {str(e)}",
                "proposal_id": None
            }
    
    def _process_agent_response(self, response, proposal_id: str, 
                                meeting_request: MeetingRequest) -> Dict[str, Any]:
        """Process agent response and execute tool calls"""
        message = response.choices[0].message
        
        if not message.tool_calls:
            return {
                "success": True,
                "agent_response": message.content,
                "proposal_id": proposal_id,
                "tool_calls": []
            }
        
        # Prepare messages for tool execution
        messages = [
            {"role": "assistant", "content": message.content or "", "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                } for tool_call in message.tool_calls
            ]}
        ]
        
        tool_calls = message.tool_calls
        suggested_slots = []
        reasoning = ""
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            # Execute the function
            if function_name in self.tool_functions:
                try:
                    function_result = self.tool_functions[function_name](**function_args)
                    
                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(function_result)
                    })
                    
                    # Process specific results
                    if function_name == "analyze_optimal_slots":
                        suggested_slots = function_result.get("suggested_slots", [])
                        reasoning = function_result.get("reasoning", "")
                    
                except Exception as e:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Error: {str(e)}"
                    })
        
        # Get final response from agent
        final_response = self.client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.3
        )
        
        # Create meeting proposal
        if suggested_slots:
            # Convert string slots to TimeSlot objects
            time_slots = []
            for slot in suggested_slots:
                time_slots.append(TimeSlot(
                    start_time=datetime.fromisoformat(slot["start_time"]),
                    end_time=datetime.fromisoformat(slot["end_time"]),
                    available=True
                ))
            
            proposal = MeetingProposal(
                id=proposal_id,
                meeting_request=meeting_request,
                suggested_slots=time_slots,
                reasoning=reasoning,
                status="pending"
            )
            
            self.proposals[proposal_id] = proposal
        
        return {
            "success": True,
            "agent_response": final_response.choices[0].message.content,
            "proposal_id": proposal_id,
            "suggested_slots": suggested_slots,
            "reasoning": reasoning,
            "tool_calls": [
                {
                    "function": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments)
                } for tool_call in tool_calls
            ]
        }
    
    # Tool function implementations with multi-user support
    def _get_authenticated_users(self) -> Dict[str, Any]:
        """Get list of all authenticated users"""
        try:
            authenticated_users = self.google_service.get_authenticated_users()
            current_user = self.google_service.get_authenticated_email()
            
            return {
                "success": True,
                "authenticated_users": authenticated_users,
                "current_user": current_user,
                "total_count": len(authenticated_users),
                "message": f"Found {len(authenticated_users)} authenticated users"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _get_calendar_availability(self, participant_emails: List[str], 
                                   start_date: str, end_date: str, 
                                   duration_minutes: int) -> Dict[str, Any]:
        """Get calendar availability for participants with multi-user access control"""
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            
            # Get access control information
            authenticated_users = self.google_service.get_authenticated_users()
            access_report = self.google_service.auth_manager.validate_access(participant_emails)
            
            logger.info(f"Multi-user availability check - Accessible: {access_report['accessible_users']}, Denied: {access_report['denied_users']}")
            
            availability_responses = self.google_service.get_calendar_availability(
                participant_emails, start_dt, end_dt
            )
            
            # Convert to JSON-serializable format with access control info
            result = []
            for response in availability_responses:
                is_authenticated = response.participant_email in access_report['accessible_users']
                result.append({
                    "participant_email": response.participant_email,
                    "is_authenticated": is_authenticated,
                    "free_slots": [
                        {
                            "start_time": slot.start_time.isoformat(),
                            "end_time": slot.end_time.isoformat(),
                            "duration_minutes": int((slot.end_time - slot.start_time).total_seconds() / 60)
                        }
                        for slot in response.free_slots
                        if (slot.end_time - slot.start_time).total_seconds() / 60 >= duration_minutes
                    ],
                    "busy_slots": [
                        {
                            "start_time": slot.start_time.isoformat(),
                            "end_time": slot.end_time.isoformat()
                        }
                        for slot in response.busy_slots
                    ]
                })
            
            return {
                "availability_data": result, 
                "success": True,
                "access_control": access_report,
                "authenticated_users": authenticated_users
            }
            
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def _analyze_optimal_slots(self, availability_data: List[Dict], 
                               meeting_requirements: Dict, max_suggestions: int = 3) -> Dict[str, Any]:
        """Analyze availability data and suggest optimal meeting slots"""
        try:
            duration_minutes = meeting_requirements["duration_minutes"]
            priority = meeting_requirements.get("priority", "medium")
            user_prefs = meeting_requirements.get("user_preferences", {})
            
            work_start = user_prefs.get("work_start_hour", 9)
            work_end = user_prefs.get("work_end_hour", 17)
            buffer_time = user_prefs.get("buffer_time_minutes", 15)
            
            # Find common free slots among all participants
            common_slots = []
            
            # Get authenticated participants only (they have real availability data)
            authenticated_participants = [
                participant for participant in availability_data 
                if participant.get("is_authenticated", False) and participant["free_slots"]
            ]
            
            if not authenticated_participants:
                return {
                    "success": False,
                    "error": "No authenticated participants with availability data found",
                    "suggested_slots": [],
                    "reasoning": "Cannot suggest meeting times without access to participant calendars. Please ensure participants are authenticated."
                }
            
            # Start with first authenticated participant's free slots
            base_participant = authenticated_participants[0]
            for slot in base_participant["free_slots"]:
                slot_start = datetime.fromisoformat(slot["start_time"])
                slot_end = datetime.fromisoformat(slot["end_time"])
                
                # Check if slot is within work hours
                if slot_start.hour < work_start or slot_end.hour > work_end:
                    continue
                
                # Check if slot is long enough
                if slot["duration_minutes"] < duration_minutes:
                    continue
                
                # Check if this slot works for all other authenticated participants
                works_for_all = True
                for other_participant in authenticated_participants[1:]:
                    participant_free = False
                    for other_slot in other_participant["free_slots"]:
                        other_start = datetime.fromisoformat(other_slot["start_time"])
                        other_end = datetime.fromisoformat(other_slot["end_time"])
                        
                        # Check for overlap
                        if (slot_start >= other_start and slot_start + timedelta(minutes=duration_minutes) <= other_end):
                            participant_free = True
                            break
                    
                    if not participant_free:
                        works_for_all = False
                        break
                
                if works_for_all:
                    # Calculate meeting end time
                    meeting_end = slot_start + timedelta(minutes=duration_minutes)
                    
                    common_slots.append({
                        "start_time": slot_start.isoformat(),
                        "end_time": meeting_end.isoformat(),
                        "score": self._calculate_slot_score(slot_start, priority, work_start, work_end),
                        "day_of_week": slot_start.strftime("%A"),
                        "formatted_time": f"{slot_start.strftime('%A, %B %d at %I:%M %p')} - {meeting_end.strftime('%I:%M %p')}"
                    })
            
            # Sort by score (higher is better) and limit suggestions
            common_slots.sort(key=lambda x: x["score"], reverse=True)
            suggested_slots = common_slots[:max_suggestions]
            
            # Create reasoning
            reasoning = f"""
Analyzed availability for {len(authenticated_participants)} authenticated participants.
Found {len(common_slots)} potential time slots.
Prioritized based on:
- Meeting priority: {priority}
- Work hours: {work_start}:00 - {work_end}:00
- Buffer time: {buffer_time} minutes
- Participant preferences

Top {len(suggested_slots)} recommendations selected.
            """.strip()
            
            return {
                "success": True,
                "suggested_slots": suggested_slots,
                "reasoning": reasoning,
                "total_slots_found": len(common_slots),
                "authenticated_participants_count": len(authenticated_participants)
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _calculate_slot_score(self, slot_start: datetime, priority: str, 
                              work_start: int, work_end: int) -> float:
        """Calculate score for a meeting slot based on various factors"""
        score = 100.0  # Base score
        
        # Time of day preference (prefer mid-morning or early afternoon)
        hour = slot_start.hour
        if 10 <= hour <= 11 or 14 <= hour <= 15:
            score += 20
        elif 9 <= hour <= 12 or 13 <= hour <= 16:
            score += 10
        
        # Day of week preference (prefer Tuesday-Thursday)
        day = slot_start.weekday()  # 0=Monday, 6=Sunday
        if 1 <= day <= 3:  # Tuesday-Thursday
            score += 15
        elif day in [0, 4]:  # Monday, Friday
            score += 5
        
        # Priority adjustment
        if priority == "high":
            # Prefer earlier in the week and day
            score += (7 - day) * 5  # Earlier in week is better
            if hour <= 12:
                score += 10  # Morning preference for high priority
        elif priority == "low":
            # More flexible, prefer later slots
            score += day * 2  # Later in week is fine
            if hour >= 14:
                score += 5  # Afternoon is fine for low priority
        
        return score
    
    def _create_calendar_event(self, title: str, description: str, 
                               start_time: str, end_time: str,
                               attendees: List[str], location: str = "", 
                               organizer_email: str = None) -> Dict[str, Any]:
        """Create a calendar event using multi-user authentication"""
        try:
            # Validate that organizer is authenticated
            if organizer_email and not self.google_service.is_user_authenticated(organizer_email):
                return {
                    "success": False, 
                    "error": f"Organizer '{organizer_email}' is not authenticated. Please authenticate first."
                }
            
            event = CalendarEvent(
                title=title,
                description=description,
                start_time=datetime.fromisoformat(start_time),
                end_time=datetime.fromisoformat(end_time),
                attendees=attendees,
                location=location
            )
            
            # Create event using specified organizer
            event_id = self.google_service.create_calendar_event(event, organizer_email)
            
            return {
                "success": True,
                "event_id": event_id,
                "message": f"Calendar event created successfully by {organizer_email or 'default user'}",
                "organizer": organizer_email
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _send_meeting_email(self, to: List[str], subject: str, body: str,
                            html_body: str = "", email_type: str = "proposal",
                            sender_email: str = None) -> Dict[str, Any]:
        """Send meeting-related email from specified authenticated user"""
        try:
            # Validate that sender is authenticated
            if sender_email and not self.google_service.is_user_authenticated(sender_email):
                return {
                    "success": False,
                    "error": f"Sender '{sender_email}' is not authenticated. Please authenticate first."
                }
            
            email_message = EmailMessage(
                to=to,
                subject=subject,
                body=body,
                html_body=html_body if html_body else None
            )
            
            # Send email from specified sender
            success = self.google_service.send_email(email_message, sender_email)
            
            return {
                "success": success,
                "message": f"Email {email_type} sent successfully from {sender_email or 'default user'}" if success else "Failed to send email",
                "email_type": email_type,
                "sender": sender_email
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _check_email_responses(self, proposal_id: str, query: str = "", 
                               max_results: int = 10, user_email: str = None) -> Dict[str, Any]:
        """Check for email responses from specified authenticated user's inbox"""
        try:
            # Validate that user is authenticated
            if user_email and not self.google_service.is_user_authenticated(user_email):
                return {
                    "success": False,
                    "error": f"User '{user_email}' is not authenticated. Please authenticate first."
                }
            
            # Search for emails related to the proposal
            if not query:
                query = f"meeting proposal {proposal_id}"
            
            emails = self.google_service.get_recent_emails(query, max_results, user_email)
            
            # Parse responses for confirmations/rejections
            responses = []
            for email in emails:
                response_type = self._parse_email_response(email["body"])
                responses.append({
                    "email_id": email["id"],
                    "sender": email["sender"],
                    "subject": email["subject"],
                    "response_type": response_type,
                    "body_snippet": email["body"][:200]
                })
            
            return {
                "success": True,
                "responses": responses,
                "total_found": len(emails),
                "checked_inbox": user_email
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _parse_email_response(self, email_body: str) -> str:
        """Parse email body to determine response type"""
        body_lower = email_body.lower()
        
        # Simple keyword-based parsing
        if any(word in body_lower for word in ["yes", "confirm", "accept", "agree", "sounds good"]):
            return "confirmation"
        elif any(word in body_lower for word in ["no", "decline", "reject", "can't", "cannot"]):
            return "rejection"
        elif any(word in body_lower for word in ["reschedule", "different time", "another time"]):
            return "reschedule_request"
        else:
            return "unclear"
    
    def _create_system_message(self, user_preferences: Optional[UserPreferences]) -> str:
        """Create system message for the agent with multi-user awareness"""
        prefs = user_preferences or UserPreferences()
        
        return f"""You are SchedulAI, an intelligent meeting scheduling agent with multi-user authentication support.

Your capabilities:
1. Analyze meeting requests and participant availability
2. Access calendars of authenticated users only 
3. Suggest optimal meeting times based on multiple factors
4. Handle email communications from specific authenticated users
5. Create calendar events through authenticated organizers

Multi-User Authentication Rules:
- Only authenticated users can access their calendar data
- External/non-authenticated users will show empty availability
- Always specify which authenticated user should perform calendar/email operations
- Use organizer's credentials for creating events and sending emails

Key scheduling principles:
- Work hours: {prefs.work_start_hour}:00 - {prefs.work_end_hour}:00
- Preferred days: {', '.join(prefs.preferred_meeting_days)}
- Buffer time: {prefs.buffer_time_minutes} minutes between meetings
- Avoid lunch: {prefs.lunch_break_start}:00 - {prefs.lunch_break_start + 1}:00

When scheduling:
- High/urgent priority: Prefer earlier slots, shorter delays
- Medium priority: Balance convenience and timing
- Low priority: Optimize for participant convenience

CRITICAL: Always start by checking authenticated users, then specify which user should perform each action.
Always explain your reasoning and be proactive in resolving conflicts.
Use the available tools systematically to gather data and execute actions."""
    
    def _create_meeting_request_message(self, meeting_request: MeetingRequest) -> str:
        """Create user message describing the meeting request with multi-user context"""
        organizer = f"{meeting_request.organizer.name} ({meeting_request.organizer.email})"
        participants = [f"{p.name} ({p.email})" for p in meeting_request.participants]
        all_attendees = [organizer] + participants
        
        return f"""Please schedule the following meeting with multi-user authentication support:

Title: {meeting_request.title}
Description: {meeting_request.description}
Duration: {meeting_request.duration_minutes} minutes
Priority: {meeting_request.priority.value}

Organizer: {organizer} [Meeting requester - use their credentials for calendar/email operations]
Additional Participants: {', '.join(participants) if participants else 'None'}
Total Attendees: {len(all_attendees)}

Additional requirements:
- Preferred days: {', '.join(meeting_request.preferred_days) if meeting_request.preferred_days else 'Any weekday'}
- Buffer time: {meeting_request.buffer_time_minutes} minutes

Multi-User Instructions:
1. First, check which users are authenticated
2. Verify organizer ({meeting_request.organizer.email}) is authenticated
3. Check availability for all attendees (authenticated users will show real data)
4. Use organizer's credentials for creating events and sending emails
5. Consider that external participants may not show availability data

Scheduling hierarchy:
1. Organizer preferences have highest priority
2. Find slots that work for ALL authenticated attendees
3. Optimize based on meeting priority and work hours

Please:
1. Check authenticated users first
2. Check availability for all {len(all_attendees)} attendees
3. Analyze and suggest the best 3 time slots that work for authenticated participants
4. Create calendar event using organizer's credentials
5. Send meeting proposal emails from organizer's account
6. Explain your reasoning and any limitations due to authentication"""

    def confirm_meeting(self, proposal_id: str, slot_index: int) -> Dict[str, Any]:
        """Confirm a meeting proposal with multi-user support"""
        if proposal_id not in self.proposals:
            return {"success": False, "error": "Proposal not found"}
        
        proposal = self.proposals[proposal_id]
        if slot_index >= len(proposal.suggested_slots):
            return {"success": False, "error": "Invalid slot index"}
        
        selected_slot = proposal.suggested_slots[slot_index]
        
        # Get all attendee emails (organizer + participants)
        all_attendees = proposal.meeting_request.get_all_emails()
        organizer_email = proposal.meeting_request.organizer.email
        
        # Verify organizer is authenticated
        if not self.google_service.is_user_authenticated(organizer_email):
            return {
                "success": False, 
                "error": f"Organizer '{organizer_email}' is not authenticated. Cannot create calendar event."
            }
        
        # Create calendar event using organizer's credentials
        event_result = self._create_calendar_event(
            title=proposal.meeting_request.title,
            description=proposal.meeting_request.description,
            start_time=selected_slot.start_time.isoformat(),
            end_time=selected_slot.end_time.isoformat(),
            attendees=all_attendees,
            organizer_email=organizer_email
        )
        
        if event_result["success"]:
            # Send confirmation emails from organizer's account
            self._send_meeting_email(
                to=all_attendees,
                subject=f"Meeting Confirmed: {proposal.meeting_request.title}",
                body=f"Your meeting '{proposal.meeting_request.title}' has been confirmed for {selected_slot.start_time.strftime('%A, %B %d at %I:%M %p')}.\n\nOrganizer: {proposal.meeting_request.organizer.name}\nAttendees: {len(all_attendees)} total",
                email_type="confirmation",
                sender_email=organizer_email
            )
            
            # Update proposal status
            proposal.status = "confirmed"
            
            return {
                "success": True,
                "event_id": event_result["event_id"],
                "confirmed_slot": {
                    "start_time": selected_slot.start_time.isoformat(),
                    "end_time": selected_slot.end_time.isoformat()
                },
                "total_attendees": len(all_attendees),
                "organizer": organizer_email,
                "organizer_authenticated": True
            }
        else:
            return {"success": False, "error": event_result["error"]} 