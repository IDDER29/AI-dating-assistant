from dataclasses import dataclass, field
import datetime
from typing import Any, Dict, Optional, Set


@dataclass
class BotState:
    last_seen_anket_text: Optional[str] = None
    last_action_time: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.min.replace(
            tzinfo=datetime.timezone.utc
        )
    )
    start_time: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    conversation_histories: Dict[str, list] = field(default_factory=dict)
    active_dialogue_tasks: Dict[int, Any] = field(default_factory=dict)
    leomatch_task: Optional[Any] = None
    whitelist_ids: Set[int] = field(default_factory=set)
    model: Optional[Any] = None
    app: Optional[Any] = None
