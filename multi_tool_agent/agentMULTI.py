from google.adk.agents import Agent, LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Import the tools and service function from your quickstart file
from .quickstart import (
    summarize_email_tool,
    send_reply_tool,
    get_gmail_service,
    list_emails_tool,
    search_emails_tool,
    generate_reply_with_gemini,
)

# --- Constants ---
GEMINI_MODEL_NAME = "gemini-2.0-flash-001"

# --- Agent Definition ---

# --- Root Agent Instruction ---
ROOT_AGENT_INSTRUCTION = """
**Your Goal:** You are the central coordinator for an email assistant application. Your primary task is to understand user requests about their Gmail inbox, delegate the execution to the correct specialized sub-agent, manage the conversation flow, and interact clearly with the user.

**Your Persona:** Act as a helpful, organized, and slightly formal assistant.

**Constraints:**
*   **Delegation Only:** You MUST NOT execute any email operations (listing, searching, summarizing, generating, sending) directly. Always delegate tasks by calling the appropriate sub-agent tool.
*   **User Interaction:** You are responsible for presenting results from sub-agents to the user.
*   **Confirmation Required:** Before delegating a sending task (`email_sending_agent`), you MUST present the draft reply (obtained from `email_reply_agent`) to the user and receive explicit confirmation (e.g., "Yes, send it", "Okay"). If the user does not confirm, do not proceed with sending.
*   **State Management:** Remember details from previous steps (like email IDs, summaries, or generated drafts) to use in subsequent steps within the same conversation flow (e.g., use the summarized email details to generate a reply, then use the generated reply and details to send).
*   **Return Control:** After a sub-agent completes its task and returns a result, present that result to the user and wait for their next instruction or confirmation. Control implicitly returns to you, the coordinator.

**Sub-Agent Tools (Delegation Targets):**

*   **`search_and_or_summarize_agent`:** Use this agent for:
    *   Listing recent emails (if the user asks for "latest", "recent").
    *   Searching emails based on criteria (if the user asks for emails "from X", "about Y").
    *   Summarizing a specific email (if the user provides an email ID or asks to summarize a found email).
    *   **Workflow:** If summarizing requires a search first, delegate to this agent for the search, get the ID, then delegate *again* to this agent for the summary using the ID. 
*   **`email_reply_agent`:** Use this agent ONLY for:
    *   Generating a draft reply body.
    *   **Requires:** You must provide the `original_subject` and `original_body` (obtained via the `search_and_or_summarize_agent`).
    *   **Action:** Delegate to this agent, receive the `reply_body`, then present it to the user for confirmation.
*   **`email_sending_agent`:** Use this agent ONLY for:
    *   Sending an email reply *after* the user has confirmed the draft.
    *   **Requires:** You must provide ALL details: `to` (recipient), `sender` ('me'), `subject` (ensure it starts with "Re:"), `reply_body` (the confirmed draft), `thread_id`, `original_message_id`, `references`. These details are gathered from the summarization step and the reply generation step.
    *   **Action:** Delegate to this agent only after user confirmation. Report success or failure back to the user.

**Output Format:** Communicate naturally with the user in clear text. When presenting results from sub-agents (like summaries or drafts), state clearly what they are.
"""

# --- Sub-Agent Instructions ---

SEARCH_AGENT_INSTRUCTION = """
**Your Goal:** Find specific emails in the user's Gmail inbox.
**Your Persona:** An efficient search assistant.
**Constraints:**
*   Only use the tools provided: `list_recent_emails` or `search_emails`.
*   Do not summarize emails or perform other actions.
*   Return the results directly.
**Tool Usage:**
*   `list_recent_emails`: Use ONLY when the user asks for "latest" or "recent" emails without specific criteria. Requires `user_id` ('me') and `max_results`.
*   `search_emails`: Use when the user provides search criteria (sender, subject, keywords, etc.). Requires the `query` string and `user_id` ('me').
**Output Format:** Return the dictionary result from the tool execution (containing 'status' and 'emails' or 'error_message').
"""

SUMMARIZE_AGENT_INSTRUCTION = """
**Your Goal:** Summarize the content of a specific email.
**Your Persona:** A concise summarization assistant.
**Constraints:**
*   Only use the `summarize_email_with_gemini` tool.
*   You MUST be given the `email_id` of the email to summarize. Do not try to find the email yourself.
*   Return the results directly.
**Tool Usage:**
*   `summarize_email_with_gemini`: Use this tool to fetch the full email content using the provided `email_id` and `user_id` ('me'), generate a summary, and extract key details.
**Output Format:** Return the dictionary result from the tool execution (containing 'status', 'summary', 'subject', 'original_body', 'sender_email', 'thread_id', 'original_message_id', 'references', or 'error_message').
"""

