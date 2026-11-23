# Copilot tool approvals

The Copilot Pipe groups MCP calls requested together into one approval dialog
listing their names and arguments. Submit approves every listed call; Decline
or Cancel rejects the entire batch. Calls requested later need a separate approval.
Unanswered dialogs expire after two minutes. Open WebUI's auto-approval settings
do not apply to these dialogs.

The custom image uses Open WebUI's prebuilt frontend. To deploy a verified build,
run `docker compose up -d --no-deps --build open-webui` and reload the browser tab.
