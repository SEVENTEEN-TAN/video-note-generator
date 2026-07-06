from __future__ import annotations

from backend.app.models import FrameCandidate, FrameCandidateIndex


def test_frame_candidate_models_serialize_expected_shape() -> None:
    index = FrameCandidateIndex(
        candidates=[
            FrameCandidate(
                id="chapter_001_candidate_001",
                chapter_index=0,
                time=12.5,
                path="review/frame_candidates/chapter_001/candidate_001.jpg",
                reason="Opening concept slide",
                source="chapter_fallback",
                hash="010101",
                duplicate_of=None,
                similarity=0.0,
                risk_flags=[],
                selected=True,
                rejected=False,
            )
        ]
    )

    payload = index.model_dump(mode="json")

    assert payload["candidates"][0]["id"] == "chapter_001_candidate_001"
    assert payload["candidates"][0]["selected"] is True
    assert payload["candidates"][0]["risk_flags"] == []
