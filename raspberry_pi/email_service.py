"""
=============================================================================
Email Service - Project Spotless
=============================================================================
Handles email notifications for bath sessions.

Features:
- Session start/completion notifications
- Log file attachment
- Session number tracking
- Multiple email templates for different session types

Configuration:
- Email credentials are stored in config (or environment variables)
- Recipients can be configured per machine
=============================================================================
"""

import os
import ssl
import smtplib
import logging
import socket
from pathlib import Path
from datetime import datetime
from email.message import EmailMessage
from typing import Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================
# Email settings directory (same as config)
EMAIL_DIR = Path.home() / ".spotless"
SESSION_NUMBER_FILE = EMAIL_DIR / "session_number.txt"
DIY_SESSION_NUMBER_FILE = EMAIL_DIR / "diy_session_number.txt"


@dataclass
class EmailConfig:
    """Email configuration settings."""
    sender: str = "spotlessbs02@gmail.com"
    password: str = "namk caiq lmpi yeoe"  # App password
    receiver: str = "management@petgully.com"
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 465
    enabled: bool = True
    
    # Optional: Additional recipients
    cc_recipients: List[str] = None
    
    def __post_init__(self):
        if self.cc_recipients is None:
            self.cc_recipients = []


# Default email config
DEFAULT_EMAIL_CONFIG = EmailConfig()


# =============================================================================
# Internet Connectivity Check
# =============================================================================
def check_internet(host: str = "8.8.8.8", port: int = 53, timeout: int = 3) -> bool:
    """
    Check if internet connection is available.
    
    Args:
        host: Host to check (default: Google DNS)
        port: Port to check (default: DNS port)
        timeout: Connection timeout in seconds
        
    Returns:
        True if internet is available, False otherwise
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error as e:
        logger.warning(f"No internet connection: {e}")
        return False


# =============================================================================
# Session Number Management
# =============================================================================
def get_next_session_number() -> int:
    """Get and increment the session number."""
    try:
        EMAIL_DIR.mkdir(parents=True, exist_ok=True)
        
        if SESSION_NUMBER_FILE.exists():
            session_number = int(SESSION_NUMBER_FILE.read_text().strip()) + 1
        else:
            session_number = 1001
            
        SESSION_NUMBER_FILE.write_text(str(session_number))
        return session_number
        
    except Exception as e:
        logger.error(f"Error managing session number: {e}")
        return 1001


def get_next_diy_session_number() -> int:
    """Get and increment the DIY session number."""
    try:
        EMAIL_DIR.mkdir(parents=True, exist_ok=True)
        
        if DIY_SESSION_NUMBER_FILE.exists():
            diy_session_number = int(DIY_SESSION_NUMBER_FILE.read_text().strip()) + 1
        else:
            diy_session_number = 1
            
        DIY_SESSION_NUMBER_FILE.write_text(str(diy_session_number))
        return diy_session_number
        
    except Exception as e:
        logger.error(f"Error managing DIY session number: {e}")
        return 1


# =============================================================================
# Email Templates
# =============================================================================
def get_email_template(session_type: str, qr_code: str = "", machine_id: str = "",
                        duration_seconds: int = 0) -> Tuple[str, str]:
    """
    Get email subject and body for a session type.
    
    Args:
        session_type: Type of session (small, large, custdiy, etc.)
        qr_code: QR code/session identifier
        machine_id: Machine/booth identifier
        duration_seconds: Session duration in seconds
        
    Returns:
        Tuple of (subject, body)
    """
    current_time = datetime.now()
    timestamp = current_time.strftime("%Y%m%d%H%M%S")
    readable_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
    
    # Convert duration to readable format
    if duration_seconds > 0:
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        duration_str = f"{minutes}m {seconds}s"
    else:
        duration_str = "N/A"
    
    # Get session number
    if session_type == "custdiy":
        session_number = get_next_diy_session_number()
        prefix = "DIY"
    else:
        session_number = get_next_session_number()
        prefix = machine_id if machine_id else "Spotless"
    
    # Generate subject and body based on session type
    templates = {
        "small": {
            "subject": f"{prefix}_Bath-SmallPet_{session_number:04d}_{timestamp}",
            "body": f"""
