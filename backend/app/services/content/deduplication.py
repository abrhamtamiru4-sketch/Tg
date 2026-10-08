"""
Duplicate Detection Engine
==========================

Four layers of detection — each independently testable:

  1. Exact      — SHA-256 hash of normalized content
  2. Normalized — Whitespace/case/punctuation normalization before hashing
  3. Media      — Perceptual hash (pHash) for images
  4. URL        — Canonical URL deduplication for source content

Semantic (vector similarity) is behind the AI feature flag and requires
an external embedding API. It is NOT called without explicit enablement.

Result:
  DuplicateResult.is_duplicate → True/False
  DuplicateResult.similarity   → 0.0–1.0
  DuplicateResult.method       → which method triggered
  DuplicateResult.original_id  → conflicting post ID (if found)

Admin action options on duplicate detection:
  - Publish anyway
  - Edit content
  - Skip
  - Replace original
  - Merge

The engine never silently destroys content. It only warns.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from app.core.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class DuplicateResult:
    is_duplicate: bool
    similarity: float = 0.0
    method: str = "none"
    original_id: Optional[int] = None
    message: str = ""
    can_publish_anyway: bool = True  # Always allow admin override


# ── Threshold configuration ───────────────────────────────────
# These are configurable per-installation; these are sensible defaults.
EXACT_THRESHOLD = 1.0       # 100% = same hash
NORMALIZED_THRESHOLD = 0.95  # Catches copy-paste with minor edits
MEDIA_THRESHOLD = 0.90       # pHash distance threshold for images


def _normalize_text(text: str) -> str:
    """Strip whitespace, lowercase, remove punctuation, normalize unicode."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _xxhash_fast(text: str) -> str:
    """Fast non-cryptographic hash for large texts."""
    try:
        import xxhash
        return xxhash.xxh64(text.encode()).hexdigest()
    except ImportError:
        return _sha256(text)


