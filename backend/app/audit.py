import json
import logging
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class AuditEvent:
    request_id: str
    user_id: str | None
    action: str
    role: str | None
    outcome: str
    duration_ms: float
    row_count: int
    error_code: str | None = None


class AuditLogger:
    def __init__(self) -> None:
        self.logger = logging.getLogger("pharma.audit")

    def record(self, event: AuditEvent) -> None:
        self.logger.info(json.dumps(asdict(event), sort_keys=True))
