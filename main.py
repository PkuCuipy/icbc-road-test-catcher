from datetime import datetime, timedelta
from email.mime.text import MIMEText
import imaplib
import smtplib
import httpx
import email
import time
import pytz
import re
import os
import sys
import logging

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
_log_start = datetime.now(pytz.timezone("America/Vancouver")).strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"icbc_catcher_{_log_start}.log")

logger = logging.getLogger("icbc_catcher")
logger.setLevel(logging.DEBUG)
_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setFormatter(_formatter)
logger.addHandler(_stdout_handler)

_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(_formatter)
logger.addHandler(_file_handler)

CONFIG = {
    "login_url": "https://onlinebusiness.icbc.com/deas-api/v1/webLogin/webLogin",
    "appointments_url": "https://onlinebusiness.icbc.com/deas-api/v1/web/getAvailableAppointments",
    "lock_url": "https://onlinebusiness.icbc.com/deas-api/v1/web/lock",
    "send_otp_url": "https://onlinebusiness.icbc.com/deas-api/v1/web/sendOTP",
    "verify_otp_url": "https://onlinebusiness.icbc.com/deas-api/v1/web/verifyOTP",
    "book_url": "https://onlinebusiness.icbc.com/deas-api/v1/web/book",

    "credentials": {
        "drvrLastName": os.getenv("USER_LAST_NAME"),
        "licenceNumber": os.getenv("USER_LICENSE_NUMBER"),
        "keyword": os.getenv("USER_KEYWORD")
    },

    "appointment_request_base": {
        "examType": "5-R-1",
        "examDate": "2025-06-13",
        "prfDaysOfWeek": "[0,1,2,3,4,5,6]",
        "prfPartsOfDay": "[0,1]",
        "lastName": os.getenv("USER_LAST_NAME"),
        "licenseNumber": os.getenv("USER_LICENSE_NUMBER")
    },

    # Comma-separated ICBC location IDs, e.g. "9,93". Required, no default.
    "location_ids": [int(x.strip()) for x in os.getenv("LOCATION_IDS", "").split(",") if x.strip()],

    "gmail": {
        "email": os.getenv("USER_GMAIL"),
        "password": os.getenv("USER_GMAIL_APP_PASSWORD"),
        "imap_server": "imap.gmail.com",
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 465
    },

    # Comma-separated emails to notify on successful booking, e.g. "a@x.com,b@y.com". Optional.
    "notify_emails": [e.strip() for e in os.getenv("NOTIFY_EMAILS", "").split(",") if e.strip()],

    "desired_date_range": {
        "start": os.getenv("DESIRED_DATE_START", "2025-06-24"),
        "end": os.getenv("DESIRED_DATE_END", "2025-06-30")
    },

    "timezone": "America/Vancouver",
    "check_interval": 577,  # in seconds, set to a prime number to avoid sync with ICBC server
    "token_refresh_interval": 1500
}

current_token = None
last_token_refresh = None
drvr_id = None


def validate_config():
    """Validate that all required environment variables are set"""
    required_vars = [
        "USER_LAST_NAME",
        "USER_LICENSE_NUMBER",
        "USER_KEYWORD",
        "USER_GMAIL",
        "USER_GMAIL_APP_PASSWORD",
        "LOCATION_IDS"
    ]

    optional_vars = ["DESIRED_DATE_START", "DESIRED_DATE_END"]

    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set these variables in your .env file or environment")
        return False

    if not CONFIG["location_ids"]:
        logger.error(f"LOCATION_IDS is set but could not be parsed as a comma-separated list of integers: "
                     f"{os.getenv('LOCATION_IDS')!r}")
        return False

    if not CONFIG["notify_emails"]:
        logger.debug("NOTIFY_EMAILS not set — no booking notification email will be sent")

    logger.debug(f"Config validated. desired_date_range={CONFIG['desired_date_range']}, "
                 f"location_ids={CONFIG['location_ids']}, notify_emails={CONFIG['notify_emails']}, "
                 f"check_interval={CONFIG['check_interval']}s")
    return True


