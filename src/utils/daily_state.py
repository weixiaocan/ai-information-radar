from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_degraded_fields(data: dict[str, Any]) -> dict[str, str]:
    return {
        "degraded_reason": _text(data.get("degraded_reason")),
        "degraded_stage": _text(data.get("degraded_stage")),
        "fallback_mode": _text(data.get("fallback_mode")),
    }


def with_degraded_fields(payload: dict[str, Any], **fields: str) -> dict[str, Any]:
    result = dict(payload)
    for key in ("degraded_reason", "degraded_stage", "fallback_mode"):
        value = _text(fields.get(key))
        if value:
            result[key] = value
    return result


def normalize_builder_hot_candidate(candidate: dict[str, Any] | None) -> dict[str, Any]:
    data = _as_dict(candidate)
    decision = _as_dict(data.get("decision"))
    copy = _as_dict(data.get("copy"))
    normalized = {
        "decision": {
            "content_id": _text(decision.get("content_id") or data.get("content_id")),
            "url": _text(decision.get("url") or data.get("url")),
            "source": _text(decision.get("source") or data.get("source")),
            "topic_key": _text(decision.get("topic_key")),
            "entered_hot_pool": bool(decision.get("entered_hot_pool", True)),
        },
        "copy": {
            "topic_label": _text(copy.get("topic_label") or data.get("topic_label")),
            "core_claim": _text(copy.get("core_claim") or data.get("core_claim")),
            "angle": _text(copy.get("angle") or data.get("angle")),
            "excerpt": _text(copy.get("excerpt") or data.get("excerpt")),
            "spotlight_text": _text(copy.get("spotlight_text") or data.get("spotlight_text")),
        },
        **_normalize_degraded_fields(data),
    }
    if not normalized["decision"]["topic_key"]:
        normalized["decision"]["topic_key"] = normalized["copy"]["topic_label"]
    return normalized


def builder_candidate_decision(candidate: dict[str, Any] | None) -> dict[str, Any]:
    return normalize_builder_hot_candidate(candidate).get("decision", {})


def builder_candidate_copy(candidate: dict[str, Any] | None) -> dict[str, Any]:
    return normalize_builder_hot_candidate(candidate).get("copy", {})


def normalize_theme(theme: dict[str, Any] | None, fallback_dispersion: str = "dispersed") -> dict[str, Any]:
    data = _as_dict(theme)
    decision = _as_dict(data.get("decision"))
    copy = _as_dict(data.get("copy"))
    evidence = []
    for entry in _as_list(copy.get("evidence") or data.get("evidence")):
        evidence_data = _as_dict(entry)
        evidence.append(
            {
                "source": _text(evidence_data.get("source")),
                "excerpt": _text(evidence_data.get("excerpt")),
                "url": _text(evidence_data.get("url")),
            }
        )
    member_content_ids = [
        _text(content_id)
        for content_id in _as_list(decision.get("member_content_ids") or data.get("related_content_ids"))
        if _text(content_id)
    ]
    representative_urls = [_text(url) for url in _as_list(decision.get("representative_urls")) if _text(url)]
    if not representative_urls:
        representative_urls = [item["url"] for item in evidence if item["url"]]
    return {
        "decision": {
            "theme_id": _text(decision.get("theme_id")),
            "member_content_ids": member_content_ids,
            "representative_urls": representative_urls,
            "discussion_dispersion": _text(decision.get("discussion_dispersion") or data.get("discussion_dispersion"))
            or fallback_dispersion,
        },
        "copy": {
            "theme_title": _text(copy.get("theme_title") or data.get("theme")),
            "theme_summary": _text(copy.get("theme_summary") or data.get("summary")),
            "evidence": evidence,
        },
        **_normalize_degraded_fields(data),
    }


def theme_decision(theme: dict[str, Any] | None, fallback_dispersion: str = "dispersed") -> dict[str, Any]:
    return normalize_theme(theme, fallback_dispersion=fallback_dispersion).get("decision", {})


def theme_copy(theme: dict[str, Any] | None, fallback_dispersion: str = "dispersed") -> dict[str, Any]:
    return normalize_theme(theme, fallback_dispersion=fallback_dispersion).get("copy", {})


def normalize_selection(selection: dict[str, Any] | None) -> dict[str, Any]:
    data = _as_dict(selection)
    decision = _as_dict(data.get("decision"))
    copy = _as_dict(data.get("copy"))
    return {
        "decision": {
            "content_id": _text(decision.get("content_id") or data.get("content_id")),
            "selected": bool(decision.get("selected", True)),
            "type": _text(decision.get("type") or data.get("type")),
            "channel_or_source": _text(decision.get("channel_or_source") or data.get("channel_or_source")),
            "title": _text(decision.get("title") or data.get("title")),
            "url": _text(decision.get("url") or data.get("url")),
        },
        "copy": {
            "value_pitch": _text(copy.get("value_pitch") or data.get("value_pitch")),
        },
        **_normalize_degraded_fields(data),
    }


def selection_decision(selection: dict[str, Any] | None) -> dict[str, Any]:
    return normalize_selection(selection).get("decision", {})


def selection_copy(selection: dict[str, Any] | None) -> dict[str, Any]:
    return normalize_selection(selection).get("copy", {})


def normalize_daily_candidates_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = _as_dict(payload)
    return {
        "builder_hot_candidates": [
            normalize_builder_hot_candidate(candidate)
            for candidate in _as_list(data.get("builder_hot_candidates"))
        ],
        "editorial_candidates_raw": _as_list(data.get("editorial_candidates_raw")),
        "editorial_candidates_filtered": _as_list(data.get("editorial_candidates_filtered")),
        "editorial_top10": _as_list(data.get("editorial_top10") or data.get("editorial_candidates")),
        "editorial_candidates": _as_list(data.get("editorial_candidates") or data.get("editorial_top10")),
        **_normalize_degraded_fields(data),
    }


def normalize_daily_themes_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = _as_dict(payload)
    dispersion = _text(data.get("discussion_dispersion")) or "dispersed"
    return {
        "themes": [normalize_theme(theme, fallback_dispersion=dispersion) for theme in _as_list(data.get("themes"))],
        "discussion_dispersion": dispersion,
        "spotlight_posts": _as_list(data.get("spotlight_posts")),
        "supplementary_items": _as_list(data.get("supplementary_items")),
        "supplementary_spotlight_posts": _as_list(data.get("supplementary_spotlight_posts")),
        "degraded_reason": _text(data.get("degraded_reason")),
        "degraded_source": _text(data.get("degraded_source")),
        "degraded_stage": _text(data.get("degraded_stage")),
        "fallback_mode": _text(data.get("fallback_mode")),
    }


def normalize_daily_selections_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = _as_dict(payload)
    return {
        "selections": [normalize_selection(selection) for selection in _as_list(data.get("selections"))],
        "selection_diversity": _text(data.get("selection_diversity")),
        **_normalize_degraded_fields(data),
    }
