"""
Google API Service for Calendar and Gmail integration

Handles authentication and operations with Google Calendar and Gmail APIs.
"""

import pickle
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import email.mime.text as mime_text
import base64

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.credentials import Credentials
from googleapiclient.errors import HttpError

from app.models import CalendarEvent, EmailMessage, TimeSlot, AvailabilityResponse
from app.config import config
from app.core.logging import get_logger
from app.core.exceptions import GoogleServiceException, CalendarException, EmailException

logger = get_logger(__name__)

class GoogleService:
    """Unified Google service for Calendar and Gmail APIs"""
    
    def __init__(self):
        logger.info("Initializing Google Service...")
        self.credentials = None
        self.calendar_service = None
        self.gmail_service = None
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Google APIs using OAuth2"""
        logger.info("Starting Google API authentication...")
        creds = None
        
        # Load existing token
        if os.path.exists(config.GOOGLE_TOKEN_FILE):
            logger.debug(f"Loading existing token from: {config.GOOGLE_TOKEN_FILE}")
            try:
                with open(config.GOOGLE_TOKEN_FILE, 'rb') as token:
                    creds = pickle.load(token)
                logger.debug("Token loaded successfully")
            except Exception as e:
                logger.warning(f"Failed to load token: {str(e)}")
        else:
            logger.info("No existing token found")
        
        # If there are no valid credentials, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired credentials...")
                try:
                    creds.refresh(Request())
                    logger.info("Credentials refreshed successfully")
                except Exception as e:
                    logger.error(f"Failed to refresh credentials: {str(e)}")
                    creds = None
            
            if not creds or not creds.valid:
                logger.info("Starting new OAuth2 flow...")
                if os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
                    logger.debug(f"Using credentials file: {config.GOOGLE_CREDENTIALS_FILE}")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        config.GOOGLE_CREDENTIALS_FILE, 
                        config.GOOGLE_SCOPES
                    )
                    logger.info("Starting local server for OAuth2...")
                    creds = flow.run_local_server(port=0)
                    logger.info("OAuth2 flow completed successfully")
                else:
                    logger.error(f"Google credentials file not found: {config.GOOGLE_CREDENTIALS_FILE}")
                    raise FileNotFoundError(f"Google credentials file not found: {config.GOOGLE_CREDENTIALS_FILE}")
            
            # Save the credentials for the next run
            logger.debug(f"Saving credentials to: {config.GOOGLE_TOKEN_FILE}")
            try:
                with open(config.GOOGLE_TOKEN_FILE, 'wb') as token:
                    pickle.dump(creds, token)
                logger.debug("Credentials saved successfully")
            except Exception as e:
                logger.warning(f"Failed to save credentials: {str(e)}")
        
        # Build services
        logger.info("Building Google API services...")
        try:
            self.credentials = creds
            self.calendar_service = build('calendar', 'v3', credentials=creds)
            self.gmail_service = build('gmail', 'v1', credentials=creds)
            
            logger.info("Google services authenticated successfully")
            logger.debug(f"Available scopes: {', '.join(config.GOOGLE_SCOPES)}")
        except Exception as e:
            logger.error(f"Failed to build Google services: {str(e)}")
            raise
    
    # Calendar Methods
    def get_calendar_availability(self, participant_emails: List[str], 
                                start_date: datetime, end_date: datetime) -> List[AvailabilityResponse]:
        """Get availability for multiple participants"""
        try:
            availability_responses = []
            
            for email in participant_emails:
                # Get busy times for this participant
                body = {
                    'timeMin': start_date.isoformat(),
                    'timeMax': end_date.isoformat(),
                    'items': [{'id': email}]
                }
                
                try:
                    freebusy_result = self.calendar_service.freebusy().query(body=body).execute()
                    busy_times = freebusy_result['calendars'].get(email, {}).get('busy', [])
                    
                    # Convert busy times to TimeSlot objects
                    busy_slots = []
                    for busy_period in busy_times:
                        start_time = datetime.fromisoformat(busy_period['start'].replace('Z', '+00:00'))
                        end_time = datetime.fromisoformat(busy_period['end'].replace('Z', '+00:00'))
                        busy_slots.append(TimeSlot(
                            start_time=start_time,
                            end_time=end_time,
                            available=False
                        ))
                    
                    # Calculate free slots
                    free_slots = self._calculate_free_slots(start_date, end_date, busy_slots)
                    
                    availability_responses.append(AvailabilityResponse(
                        participant_email=email,
                        free_slots=free_slots,
                        busy_slots=busy_slots
                    ))
                    
                except HttpError as e:
                    print(f"Error getting availability for {email}: {e}")
                    # Add empty availability for this participant
                    availability_responses.append(AvailabilityResponse(
                        participant_email=email,
                        free_slots=[],
                        busy_slots=[]
                    ))
            
            return availability_responses
            
        except HttpError as error:
            print(f'Calendar API error: {error}')
            return []
    
    def _calculate_free_slots(self, start_date: datetime, end_date: datetime, 
                             busy_slots: List[TimeSlot]) -> List[TimeSlot]:
        """Calculate free time slots from busy periods"""
        free_slots = []
        
        # Sort busy slots by start time
        busy_slots.sort(key=lambda x: x.start_time)
        
        current_time = start_date
        
        for busy_slot in busy_slots:
            # If there's a gap before this busy slot, it's free time
            if current_time < busy_slot.start_time:
                free_slots.append(TimeSlot(
                    start_time=current_time,
                    end_time=busy_slot.start_time,
                    available=True
                ))
            
            # Move current time to end of busy slot
            current_time = max(current_time, busy_slot.end_time)
        
        # Add final free slot if there's time remaining
        if current_time < end_date:
            free_slots.append(TimeSlot(
                start_time=current_time,
                end_time=end_date,
                available=True
            ))
        
        return free_slots
    
    def create_calendar_event(self, event: CalendarEvent) -> Optional[str]:
        """Create a calendar event"""
        try:
            # Prepare attendees
            attendees = [{'email': email} for email in event.attendees]
            
            # Create event body
            event_body = {
                'summary': event.title,
                'description': event.description,
                'start': {
                    'dateTime': event.start_time.isoformat(),
                    'timeZone': event.timezone,
                },
                'end': {
                    'dateTime': event.end_time.isoformat(),
                    'timeZone': event.timezone,
                },
                'attendees': attendees,
                'sendUpdates': 'all'
            }
            
            if event.location:
                event_body['location'] = event.location
            
            # Create the event
            created_event = self.calendar_service.events().insert(
                calendarId='primary', 
                body=event_body,
                sendUpdates='all'
            ).execute()
            
            print(f"✅ Calendar event created: {created_event.get('id')}")
            return created_event.get('id')
            
        except HttpError as error:
            print(f'Error creating calendar event: {error}')
            return None
    
    def get_calendar_events(self, start_date: datetime, end_date: datetime) -> List[CalendarEvent]:
        """Get calendar events in date range"""
        try:
            time_min = start_date.isoformat()
            time_max = end_date.isoformat()
            
            events_result = self.calendar_service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            calendar_events = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                start_time = datetime.fromisoformat(start.replace('Z', '+00:00'))
                end_time = datetime.fromisoformat(end.replace('Z', '+00:00'))
                
                attendees = []
                if 'attendees' in event:
                    attendees = [attendee['email'] for attendee in event['attendees']]
                
                calendar_events.append(CalendarEvent(
                    id=event['id'],
                    title=event.get('summary', 'No title'),
                    description=event.get('description', ''),
                    start_time=start_time,
                    end_time=end_time,
                    attendees=attendees,
                    location=event.get('location', ''),
                    timezone=event.get('start', {}).get('timeZone', 'UTC')
                ))
            
            return calendar_events
            
        except HttpError as error:
            print(f'Error fetching calendar events: {error}')
            return []
    
    # Gmail Methods
    def send_email(self, email_message: EmailMessage) -> bool:
        """Send email using Gmail API"""
        try:
            # Create message
            message = MimeMultipart('alternative')
            message['To'] = ', '.join(email_message.to)
            message['Subject'] = email_message.subject
            
            # Add plain text part
            text_part = MimeText(email_message.body, 'plain')
            message.attach(text_part)
            
            # Add HTML part if provided
            if email_message.html_body:
                html_part = MimeText(email_message.html_body, 'html')
                message.attach(html_part)
            
            # Encode message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            # Send message
            send_message = {
                'raw': raw_message
            }
            
            # Add thread ID if provided (for replies)
            if email_message.thread_id:
                send_message['threadId'] = email_message.thread_id
            
            result = self.gmail_service.users().messages().send(
                userId='me',
                body=send_message
            ).execute()
            
            print(f"✅ Email sent successfully: {result.get('id')}")
            return True
            
        except HttpError as error:
            print(f'Error sending email: {error}')
            return False
    
    def get_recent_emails(self, query: str = '', max_results: int = 10) -> List[Dict[str, Any]]:
        """Get recent emails matching query"""
        try:
            results = self.gmail_service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            email_list = []
            
            for message in messages:
                msg = self.gmail_service.users().messages().get(
                    userId='me',
                    id=message['id']
                ).execute()
                
                # Extract email details
                headers = msg['payload'].get('headers', [])
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
                sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
                date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
                
                # Get body (simplified)
                body = ''
                if 'parts' in msg['payload']:
                    for part in msg['payload']['parts']:
                        if part['mimeType'] == 'text/plain':
                            body = base64.urlsafe_b64decode(
                                part['body']['data']
                            ).decode('utf-8')
                            break
                
                email_list.append({
                    'id': message['id'],
                    'thread_id': msg['threadId'],
                    'subject': subject,
                    'sender': sender,
                    'date': date,
                    'body': body
                })
            
            return email_list
            
        except HttpError as error:
            print(f'Error fetching emails: {error}')
            return []
    
    def validate_services(self) -> Dict[str, bool]:
        """Validate that both services are working"""
        calendar_working = False
        gmail_working = False
        
        try:
            # Test Calendar API
            self.calendar_service.calendarList().list().execute()
            calendar_working = True
        except Exception as e:
            print(f"Calendar API validation failed: {e}")
        
        try:
            # Test Gmail API
            self.gmail_service.users().getProfile(userId='me').execute()
            gmail_working = True
        except Exception as e:
            print(f"Gmail API validation failed: {e}")
        
        return {
            'calendar': calendar_working,
            'gmail': gmail_working,
            'authenticated': calendar_working and gmail_working
        } 