def refresh_token():
    global current_token, last_token_refresh, drvr_id
    logger.info("Attempting to refresh auth token...")
    t0 = time.monotonic()
    try:
        with httpx.Client() as client:
            logger.debug(f"PUT {CONFIG['login_url']} payload={{'drvrLastName': '{CONFIG['credentials']['drvrLastName']}', "
                         f"'licenceNumber': '***', 'keyword': '***'}}")
            response = client.put(
                CONFIG["login_url"],
                json=CONFIG["credentials"],
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0"
                }
            )
            elapsed = time.monotonic() - t0
            logger.debug(f"Login response: status={response.status_code} elapsed={elapsed:.2f}s")
            response.raise_for_status()

            auth_header = response.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                current_token = auth_header
                last_token_refresh = datetime.now(pytz.timezone(CONFIG['timezone']))

                try:
                    login_data = response.json()
                    drvr_id = login_data.get('drvrId')
                    logger.info(f"Token refreshed successfully. drvrID: {drvr_id}")
                except Exception:
                    logger.warning("Token refreshed but failed to parse drvrID from response body")

                return True

        logger.error(f"Failed to get token from response headers. status={response.status_code} headers={dict(response.headers)}")
        return False
    except Exception as e:
        logger.error(f"Error refreshing token after {time.monotonic() - t0:.2f}s: {e}")
        return False


def get_earliest_appointment():
    global current_token

    if not current_token:
        if not refresh_token():
            return None

    try:
        earliest_appointment = None
        desired_start = datetime.strptime(CONFIG["desired_date_range"]["start"], "%Y-%m-%d").date()
        desired_end = datetime.strptime(CONFIG["desired_date_range"]["end"], "%Y-%m-%d").date()
        logger.info(f"Checking for available appointments between {desired_start} and {desired_end}...")

        with httpx.Client() as client:
            for location_id in CONFIG["location_ids"]:
                request_data = CONFIG["appointment_request_base"].copy()
                request_data["aPosID"] = location_id
                logger.debug(f"POST {CONFIG['appointments_url']} payload={request_data}")

                t0 = time.monotonic()
                response = client.post(
                    CONFIG["appointments_url"],
                    json=request_data,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": current_token,
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0"
                    }
                )
                elapsed = time.monotonic() - t0
                logger.debug(f"Appointments response: status={response.status_code} elapsed={elapsed:.2f}s location={location_id}")
                response.raise_for_status()

                appointments = response.json()
                logger.info(f"Found {len(appointments)} available dates for location {location_id}")

                all_dates = [a["appointmentDt"]["date"] for a in appointments if "appointmentDt" in a]
                if all_dates:
                    logger.debug(f"Location {location_id} raw available dates: {all_dates}")

                for appointment in appointments:
                    if "appointmentDt" in appointment:
                        appointment_date = datetime.strptime(appointment["appointmentDt"]["date"], "%Y-%m-%d").date()

                        if desired_start <= appointment_date <= desired_end:
                            logger.info(f"Match found within desired range: {appointment_date} at location {location_id}")
                            if (earliest_appointment is None or
                                    appointment_date < datetime.strptime(earliest_appointment["appointmentDt"]["date"],
                                                                         "%Y-%m-%d").date()):
                                earliest_appointment = appointment

        if earliest_appointment is None:
            logger.debug("No appointment within desired date range across all checked locations")
            canary_check()

        return earliest_appointment

    except Exception as e:
        logger.error(f"Error checking available dates: {e}", exc_info=True)
        current_token = None
        return None