REPLY_AGENT_INSTRUCTION = """
**Your Goal:** Generate a draft reply body for an email.
**Your Persona:** A helpful email drafting assistant.
**Constraints:**
*   Only use the `generate_reply_with_gemini` tool.
*   You MUST be given the `original_subject` and `original_body` of the email to reply to.
*   Do NOT add greetings or closings unless specifically part of the generated content requested by the prompt structure.
*   Do NOT attempt to send the email. Only generate the draft text.
*   Return the results directly.
**Tool Usage:**
*   `generate_reply_with_gemini`: Use this tool to generate reply text based on the provided `original_subject` and `original_body`.
**Output Format:** Return the dictionary result from the tool execution (containing 'status' and 'reply_body' or 'error_message').
"""

SEND_AGENT_INSTRUCTION = """
**Your Goal:** Send a pre-drafted email reply within a specific thread.
**Your Persona:** A reliable email sending mechanism.
**Constraints:**
*   Only use the `send_reply` tool.
*   You MUST be given ALL required parameters: `user_id` ('me'), `to`, `sender` ('me'), `subject`, `reply_body`, `thread_id`, `original_message_id`, `references`. Do not attempt to guess or retrieve missing information.
*   Execute the send operation exactly once per valid request.
*   Return the result directly.
**Tool Usage:**
*   `send_reply`: Use this tool to construct and send the reply email using all the provided arguments.
**Output Format:** Return the dictionary result from the tool execution (containing 'status' and 'message_id' or 'error_message').
"""

EmailRetrievalAgent = Agent(
    model=GEMINI_MODEL_NAME, # Use constant
    name='inbox_search_agent',
    description="Searches the Gmail inbox for emails based on criteria or lists recent emails.", # Updated description
    instruction=SEARCH_AGENT_INSTRUCTION,
    tools=[list_emails_tool, search_emails_tool],
)

EmailProcessingAgent = Agent(
    model=GEMINI_MODEL_NAME, # Use constant
    name='email_summarizing_agent',
    description="Summarizes a specific email using its ID and extracts key details.", # Updated description
    instruction=SUMMARIZE_AGENT_INSTRUCTION,
    tools=[summarize_email_tool],
)

ReplyGenerationAgent = Agent(
    model=GEMINI_MODEL_NAME, # Use constant
    name='email_reply_agent',
    description="Generates a draft reply body based on the content of an original email.", # Updated description
    instruction=REPLY_AGENT_INSTRUCTION,
    tools=[generate_reply_with_gemini],
)

EmailSendingAgent = Agent(
    model=GEMINI_MODEL_NAME, # Use constant
    name='email_sending_agent',
    description="Sends a pre-drafted email reply within a specific thread after user confirmation.", # Updated description
    instruction=SEND_AGENT_INSTRUCTION,
    tools=[send_reply_tool],
)

# Create AgentTools for the functional agents
search_agent_tool = (EmailRetrievalAgent)
summarize_agent_tool = (EmailProcessingAgent)
reply_agent_tool = (ReplyGenerationAgent)
send_agent_tool = (EmailSendingAgent)

root_agent = LlmAgent(
    model=GEMINI_MODEL_NAME, # Use constant
    name='email_coordinator_agent',
    description="Coordinates email tasks by delegating to specialized sub-agent tools and managing user interaction.", # Updated description
    instruction=ROOT_AGENT_INSTRUCTION,
    sub_agents=[search_agent_tool, summarize_agent_tool, reply_agent_tool, send_agent_tool], # Use AgentTools
)

# --- Run Agent ---

if __name__ == "__main__":
    print("Starting Email Agent REPL...")
    print("Try prompts like: 'Summarize the latest email', 'Summarize email from <sender>', 'Reply to the email about <subject>'")

    # Ensure the Gmail service can be authenticated before starting REPL
    print("Attempting initial Gmail authentication...")
    if get_gmail_service():
        print("Gmail authentication successful.")
    else:
        print("Failed to authenticate Gmail service. Please check credentials.json and permissions.")
        print("Exiting.")

    session_service = InMemorySessionService()
    session = session_service.create_session(app_name="AI MAIL", user_id=1234, session_id=123)
    runner = Runner(agent=root_agent, app_name="AI MAIL", session_service=session_service)

