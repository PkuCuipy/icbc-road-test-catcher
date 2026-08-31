# ICBC Road Test Catcher

An automated Python script that monitors and books available road test appointments at ICBC (Insurance Corporation of British Columbia) locations in Canada.

## Problem Statement

Road test appointments in British Columbia are typically booked solid for 6+ months in advance, making it extremely difficult to find earlier available slots. This script continuously monitors the ICBC booking system and automatically secures the earliest available appointment within your preferred date range.

## Features

- **Automated Monitoring**: Continuously checks for available appointments every 90 seconds
- **Smart Filtering**: Only considers appointments within your specified date range
- **Full Automation**: Complete booking process without manual intervention
- **Email Integration**: Automatically retrieves and processes OTP codes from Gmail
- **Token Management**: Handles authentication token refresh automatically
- **Multi-location Support**: Can monitor multiple ICBC locations simultaneously
- **Error Handling**: Robust error handling with retry mechanisms
- **Docker Support**: Easy deployment with Docker Compose for consistent environment
- **Timezone Aware**: Properly configured for Pacific Time (America/Vancouver)

## How It Works

1. **Authentication**: Logs into ICBC system using your credentials
2. **Monitoring**: Continuously scans for available appointments
3. **Booking Process**: When a suitable slot is found:
   - Locks the appointment temporarily
   - Requests OTP code via email
   - Automatically retrieves OTP from Gmail
   - Verifies the OTP code
   - Completes the booking

## Prerequisites

### For Docker Installation (Recommended)
- Docker and Docker Compose installed
- Gmail account with App Password enabled
- Valid ICBC learner's license and credentials

### For Local Python Installation
- Python 3.7+
- Gmail account with App Password enabled
- Valid ICBC learner's license and credentials

## Installation

### Option 1: Docker (Recommended)

1. Clone the repository:
```bash
git clone https://github.com/l1ve4code/icbc-road-test-catcher.git
cd icbc-road-test-catcher
```

2. Configure your credentials in `docker-compose.yml` (see Configuration section below)

3. Run with Docker Compose:
```bash
docker-compose up -d
```

### Option 2: Local Python Installation

1. Clone the repository:
```bash
git clone https://github.com/l1ve4code/icbc-road-test-catcher.git
cd icbc-road-test-catcher
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

### Docker Configuration (Recommended)

Edit the `docker-compose.yml` file and replace the placeholder values with your personal information:

```yaml
environment:
  - TZ=America/Vancouver
  - USER_LAST_NAME=YourLastName          # Replace with your last name
  - USER_LICENSE_NUMBER=1234567          # Replace with your license number
  - USER_KEYWORD=your_keyword_here       # Replace with your ICBC keyword
  - USER_GMAIL=your.email@gmail.com      # Replace with your Gmail address
  - USER_GMAIL_APP_PASSWORD=your_16_character_app_password  # Replace with Gmail App Password
  - DESIRED_DATE_START=2025-06-24        # Replace with your preferred start date (YYYY-MM-DD)
  - DESIRED_DATE_END=2025-06-30          # Replace with your preferred end date (YYYY-MM-DD)