def canary_check():
    """Diagnostic-only check: is the ICBC API returning ANY appointments at all,
    within a much wider window (tomorrow to +178 days)? Never acted upon —
    purely so the log can confirm the script is still working even when
    nothing matches the desired date range."""
    global current_token

    if not current_token:
        logger.warning("Canary check skipped: no auth token available")
        return

    canary_start = datetime.now(pytz.timezone(CONFIG["timezone"])).date() + timedelta(days=1)
    canary_end = canary_start + timedelta(days=178)

    try:
        with httpx.Client() as client:
            for location_id in CONFIG["location_ids"]:
                request_data = CONFIG["appointment_request_base"].copy()
                request_data["aPosID"] = location_id
                request_data["examDate"] = canary_start.strftime("%Y-%m-%d")

                response = client.post(
                    CONFIG["appointments_url"],
                    json=request_data,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": current_token,
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0"
                    }
                )
                response.raise_for_status()

                appointments = response.json()
                canary_dates = sorted({
                    a["appointmentDt"]["date"] for a in appointments if "appointmentDt" in a
                    and canary_start <= datetime.strptime(a["appointmentDt"]["date"], "%Y-%m-%d").date() <= canary_end
                })

                if canary_dates:
                    logger.info(f"[CANARY] Location {location_id}: {len(canary_dates)} date(s) available "
                                f"within {canary_start} to {canary_end} (outside desired range, not acting on this): "
                                f"{canary_dates}")
                else:
                    logger.info(f"[CANARY] Location {location_id}: 0 dates available within "
                                f"{canary_start} to {canary_end}. Script is running normally, ICBC just has nothing open.")

    except Exception as e:
        logger.warning(f"[CANARY] Check failed (this does not affect normal booking logic): {e}")


def lock_appointment(appointment):
    global current_token, drvr_id

    if not current_token or not drvr_id:
        if not refresh_token():
            return None

    try:
        booked_ts = datetime.now(pytz.timezone(CONFIG['timezone'])).strftime("%Y-%m-%dT%H:%M:%S")

        unlock_data = {"appointmentDt": {}, "dlExam": {}, "drvrDriver": {"drvrId": drvr_id}, "drscDrvSchl": {}}

        lock_data = {
            "appointmentDt": appointment["appointmentDt"],
            "dlExam": appointment["dlExam"],
            "drvrDriver": {"drvrId": drvr_id},
            "drscDrvSchl": {},
            "instructorDlNum": None,
            "bookedTs": booked_ts,
            "startTm": appointment["startTm"],
            "endTm": appointment["endTm"],
            "posId": appointment["posId"],
            "resourceId": appointment["resourceId"],
            "signature": appointment["signature"]
        }

        logger.info(f"Attempting to lock appointment on {appointment['appointmentDt']['date']}...")
        with httpx.Client() as client:
            logger.debug(f"PUT {CONFIG['lock_url']} (unlock/reset) payload={unlock_data}")
            t0 = time.monotonic()
            response = client.put(
                CONFIG["lock_url"],
                json=unlock_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": current_token,
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0"
                }
            )
            logger.debug(f"Unlock response: status={response.status_code} elapsed={time.monotonic() - t0:.2f}s")
            response.raise_for_status()

            logger.debug("Sleeping 10s between unlock and lock calls...")
            time.sleep(10)

            logger.debug(f"PUT {CONFIG['lock_url']} (lock) payload={lock_data}")
            t0 = time.monotonic()
            response = client.put(
                CONFIG["lock_url"],
                json=lock_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": current_token,
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0"
                }
            )
            logger.debug(f"Lock response: status={response.status_code} elapsed={time.monotonic() - t0:.2f}s")
            response.raise_for_status()

            resulting_timezone = response.json()

            logger.info(f"Date {appointment['appointmentDt']['date']} successfully locked. bookedTs={resulting_timezone.get('bookedTs')}")
            return resulting_timezone["bookedTs"]

    except Exception as e:
        logger.error(f"Error locking appointment: {e}", exc_info=True)
        return None