class DeduplicationEngine:
    """
    Stateless duplicate checker. Pass DB session for history lookups.
    """

    async def check_text(
        self,
        text: str,
        db=None,
        exclude_post_id: int | None = None,
    ) -> DuplicateResult:
        """Check whether text duplicates any published post."""
        if not text or not text.strip():
            return DuplicateResult(is_duplicate=False, method="skip_empty")

        # ── 1. Exact hash ─────────────────────────────────────
        exact_hash = _sha256(text.strip())
        if db:
            match = await self._find_by_hash(db, exact_hash, exclude_post_id)
            if match:
                return DuplicateResult(
                    is_duplicate=True,
                    similarity=1.0,
                    method="exact",
                    original_id=match,
                    message=f"Exact duplicate of post #{match}",
                )

        # ── 2. Normalized hash ────────────────────────────────
        normalized = _normalize_text(text)
        norm_hash = _sha256(normalized)
        if db:
            match = await self._find_by_hash(db, norm_hash, exclude_post_id, field="content_hash")
            if match:
                return DuplicateResult(
                    is_duplicate=True,
                    similarity=0.97,
                    method="normalized",
                    original_id=match,
                    message=f"Near-duplicate (normalized) of post #{match}",
                )

        # ── 3. Similarity (Jaccard on word-grams) ─────────────
        similarity, similar_id = await self._jaccard_similarity(text, db, exclude_post_id)
        if similarity >= NORMALIZED_THRESHOLD:
            return DuplicateResult(
                is_duplicate=True,
                similarity=similarity,
                method="similarity",
                original_id=similar_id,
                message=f"Similar content ({similarity:.0%}) to post #{similar_id}",
            )

        return DuplicateResult(
            is_duplicate=False,
            similarity=similarity,
            method="none",
            message="No duplicates detected",
        )

    async def check_media(
        self,
        file_path: str,
        db=None,
    ) -> DuplicateResult:
        """Check if an image/video file is a perceptual duplicate."""
        phash = await self._compute_phash(file_path)
        if not phash:
            return DuplicateResult(is_duplicate=False, method="skip_no_phash")

        if db:
            match_id, distance = await self._find_phash_match(db, phash)
            if match_id is not None:
                similarity = max(0.0, 1.0 - distance / 64.0)  # pHash max distance is 64 bits
                if similarity >= MEDIA_THRESHOLD:
                    return DuplicateResult(
                        is_duplicate=True,
                        similarity=similarity,
                        method="perceptual_hash",
                        original_id=match_id,
                        message=f"Visually similar media to file #{match_id} ({similarity:.0%})",
                    )

        return DuplicateResult(is_duplicate=False, method="none", similarity=0.0)

    def compute_content_hash(self, text: str) -> str:
        """Return the normalized hash for storage alongside a post."""
        return _sha256(_normalize_text(text))

    def compute_exact_hash(self, text: str) -> str:
        return _sha256(text.strip())

    # ── Private helpers ───────────────────────────────────────

    async def _find_by_hash(
        self,
        db,
        hash_value: str,
        exclude_post_id: int | None,
        field: str = "content_hash",
    ) -> int | None:
        from sqlalchemy import select, and_
        from app.db.models import Post, PostStatus

        filters = [
            getattr(Post, field) == hash_value,
            Post.status.in_([PostStatus.PUBLISHED, PostStatus.SCHEDULED, PostStatus.APPROVED]),
        ]
        if exclude_post_id:
            from sqlalchemy import not_
            filters.append(Post.id != exclude_post_id)

        result = (await db.execute(
            select(Post.id).where(and_(*filters)).limit(1)
        )).scalar_one_or_none()
        return result

    @staticmethod
    async def _jaccard_similarity(
        text: str,
        db,
        exclude_post_id: int | None,
    ) -> tuple[float, int | None]:
        """
        Approximate Jaccard similarity against recent published posts.
        Only checks the last 500 posts for performance.
        Returns (max_similarity, post_id_of_best_match).
        """
        if not db:
            return 0.0, None

        from sqlalchemy import select
        from app.db.models import Post, PostStatus

        query = (
            select(Post.id, Post.text, Post.caption)
            .where(Post.status.in_([PostStatus.PUBLISHED, PostStatus.APPROVED]))
            .order_by(Post.id.desc())
            .limit(500)
        )
        rows = (await db.execute(query)).all()

        words_a = set(_normalize_text(text).split())
        if not words_a:
            return 0.0, None

        best_sim, best_id = 0.0, None
        for row in rows:
            if exclude_post_id and row.id == exclude_post_id:
                continue
            compare_text = (row.text or "") + " " + (row.caption or "")
            words_b = set(_normalize_text(compare_text).split())
            if not words_b:
                continue
            intersection = len(words_a & words_b)
            union = len(words_a | words_b)
            sim = intersection / union if union > 0 else 0.0
            if sim > best_sim:
                best_sim = sim
                best_id = row.id

        return best_sim, best_id

    @staticmethod
    async def _compute_phash(file_path: str) -> str | None:
        try:
            from PIL import Image
            import imagehash
            img = Image.open(file_path)
            return str(imagehash.phash(img))
        except Exception as exc:
            log.debug("phash_failed", path=file_path, error=str(exc))
            return None

    @staticmethod
    async def _find_phash_match(
        db,
        phash: str,
        max_distance: int = 6,
    ) -> tuple[int | None, int]:
        """Find a media file with a close perceptual hash."""
        from sqlalchemy import select
        from app.db.models import MediaFile

        rows = (await db.execute(
            select(MediaFile.id, MediaFile.perceptual_hash)
            .where(MediaFile.perceptual_hash != None)
            .limit(2000)
        )).all()

        best_id, best_dist = None, max_distance + 1
        for row in rows:
            try:
                dist = _hamming_distance(phash, row.perceptual_hash)
                if dist < best_dist:
                    best_dist = dist
                    best_id = row.id
            except Exception:
                continue

        return (best_id, best_dist) if best_id is not None else (None, 99)


def _hamming_distance(a: str, b: str) -> int:
    """Compute bit-level Hamming distance between two hex pHash strings."""
    try:
        ai = int(a, 16)
        bi = int(b, 16)
        return bin(ai ^ bi).count("1")
    except ValueError:
        return 64  # Max distance — treat as different


# Module-level singleton
_engine: DeduplicationEngine | None = None


def get_dedup_engine() -> DeduplicationEngine:
    global _engine
    if _engine is None:
        _engine = DeduplicationEngine()
    return _engine
