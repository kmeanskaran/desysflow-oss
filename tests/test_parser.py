import pytest

from schemas.models import Requirements
from utils.parser import normalize_llm_text, parse_json_response


def test_normalize_llm_text_handles_content_blocks() -> None:
    raw = [
        {"type": "text", "text": '{"traffic_estimate":"5M DAU",'},
        {"type": "text", "text": '"latency_requirement":"<100ms p99",'},
        {
            "type": "text",
            "text": (
                '"consistency_requirement":"eventual",'
                '"budget_constraint":"moderate",'
                '"region":"us-east-1",'
                '"scale_growth_projection":"3x in 12 months",'
                '"critical_features":["uploads","search"]}'
            ),
        },
    ]

    requirements = parse_json_response(normalize_llm_text(raw), Requirements)

    assert requirements.traffic_estimate == "5M DAU"
    assert requirements.critical_features == ["uploads", "search"]


def test_parse_json_response_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="empty response"):
        parse_json_response("", Requirements)


def test_normalize_llm_text_handles_nested_content_dict() -> None:
    raw = {
        "content": [
            {
                "type": "output_text",
                "text": (
                    '{"traffic_estimate":"1M MAU","latency_requirement":"<200ms p99",'
                    '"consistency_requirement":"strong","budget_constraint":"high",'
                    '"region":"eu-west-1","scale_growth_projection":"2x in 6 months",'
                    '"critical_features":["billing"]}'
                ),
            }
        ]
    }

    requirements = parse_json_response(normalize_llm_text(raw), Requirements)

    assert requirements.region == "eu-west-1"
    assert requirements.critical_features == ["billing"]
