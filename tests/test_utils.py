from unittest.mock import MagicMock

from utils import get_message_text


def test_returns_text_field():
    msg = MagicMock()
    msg.text = "hello"
    msg.caption = None
    assert get_message_text(msg) == "hello"


def test_returns_caption_when_no_text():
    msg = MagicMock()
    msg.text = None
    msg.caption = "photo caption"
    assert get_message_text(msg) == "photo caption"


def test_returns_none_when_both_empty():
    msg = MagicMock()
    msg.text = None
    msg.caption = None
    assert get_message_text(msg) is None


def test_text_takes_priority():
    msg = MagicMock()
    msg.text = "text content"
    msg.caption = "caption content"
    assert get_message_text(msg) == "text content"