Bath Session Completed
======================

Session Type: Small Pet Bath
Machine ID: {machine_id}
QR Code: {qr_code}
Session Number: {session_number}
Timestamp: {readable_time}
Duration: {duration_str}

Status: COMPLETED

---
Project Spotless - Automated Notification
"""
        },
        "large": {
            "subject": f"{prefix}_Bath-LargePet_{session_number:04d}_{timestamp}",
            "body": f"""
Bath Session Completed
======================

Session Type: Large Pet Bath
Machine ID: {machine_id}
QR Code: {qr_code}
Session Number: {session_number}
Timestamp: {readable_time}
Duration: {duration_str}

Status: COMPLETED

---
Project Spotless - Automated Notification
"""
        },
        "custdiy": {
            "subject": f"DIY_Bath-Customer_{session_number:04d}_{timestamp}_{qr_code}",
            "body": f"""
DIY Bath Session Completed
==========================

Session Type: Customer DIY Bath
Machine ID: {machine_id}
QR Code: {qr_code}
DIY Session Number: {session_number}
Timestamp: {readable_time}
Duration: {duration_str}

Status: COMPLETED

---
Project Spotless - Automated Notification
"""
        },
        "medsmall": {
            "subject": f"{prefix}_MedBath-SmallPet_{session_number:04d}_{timestamp}",
            "body": f"""
Medicated Bath Session Completed
================================

Session Type: Medicated Bath - Small Pet
Machine ID: {machine_id}
QR Code: {qr_code}
Session Number: {session_number}
Timestamp: {readable_time}
Duration: {duration_str}

Status: COMPLETED

---
Project Spotless - Automated Notification
"""
        },
        "medlarge": {
            "subject": f"{prefix}_MedBath-LargePet_{session_number:04d}_{timestamp}",
            "body": f"""
Medicated Bath Session Completed
================================

Session Type: Medicated Bath - Large Pet
Machine ID: {machine_id}
QR Code: {qr_code}
Session Number: {session_number}
Timestamp: {readable_time}
Duration: {duration_str}

Status: COMPLETED

---
Project Spotless - Automated Notification
"""
        },
        "onlydisinfectant": {
            "subject": f"{prefix}_Disinfectant_{session_number:04d}_{timestamp}",
            "body": f"""
Disinfectant Session Completed
==============================

Session Type: Disinfectant Only
Machine ID: {machine_id}
QR Code: {qr_code}
Session Number: {session_number}
Timestamp: {readable_time}
Duration: {duration_str}

Status: COMPLETED

---
Project Spotless - Automated Notification
"""
        },
        "quicktest": {
            "subject": f"{prefix}_RelayTest_{timestamp}",
            "body": f"""
Relay Test Completed
====================

Session Type: Quick Relay Test
Machine ID: {machine_id}
Timestamp: {readable_time}

Status: TEST COMPLETED

---
Project Spotless - Automated Notification
"""
        },
    }
    
    # Default template for unknown session types
    default_template = {
        "subject": f"{prefix}_Session_{session_number:04d}_{timestamp}",
        "body": f"""
Session Completed
=================

Session Type: {session_type}
Machine ID: {machine_id}
QR Code: {qr_code}
Session Number: {session_number}
Timestamp: {readable_time}
Duration: {duration_str}

Status: COMPLETED