```

### Local Python Configuration

Edit the `CONFIG` dictionary in `main.py` with your personal information, or set environment variables:

```bash
export USER_LAST_NAME="YourLastName"
export USER_LICENSE_NUMBER="1234567"
export USER_KEYWORD="your_keyword_here"
export USER_GMAIL="your.email@gmail.com"
export USER_GMAIL_APP_PASSWORD="your_16_character_app_password"
export DESIRED_DATE_START="2025-06-24"
export DESIRED_DATE_END="2025-06-30"
```

**Note**: You must enable 2-factor authentication on Gmail and generate an App Password. Regular Gmail passwords won't work.

### Date Range

The desired date range is now configured via environment variables:
- `DESIRED_DATE_START`: Start date in YYYY-MM-DD format (default: 2025-06-24)
- `DESIRED_DATE_END`: End date in YYYY-MM-DD format (default: 2025-06-30)

### Location IDs

Configured via the `LOCATION_IDS` environment variable, a comma-separated list of ICBC location IDs. **Required** — the script will refuse to start if it's not set:
```bash
export LOCATION_IDS="9"          # Vancouver driver licensing (Point Grey)
export LOCATION_IDS="9,214"      # multiple locations
```

### Booking Notification Email

Configured via the `NOTIFY_EMAILS` environment variable, a comma-separated list of email addresses to notify when a booking succeeds. Optional — if unset, no notification is sent. Sent from the same `USER_GMAIL` account (via SMTP):
```bash
export NOTIFY_EMAILS="you@example.com,someone.else@example.com"
```

### Other Settings
```python
"check_interval": 90,           # Seconds between appointment checks
"token_refresh_interval": 1500  # Seconds between token refreshes (25 minutes)
```

## Gmail App Password Setup

1. Enable 2-Factor Authentication on your Google account
2. Go to Google Account settings → Security → App passwords
3. Generate a new app password for "Mail"
4. Use this 16-character password in the configuration

## Usage

### Docker Usage (Recommended)

1. Start the container:
```bash
docker-compose up -d
```

2. View logs:
```bash
docker-compose logs -f icbc-catcher
```

Verbose logs (including request/response details and timing) are also written to a timestamped file under `./logs/` on the host (e.g. `logs/icbc_catcher_20260830_221530.log`), mounted from `/app/logs` in the container. A new log file is created each time the container starts.

3. Stop the container:
```bash
docker-compose down
```

### Local Python Usage

Export the required environment variables (see [Configuration](#configuration) above — `LOCATION_IDS` is required, `NOTIFY_EMAILS` is optional), then run the script:
```bash
export USER_LAST_NAME="YourLastName"
export USER_LICENSE_NUMBER="1234567"
export USER_KEYWORD="your_keyword_here"
export USER_GMAIL="your.email@gmail.com"
export USER_GMAIL_APP_PASSWORD="your_16_character_app_password"
export DESIRED_DATE_START="2025-06-24"
export DESIRED_DATE_END="2025-06-30"
export LOCATION_IDS="9"
export NOTIFY_EMAILS="you@example.com"   # optional

python main.py
```

No extra dependencies are needed for logging or email — it only uses `httpx`/`pytz` from `requirements.txt` plus the Python standard library. Logs are written to `./logs/` relative to wherever you run the script from, in addition to stdout.

### What the script does:
- Start monitoring immediately
- Display status updates in the console
- Automatically book when a suitable appointment is found
- Stop execution after successful booking

## Sample Output

```
Token refreshed. drvrID: 12345678
Script started. Beginning monitoring for available dates...
Found 3 available dates for location 214
Found early date: 2025-06-25
Date 2025-06-25 successfully locked
OTP code sent to email
OTP code successfully verified
Booking completed successfully!
Booking completed successfully! Script terminating.
```

## Location IDs

Common ICBC locations and their IDs:
- Duncan: 214
- Vancouver driver licensing (Point Grey): 9
- Victoria: (add ID if known)

To find other location IDs, inspect network traffic in your browser when selecting different locations on the ICBC website.

## Important Notes

- **Rate Limiting**: The script respects ICBC's servers with reasonable intervals
- **Legal Compliance**: This tool automates the same process you would do manually
- **Single Use**: Script stops after successfully booking one appointment
- **Timezone**: Configured for Pacific Time (America/Vancouver)

## Troubleshooting

### Docker Commands

```bash
# View container logs
docker-compose logs -f icbc-catcher

# Restart the container
docker-compose restart icbc-catcher

# Rebuild the container (after code changes)
docker-compose up --build -d

# Access container shell for debugging
docker-compose exec icbc-catcher /bin/bash

# Remove container and volumes
docker-compose down -v
```

### Common Issues

1. **Authentication Failed**
   - Verify your ICBC credentials are correct
   - Check that your license is valid and active

2. **Gmail Connection Issues**
   - Ensure 2FA is enabled on Gmail
   - Verify App Password is correctly generated and entered
   - Check IMAP is enabled in Gmail settings

3. **No Appointments Found**
   - Adjust your date range
   - Add more location IDs
   - Check if appointments are available manually on ICBC website

4. **Token Refresh Errors**
   - Usually resolves automatically on next refresh cycle
   - Restart script if persistent

5. **Docker Issues**
   - Ensure Docker and Docker Compose are installed
   - Check container logs: `docker-compose logs icbc-catcher`
   - Verify timezone is set correctly in container

## Disclaimer

This tool is for educational purposes and personal use only. Users are responsible for:
- Complying with ICBC terms of service
- Using the tool responsibly and ethically
- Not overloading ICBC servers

## Author

**Telegram:** [@live4code](https://t.me/live4code)  
**Email:** steven.marelly@gmail.com
