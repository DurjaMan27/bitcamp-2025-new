import os.path
import base64
import os
import google.generativeai as genai
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging  

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
TOKEN_PATH = "token.json"
CREDENTIALS_PATH = "credentials.json"

class GmailAgent:
    """
    A class to interact with the Gmail API and Gemini for email operations like
    listing, searching, summarizing, generating replies, and sending emails.
    """
    def __init__(self, scopes=SCOPES, token_path=TOKEN_PATH, credentials_path=CREDENTIALS_PATH):
        self.scopes = scopes
        self.token_path = token_path
        self.credentials_path = credentials_path
        self.service = self._authenticate()
        self.gemini_model = self._configure_gemini()
        if self.service:
            logging.info("Gmail service initialized successfully.")
        else:
            logging.error("Gmail service initialization failed.")
        if self.gemini_model:
            logging.info("Gemini model initialized successfully.")
        else:
            logging.error("Gemini model initialization failed.")

    def _configure_gemini(self):
        try:
            gemini_api_key = os.environ.get("GOOGLE_API_KEY")
            if not gemini_api_key:
                raise ValueError("GOOGLE_API_KEY not found in environment variables.")
            genai.configure(api_key=gemini_api_key)
            return genai.GenerativeModel('gemini-2.0-flash-lite-001')
        except ValueError as e:
            logging.error(f"Error configuring Gemini: {e}")
            return None
        except Exception as e:
            logging.error(f"An unexpected error occurred during Gemini configuration: {e}")
            return None

    def _authenticate(self):
        creds = None
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, self.scopes)
            except Exception as e:
                logging.warning(f"Failed to load token file: {e}. Re-authenticating.")
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    logging.info("Refreshing access token.")
                    creds.refresh(Request())
                except Exception as e:
                    logging.error(f"Error refreshing token: {e}. Re-authenticating.")
                    try:
                        os.remove(self.token_path)
                        logging.info(f"Removed potentially invalid token file: {self.token_path}")
                    except OSError as rm_error:
                        logging.error(f"Error removing token file {self.token_path}: {rm_error}")
                    creds = None
            if not creds:
                if not os.path.exists(self.credentials_path):
                    logging.error(f"Credentials file not found at: {self.credentials_path}")
                    return None
                logging.info("Performing new user authentication.")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, self.scopes
                )
                creds = flow.run_local_server(port=0)

            try:
                with open(self.token_path, "w") as token:
                    token.write(creds.to_json())
                logging.info(f"Credentials saved to {self.token_path}")
            except Exception as e:
                logging.error(f"Failed to save token: {e}")

        try:
            service = build("gmail", "v1", credentials=creds)
            logging.info("Gmail service built successfully.")
            return service
        except Exception as e:
            logging.error(f"Failed to build Gmail service: {e}")
            return None

    def _get_email_body(self, payload):
        body = ""
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data")
                    if data:
                        return base64.urlsafe_b64decode(data).decode("utf-8", errors='replace')

            for part in payload["parts"]:
                if "parts" in part:
                    nested_body = self._get_email_body(part)
                    if nested_body:
                        return nested_body
                elif part.get("mimeType") == "text/html":
                    data = part.get("body", {}).get("data")
                    if data:
                        if not body:
                            body = base64.urlsafe_b64decode(data).decode("utf-8", errors='replace')

        elif payload.get("mimeType", "").startswith("text/"):
            data = payload.get("body", {}).get("data")
            if data:
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors='replace')

        return body

    def list_recent_emails(self, max_results: int) -> dict:
        """
        Lists the most recent emails from the user's INBOX.

        Fetches metadata (id, threadId, subject, from, date) for a specified
        number of the latest emails.

        Args:
            max_results (int, optional): The maximum number of emails to retrieve.
                Defaults to 10.

        Returns:
            dict: A dictionary containing:
                - 'status' (str): 'success' or 'error'.
                - 'emails' (list[dict]): A list of email details (id, threadId,
                  subject, from, date) if successful and emails are found.
                  An empty list if no emails are found.
                - 'error_message' (str): Description of the error if status is 'error'.
        """
        if not self.service:
            return {"status": "error", "error_message": "Gmail service not available."}

        try:
            results = self.service.users().messages().list(
                userId="me", labelIds=['INBOX'], maxResults=max_results
            ).execute()
            messages = results.get('messages', [])

            if not messages:
                logging.info("No recent emails found in INBOX.")
                return {"status": "success", "emails": []}

            email_list = []
            for msg_stub in messages:
                msg_id = msg_stub['id']
                try:
                    msg = self.service.users().messages().get(
                        userId="me", id=msg_id, format='metadata',
                        metadataHeaders=['Subject', 'From', 'Date']
                    ).execute()

                    payload = msg.get('payload', {})
                    headers = payload.get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
                    sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
                    date = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'No Date')

                    email_list.append({
                        'id': msg_id,
                        'threadId': msg.get('threadId'),
                        'subject': subject,
                        'from': sender,
                        'date': date
                    })
                except HttpError as error:
                    logging.warning(f"Could not fetch metadata for message {msg_id}: {error}")
                except Exception as e:
                    logging.warning(f"Unexpected error fetching metadata for message {msg_id}: {e}")

            return {"status": "success", "emails": email_list}

        except HttpError as error:
            logging.error(f"An API error occurred listing emails: {error}")
            return {"status": "error", "error_message": f"An API error occurred listing emails: {error}"}
        except Exception as e:
            logging.error(f"An unexpected error occurred listing emails: {e}")
            return {"status": "error", "error_message": f"An unexpected error occurred listing emails: {e}"}

    def summarize_email_with_gemini(self, email_id: str) -> dict:
        """
        Fetches a specific email by its ID and summarizes its content using Gemini.

        Retrieves the full email content, extracts key headers (subject, sender,
        message-id, references) and the body. Sends the subject and body to the
        Gemini model for summarization.

        Args:
            email_id (str): The unique ID of the email message to summarize.

        Returns:
            dict: A dictionary containing:
                - 'status' (str): 'success' or 'error'.
                - 'summary' (str): The generated summary text from Gemini. Can indicate
                  if the body couldn't be extracted.
                - 'subject' (str): The original email subject.
                - 'original_body' (str): The extracted original email body.
                - 'sender_email' (str): The extracted sender's email address.
                - 'thread_id' (str): The thread ID the email belongs to.
                - 'original_message_id' (str): The Message-ID header of the email.
                - 'references' (str): The References header of the email.
                - 'error_message' (str): Description of the error if status is 'error'.
        """
        if not self.service:
            return {"status": "error", "error_message": "Gmail service not available."}
        if not self.gemini_model:
            return {"status": "error", "error_message": "Gemini model not initialized."}

        try:
            message = self.service.users().messages().get(userId="me", id=email_id, format='full').execute()
            payload = message.get('payload', {})
            thread_id = message.get('threadId')

            headers = payload.get('headers', [])
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            original_message_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), '')
            references = next((h['value'] for h in headers if h['name'].lower() == 'references'), '')

            sender_email = sender_header
            if '<' in sender_header and '>' in sender_header:
                start = sender_header.find('<') + 1
                end = sender_header.find('>')
                if start < end:
                    sender_email = sender_header[start:end]

            email_body = self._get_email_body(payload)

            if not email_body:
                logging.warning(f"Could not extract body for email {email_id}.")
                summary_text = "Could not extract email body to summarize."
            else:
                prompt = f"Summarize the following email concisely:\n\nSubject: {subject}\n\nBody:\n{email_body[:3000]}\n\nSummary:"
                try:
                    response = self.gemini_model.generate_content(prompt)
                    summary_text = response.text
                except Exception as gen_e:
                    logging.error(f"Gemini content generation failed for email {email_id}: {gen_e}")
                    return {"status": "error", "error_message": f"Gemini content generation failed: {gen_e}"}

            return {
                "status": "success",
                "summary": summary_text,
                "subject": subject,
                "original_body": email_body,
                "sender_email": sender_email,
                "thread_id": thread_id,
                "original_message_id": original_message_id,
                "references": references
            }

        except HttpError as error:
            logging.error(f"An API error occurred fetching email {email_id}: {error}")
            return {"status": "error", "error_message": f"An API error occurred fetching email {email_id}: {error}"}
        except Exception as e:
            logging.error(f"An unexpected error occurred during summarization for email {email_id}: {e}")
            return {"status": "error", "error_message": f"An unexpected error occurred during summarization: {e}"}

    def generate_reply_with_gemini(self, original_subject: str, original_body: str) -> dict:
        """
        Generates a draft reply email body using the Gemini model based on the original email.

        Constructs a prompt with the original subject and body (truncated) and asks
        Gemini to generate a professional, concise reply draft, omitting salutations
        and closings.

        Args:
            original_subject (str): The subject line of the email being replied to.
            original_body (str): The body content of the email being replied to.
                                 Generation is attempted even if empty, with a warning.

        Returns:
            dict: A dictionary containing:
                - 'status' (str): 'success' or 'error'.
                - 'reply_body' (str): The generated reply body text if successful.
                - 'error_message' (str): Description of the error if status is 'error'.
        """
        if not self.gemini_model:
            return {"status": "error", "error_message": "Gemini model not initialized."}
        if not original_body:
            logging.warning("Attempting to generate reply without original email body.")

        try:
            prompt = f"""Generate a professional and concise reply draft for the following email.
Focus on addressing the main points or questions. Omit salutations (like "Hi Name,") and closings (like "Best,").

Original Email Subject: {original_subject}
Original Email Body (first 2000 chars):
---
{original_body[:2000]}
---

Generated Reply Draft (body only):"""

            response = self.gemini_model.generate_content(prompt)
            reply_body = response.text.strip()
            return {"status": "success", "reply_body": reply_body}

        except Exception as e:
            logging.error(f"An error occurred during reply generation: {e}")
            return {"status": "error", "error_message": f"An error occurred during reply generation: {e}"}

    def _create_reply_message(self, sender: str, to: str, subject: str, reply_body: str, thread_id: str, original_message_id: str, references: str) -> dict:
        """
        Creates a MIME message object suitable for replying within an email thread.

        Constructs a `MIMEMultipart` message, setting the 'To', 'From', and 'Subject'
        headers. Crucially, it sets the 'In-Reply-To' and 'References' headers
        using the provided IDs and references to ensure correct threading in email clients.
        Attaches the reply body as plain text. Encodes the message in base64 URL-safe
        format as required by the Gmail API.

        Internal helper method for `send_reply`.

        Args:
            sender (str): The sender's email address (authenticated user).
            to (str): The recipient's email address.
            subject (str): The subject line for the reply email (should include "Re:").
            reply_body (str): The plain text content of the reply.
            thread_id (str): The ID of the Gmail thread this reply belongs to.
            original_message_id (str): The Message-ID of the email being replied to.
            references (str): The References header value from the email being replied to.

        Returns:
            dict: A dictionary containing the raw, base64-encoded message string
                  under the key 'raw' and the 'threadId'. Suitable for the
                  `users().messages().send()` API call body.
        """
        message = MIMEMultipart('related')
        message['to'] = to
        message['from'] = sender
        message['subject'] = subject

        if original_message_id:
            message['In-Reply-To'] = original_message_id
        new_references = f"{references} {original_message_id}".strip() if references else original_message_id
        if new_references:
            message['References'] = new_references

        msg_text = MIMEText(reply_body, 'plain', 'utf-8')
        message.attach(msg_text)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        return {'raw': raw_message, 'threadId': thread_id}

    def send_reply(self, to: str, subject: str, reply_body: str, thread_id: str, original_message_id: str, references: str) -> dict:
        """
        Creates and sends a reply email within a specific Gmail thread.

        Retrieves the authenticated user's email address. Ensures the subject line
        starts with "Re: ". Uses `_create_reply_message` to construct the MIME message
        with correct threading headers. Sends the message using the Gmail API.

        Args:
            to (str): The recipient's email address.
            subject (str): The subject line for the reply. "Re: " will be added if missing.
            reply_body (str): The plain text content of the reply.
            thread_id (str): The ID of the thread to reply within.
            original_message_id (str): The Message-ID header of the message being replied to.
                                     Used for the 'In-Reply-To' header.
            references (str): The References header content from the original email.
                              Used for constructing the new 'References' header.

        Returns:
            dict: A dictionary containing:
                - 'status' (str): 'success' or 'error'.
                - 'message_id' (str): The ID of the sent message if successful.
                - 'error_message' (str): Description of the error if status is 'error'.
        """
        if not self.service:
            return {"status": "error", "error_message": "Gmail service not available."}
        try:
            profile = self.service.users().getProfile(userId='me').execute()
            actual_sender = profile.get('emailAddress')
            if not actual_sender:
                return {"status": "error", "error_message": "Could not determine sender email address from profile."}

            reply_subject = subject
            if not subject.lower().startswith("re:"):
                reply_subject = f"Re: {subject}"

            reply_message_dict = self._create_reply_message(
                sender=actual_sender,
                to=to,
                subject=reply_subject,
                reply_body=reply_body,
                thread_id=thread_id,
                original_message_id=original_message_id,
                references=references
            )
            message = self.service.users().messages().send(userId="me", body=reply_message_dict).execute()
            logging.info(f"Reply sent successfully. Message ID: {message['id']}")
            return {"status": "success", "message_id": message['id']}

        except HttpError as error:
            logging.error(f"An API error occurred sending the reply: {error}")
            return {"status": "error", "error_message": f"An API error occurred sending the reply: {error}"}
        except Exception as e:
            logging.error(f"An unexpected error occurred sending the reply: {e}")
            return {"status": "error", "error_message": f"An unexpected error occurred sending the reply: {e}"}

    def search_emails(self, query: str, max_results: int) -> dict:
        """
        Searches for emails matching a given Gmail search query.

        Uses the standard Gmail search query format. Fetches metadata (id, threadId,
        subject, from, date) for the emails matching the query, up to a specified limit.

        Args:
            query (str): The search query string (e.g., 'from:someone@example.com subject:report').
            max_results (int, optional): The maximum number of matching emails to retrieve.
                                         Defaults to 5.

        Returns:
            dict: A dictionary containing:
                - 'status' (str): 'success' or 'error'.
                - 'emails' (list[dict]): A list of matching email details (id, threadId,
                  subject, from, date) if successful. An empty list if no matches found.
                - 'error_message' (str): Description of the error if status is 'error'.
        """
        if not self.service:
            return {"status": "error", "error_message": "Gmail service not available."}

        try:
            results = self.service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()
            messages = results.get('messages', [])

            if not messages:
                logging.info(f"No emails found matching query: '{query}'")
                return {"status": "success", "emails": []}

            email_list = []
            for msg_stub in messages:
                msg_id = msg_stub['id']
                try:
                    msg = self.service.users().messages().get(
                        userId="me", id=msg_id, format='metadata',
                        metadataHeaders=['Subject', 'From', 'Date']
                    ).execute()

                    payload = msg.get('payload', {})
                    headers = payload.get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
                    sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
                    date = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'No Date')

                    email_list.append({
                        'id': msg_id,
                        'threadId': msg.get('threadId'),
                        'subject': subject,
                        'from': sender,
                        'date': date
                    })
                except HttpError as error:
                    logging.warning(f"Could not fetch metadata for searched message {msg_id}: {error}")
                except Exception as e:
                    logging.warning(f"Unexpected error fetching metadata for searched message {msg_id}: {e}")

            return {"status": "success", "emails": email_list}

        except HttpError as error:
            logging.error(f"An API error occurred searching emails: {error}")
            return {"status": "error", "error_message": f"An API error occurred searching emails: {error}"}
        except Exception as e:
            logging.error(f"An unexpected error occurred searching emails: {e}")
            return {"status": "error", "error_message": f"An unexpected error occurred searching emails: {e}"}

gmail_agent = GmailAgent()

if gmail_agent.service and gmail_agent.gemini_model:
    agent_tools = [
        gmail_agent.list_recent_emails,
        gmail_agent.search_emails,
        gmail_agent.summarize_email_with_gemini,
        gmail_agent.generate_reply_with_gemini,
        gmail_agent.send_reply,
    ]
    logging.info("Agent Function Tools Initialized using GmailAgent instance.")
else:
    agent_tools = []
    logging.error("Agent Function Tools could not be initialized due to Gmail/Gemini setup issues.")