---
Project Spotless - Automated Notification
"""
    }
    
    template = templates.get(session_type, default_template)
    return template["subject"], template["body"]


# =============================================================================
# Email Service Class
# =============================================================================
class EmailService:
    """
    Email notification service for Spotless.
    
    Usage:
        email_service = EmailService()
        
        # Send session notification
        email_service.send_session_email(
            session_type="small",
            qr_code="QR123",
            machine_id="BS01",
            duration_seconds=1200
        )
        
        # Send with log file attached
        email_service.send_session_email(
            session_type="large",
            qr_code="QR456",
            log_file_path="/path/to/spotless.log"
        )
    """
    
    def __init__(self, config: Optional[EmailConfig] = None):
        """
        Initialize email service.
        
        Args:
            config: Email configuration (uses default if not provided)
        """
        self.config = config or DEFAULT_EMAIL_CONFIG
        self._enabled = self.config.enabled
        
    @property
    def enabled(self) -> bool:
        """Check if email service is enabled."""
        return self._enabled
        
    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable email service."""
        self._enabled = value
        logger.info(f"Email service {'enabled' if value else 'disabled'}")
        
    def send_session_email(
        self,
        session_type: str,
        qr_code: str = "",
        machine_id: str = "",
        duration_seconds: int = 0,
        log_file_path: Optional[str] = None,
        additional_info: str = ""
    ) -> bool:
        """
        Send a session notification email.
        
        Args:
            session_type: Type of session (small, large, etc.)
            qr_code: QR code/session identifier
            machine_id: Machine/booth identifier
            duration_seconds: Session duration in seconds
            log_file_path: Optional path to log file to attach
            additional_info: Additional information to include in body
            
        Returns:
            True if email sent successfully, False otherwise
        """
        if not self._enabled:
            logger.info("Email service disabled, skipping notification")
            return False
            
        # Check internet connectivity
        if not check_internet():
            logger.warning("No internet connection, email not sent")
            return False
            
        try:
            # Get email template
            subject, body = get_email_template(
                session_type=session_type,
                qr_code=qr_code,
                machine_id=machine_id,
                duration_seconds=duration_seconds
            )
            
            # Add additional info if provided
            if additional_info:
                body += f"\n\nAdditional Information:\n{additional_info}"
            
            # Create email message
            em = EmailMessage()
            em['From'] = self.config.sender
            em['To'] = self.config.receiver
            em['Subject'] = subject
            em.set_content(body)
            
            # Add CC recipients if any
            if self.config.cc_recipients:
                em['Cc'] = ', '.join(self.config.cc_recipients)
            
            # Attach log file if provided
            if log_file_path and os.path.exists(log_file_path):
                try:
                    with open(log_file_path, 'rb') as file:
                        em.add_attachment(
                            file.read(),
                            maintype='text',
                            subtype='plain',
                            filename=os.path.basename(log_file_path)
                        )
                    logger.info(f"Attached log file: {log_file_path}")
                except Exception as e:
                    logger.warning(f"Failed to attach log file: {e}")
            
            # Send email - create SSL context that works on Windows
            context = ssl.create_default_context()
            # Workaround for Windows SSL certificate issues
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            with smtplib.SMTP_SSL(
                self.config.smtp_server, 
                self.config.smtp_port, 
                context=context
            ) as smtp:
                smtp.login(self.config.sender, self.config.password)
                
                # Build recipient list
                recipients = [self.config.receiver] + self.config.cc_recipients
                smtp.sendmail(self.config.sender, recipients, em.as_string())
            
            logger.info(f"Email sent successfully: {subject}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Email authentication failed: {e}")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
            
    def send_session_start_email(
        self,
        session_type: str,
        qr_code: str = "",
        machine_id: str = "",
        customer_name: str = "",
        pet_name: str = "",
    ) -> bool:
        """
        Send a notification when a session STARTS (QR scanned, validated, running).
        """
        if not self._enabled:
            return False

        current_time = datetime.now()
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")

        subject = (
            f"Spotless_{machine_id}_SessionStarted_"
            f"{current_time.strftime('%Y%m%d%H%M%S')}"
        )
        body = f"""
Session Started
===============

Machine ID:    {machine_id}
Session Type:  {session_type}
QR Code:       {qr_code}
Customer:      {customer_name or 'N/A'}
Pet:           {pet_name or 'N/A'}
Started At:    {timestamp}

Status: IN PROGRESS

---
Project Spotless - Automated Notification
"""
        return self._send_raw_email(subject, body)

    def send_startup_notification(self, machine_id: str) -> bool:
        """Send a system startup notification."""
        if not self._enabled:
            return False
            
        current_time = datetime.now()
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
        
        subject = f"Spotless_{machine_id}_Startup_{current_time.strftime('%Y%m%d%H%M%S')}"
        body = f"""
System Startup Notification
===========================

Machine ID: {machine_id}
Startup Time: {timestamp}
Status: ONLINE

---
Project Spotless - Automated Notification
"""
        
        return self._send_raw_email(subject, body)
        
    def send_error_notification(self, machine_id: str, error_message: str) -> bool:
        """Send an error notification."""
        if not self._enabled:
            return False
            
        current_time = datetime.now()
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
        
        subject = f"ALERT_Spotless_{machine_id}_Error_{current_time.strftime('%Y%m%d%H%M%S')}"
        body = f"""
ERROR NOTIFICATION
==================

Machine ID: {machine_id}
Time: {timestamp}
Status: ERROR

Error Details:
{error_message}

---
Project Spotless - Automated Notification
"""
        
        return self._send_raw_email(subject, body)
        
    def send_shutdown_notification(self, machine_id: str) -> bool:
        """Send a system shutdown notification."""
        if not self._enabled:
            return False
            
        current_time = datetime.now()
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
        
        subject = f"Spotless_{machine_id}_Shutdown_{current_time.strftime('%Y%m%d%H%M%S')}"
        body = f"""
System Shutdown Notification
============================

Machine ID: {machine_id}
Shutdown Time: {timestamp}
Status: OFFLINE

---
Project Spotless - Automated Notification
"""
        
        return self._send_raw_email(subject, body)
        
    def _send_raw_email(self, subject: str, body: str, 
                        attachment_path: Optional[str] = None) -> bool:
        """Send a raw email with given subject and body."""
        if not check_internet():
            logger.warning("No internet connection, email not sent")
            return False
            
        try:
            em = EmailMessage()
            em['From'] = self.config.sender
            em['To'] = self.config.receiver
            em['Subject'] = subject
            em.set_content(body)
            
            if attachment_path and os.path.exists(attachment_path):
                with open(attachment_path, 'rb') as file:
                    em.add_attachment(
                        file.read(),
                        maintype='text',
                        subtype='plain',
                        filename=os.path.basename(attachment_path)
                    )
            
            context = ssl.create_default_context()
            # Workaround for Windows SSL certificate issues
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            with smtplib.SMTP_SSL(
                self.config.smtp_server, 
                self.config.smtp_port, 
                context=context
            ) as smtp:
                smtp.login(self.config.sender, self.config.password)
                smtp.sendmail(self.config.sender, self.config.receiver, em.as_string())
            
            logger.info(f"Email sent: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False


# =============================================================================
# Global Instance
# =============================================================================
_email_service: Optional[EmailService] = None

def get_email_service() -> EmailService:
    """Get or create the global EmailService instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service


# =============================================================================
# Convenience Functions
# =============================================================================
def send_session_email(session_type: str, qr_code: str = "", machine_id: str = "",
                       duration_seconds: int = 0, log_file_path: Optional[str] = None) -> bool:
    """Send a session notification email."""
    return get_email_service().send_session_email(
        session_type=session_type,
        qr_code=qr_code,
        machine_id=machine_id,
        duration_seconds=duration_seconds,
        log_file_path=log_file_path
    )


# =============================================================================
# Test
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Email Service...")
    
    # Test internet connectivity
    print(f"Internet available: {check_internet()}")
    
    # Test session number
    print(f"Next session number: {get_next_session_number()}")
    
    # Test email template
    subject, body = get_email_template(
        session_type="small",
        qr_code="TEST123",
        machine_id="BS01",
        duration_seconds=1200
    )
    print(f"\nSubject: {subject}")
    print(f"Body:\n{body}")
    
    # Uncomment to actually send a test email
    # service = EmailService()
    # service.send_session_email("quicktest", machine_id="BS01")
