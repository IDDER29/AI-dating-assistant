def get_message_text(message) -> str | None:
    """Extract text from message text or caption."""
    return message.text or message.caption