def send_otp_email(booked_ts):
    global current_token, drvr_id

    try:
        otp_data = {
            "bookedTs": booked_ts,
            "drvrID": drvr_id,
            "method": "E"
        }

        logger.info("Requesting OTP code to be sent via email...")
        logger.debug(f"POST {CONFIG['send_otp_url']} payload={otp_data}")
        timeout = httpx.Timeout(15.0, read=None)
        with httpx.Client() as client:
            t0 = time.monotonic()
            response = client.post(
                CONFIG["send_otp_url"],
                json=otp_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": current_token,
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0"
                },
                timeout=timeout
            )
            logger.debug(f"Send OTP response: status={response.status_code} elapsed={time.monotonic() - t0:.2f}s body={response.text[:500]}")

            response.raise_for_status()

            result = response.json()
            if result.get("code") == "success":
                logger.info("OTP code sent to email")
                return True
            else:
                logger.error(f"Failed to send OTP code. response={result}")
                return False

    except Exception as e:
        logger.error(f"Error sending OTP code: {e}", exc_info=True)
        return False


def get_otp_from_email():
    mail = None
    try:
        logger.debug(f"Connecting to IMAP server {CONFIG['gmail']['imap_server']}...")
        mail = imaplib.IMAP4_SSL(CONFIG["gmail"]["imap_server"])
        mail.login(CONFIG["gmail"]["email"], CONFIG["gmail"]["password"])
        mail.select("inbox")

        status, messages = mail.search(None, '(FROM "roadtests-donotreply@icbc.com")')
        if status != "OK":
            logger.warning("IMAP search failed to find emails from ICBC")
            return None

        message_ids = messages[0].split()
        logger.debug(f"IMAP search found {len(message_ids)} email(s) from ICBC")
        if not message_ids:
            logger.debug("No new emails from ICBC yet")
            return None

        latest_email_id = message_ids[-1]
        status, msg_data = mail.fetch(latest_email_id, "(RFC822)")
        if status != "OK":
            logger.warning("Failed to fetch latest ICBC email")
            return None

        raw_email = msg_data[0][1]
        email_message = email.message_from_bytes(raw_email)

        for part in email_message.walk():
            if part.get_content_type() == "text/html":
                html_content = part.get_payload(decode=True).decode()
                match = re.search(r'<h2[^>]*>(\d{6})</h2>', html_content)
                if match:
                    logger.info("OTP code found in email")
                    return match.group(1)

        logger.warning("Latest ICBC email did not contain a recognizable OTP code")
        return None

    except Exception as e:
        logger.error(f"Error getting OTP code from email: {e}", exc_info=True)
        return None
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


def verify_otp(booked_ts, otp_code):
    global current_token, drvr_id

    try:
        verify_data = {
            "bookedTs": booked_ts,
            "drvrID": drvr_id,
            "code": otp_code
        }

        logger.info("Verifying OTP code...")
        logger.debug(f"PUT {CONFIG['verify_otp_url']} payload={{'bookedTs': '{booked_ts}', 'drvrID': {drvr_id}, 'code': '***'}}")
        with httpx.Client() as client:
            t0 = time.monotonic()
            response = client.put(
                CONFIG["verify_otp_url"],
                json=verify_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": current_token,
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0"
                }
            )
            logger.debug(f"Verify OTP response: status={response.status_code} elapsed={time.monotonic() - t0:.2f}s body={response.text[:500]}")

            response.raise_for_status()

            result = response.json()
            if result.get("status") == "VERIFIED":
                logger.info("OTP code successfully verified")
                return True
            else:
                logger.error(f"Invalid OTP code. response={result}")
                return False

    except Exception as e:
        logger.error(f"Error verifying OTP code: {e}", exc_info=True)
        return False


