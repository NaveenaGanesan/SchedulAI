# SchedulAI

> **Autonomous Meeting Booking Agent with OpenAI Function Calling**

SchedulAI is an intelligent meeting scheduler that uses OpenAI Function Calling to automatically coordinate meetings by integrating with Google Calendar and Gmail APIs.

## 🚀 **Quick Start**

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment**
   ```bash
   cp env.example .env
   # Edit .env with your API keys
   ```

3. **Run Application**
   ```bash
   python -m app.main
   ```

4. **Access API**
   - API: `http://localhost:8000`
   - Documentation: `http://localhost:8000/docs`

## 📚 **Documentation**

**📖 [SCHEDULEAI_DOCUMENTATION.md](./SCHEDULEAI_DOCUMENTATION.md)** - Complete documentation including architecture, setup, authentication, API reference, and requirements.

**🧪 [TESTING_GUIDE.md](./TESTING_GUIDE.md)** - Step-by-step testing guide with all commands and expected responses.

## 🔧 **Architecture**

```
app/
├── main.py              # FastAPI application
├── models/              # Domain models (meeting, user, api, agent)
├── services/            # Business logic (agent, google)
├── api/                 # API layer (routes, middleware, dependencies)
├── core/                # Core utilities (logging, exceptions)
└── utils/               # Helper utilities (validators)
```

## 🤖 **AI Agent Tools**

- **`get_calendar_availability`** - Fetch participant availability
- **`analyze_optimal_slots`** - AI-powered slot optimization  
- **`create_calendar_event`** - Calendar event management
- **`send_meeting_email`** - Automated email communication
- **`check_email_responses`** - Response parsing and tracking

## 📋 **Requirements**

- Python 3.8+
- OpenAI API Key
- Google Cloud Project (Calendar + Gmail APIs)
- OAuth2 Credentials

## ⚡ **Key Features**

- 🤖 **OpenAI Function Calling** - AI agent with specialized tools
- 📅 **Google Calendar Integration** - Real-time availability checking
- 📧 **Gmail Integration** - Automated meeting coordination
- 🎯 **Smart Scheduling** - AI-powered optimal slot selection
- 🏗️ **Clean Architecture** - Layered design with domain separation
- 🔒 **Secure Authentication** - OAuth2 integration

---

**License:** MIT | **Version:** 1.0.0
