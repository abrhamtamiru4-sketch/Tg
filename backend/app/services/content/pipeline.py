"""Content processing pipeline: fetch → validate → deduplicate → format → schedule."""
from __future__ import annotations
from dataclasses import dataclass, field
from app.core.logging_config import get_logger
log = get_logger(__name__)

@dataclass
class PipelineResult:
    post_id: int | None = None
    skipped: bool = False
    reason: str = ""
    stages_completed: list[str] = field(default_factory=list)

class ContentPipeline:
    """Runs imported content through the full processing pipeline."""
    stages = ["validate","extract","normalize","deduplicate","classify","translate","format","approve","schedule"]

    async def run(self, raw_content: dict, source_id: int, db) -> PipelineResult:
        result = PipelineResult()
        # Stage: validate
        if not raw_content.get("text") and not raw_content.get("title"):
            result.skipped = True
            result.reason = "empty_content"
            return result
        result.stages_completed.append("validate")
        # Stage: deduplicate
        from app.services.content.deduplication import get_dedup_engine
        text = raw_content.get("text") or raw_content.get("title", "")
        dup = await get_dedup_engine().check_text(text, db=db)
        if dup.is_duplicate:
            result.skipped = True
            result.reason = f"duplicate:{dup.method}:{dup.similarity:.2f}"
            return result
        result.stages_completed.append("deduplicate")
        return result