def book_appointment(booked_ts):
    global current_token, drvr_id

    try:
        book_data = {
            "userId": f"WEBD:{drvr_id}",
            "appointment": {
                "drvrDriver": {"drvrId": drvr_id}
            }
        }

        logger.info("Finalizing booking...")
        logger.debug(f"PUT {CONFIG['book_url']} payload={book_data}")
        with httpx.Client() as client:
            t0 = time.monotonic()
            response = client.put(
                CONFIG["book_url"],
                json=book_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": current_token,
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0"
                }
            )
            logger.debug(f"Book response: status={response.status_code} elapsed={time.monotonic() - t0:.2f}s body={response.text[:500]}")

            response.raise_for_status()

            result = response.json()
            if result.get("code") == "success":
                logger.info("Booking completed successfully!")
                return True
            else:
                logger.error(f"Failed to complete booking. response={result}")
                return False

    except Exception as e:
        logger.error(f"Error completing booking: {e}", exc_info=True)
        return False


def send_booking_notification(appointment):
    recipients = CONFIG["notify_emails"]
    if not recipients:
        logger.debug("NOTIFY_EMAILS not set, skipping booking notification email")
        return

    try:
        appt_date = appointment["appointmentDt"]["date"]
        start_tm = appointment.get("startTm", "")
        location_id = appointment.get("posId", "")

        body = (
            f"Your ICBC road test has been successfully booked!\n\n"
            f"Date: {appt_date}\n"
            f"Time: {start_tm}\n"
            f"Location ID: {location_id}\n"
        )

        msg = MIMEText(body)
        msg["Subject"] = f"ICBC Road Test Booked - {appt_date}"
        msg["From"] = CONFIG["gmail"]["email"]
        msg["To"] = ", ".join(recipients)

        logger.info(f"Sending booking notification email to: {', '.join(recipients)}")
        with smtplib.SMTP_SSL(CONFIG["gmail"]["smtp_server"], CONFIG["gmail"]["smtp_port"]) as smtp:
            smtp.login(CONFIG["gmail"]["email"], CONFIG["gmail"]["password"])
            smtp.sendmail(CONFIG["gmail"]["email"], recipients, msg.as_string())

        logger.info("Booking notification email sent successfully")

    except Exception as e:
        logger.error(f"Failed to send booking notification email: {e}", exc_info=True)


def auto_book_earliest_appointment():
    appointment = get_earliest_appointment()
    if not appointment:
        logger.debug("No suitable dates available for booking")
        return False

    logger.info(f"Found early date: {appointment['appointmentDt']['date']}")

    booked_ts = lock_appointment(appointment)
    if not booked_ts:
        return False

    if not send_otp_email(booked_ts):
        return False

    otp_code = None
    for attempt in range(1, 21):
        logger.debug(f"Waiting for OTP email, attempt {attempt}/20...")
        time.sleep(10)
        otp_code = get_otp_from_email()
        if otp_code:
            break

    if not otp_code:
        logger.error("Failed to get OTP code from email after 20 attempts")
        return False

    if not verify_otp(booked_ts, otp_code):
        return False

    if not book_appointment(booked_ts):
        return False

    send_booking_notification(appointment)

    return True


def main():
    logger.info(f"Logging to file: {LOG_FILE}")

    if not validate_config():
        return

    if not refresh_token():
        logger.error("Failed to get token. Check your credentials.")
        return

    last_check_time = time.time()
    last_token_time = time.time()
    check_count = 0

    logger.info("Script started. Beginning monitoring for available dates...")

    try:
        while True:
            current_time = time.time()

            if current_time - last_token_time >= CONFIG["token_refresh_interval"]:
                logger.debug("Token refresh interval reached, refreshing...")
                refresh_token()
                last_token_time = current_time

            if current_time - last_check_time >= CONFIG["check_interval"]:
                check_count += 1
                logger.debug(f"--- Check #{check_count} ---")
                if auto_book_earliest_appointment():
                    logger.info("Booking completed successfully! Script terminating.")
                    break
                last_check_time = current_time

            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Script stopped by user")


if __name__ == "__main__":
    main()