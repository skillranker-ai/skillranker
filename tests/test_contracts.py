"""Tests for backend.contracts — contract validation and rendering."""

from backend.contracts import ENRICHMENT_CONTRACT, render_contract, validate_contract


def _valid_response() -> dict:
    """A valid enrichment response matching the contract."""
    return {
        "domains": ["coding", "testing"],
        "tags": ["unit-test", "pytest", "coverage", "automation", "ci"],
        "summary": "A skill that helps set up and run comprehensive test suites for Python projects.",
        "strengths": [
            "Clear instructions for test setup",
            "Covers multiple testing frameworks",
            "Includes CI integration steps",
        ],
        "weaknesses": ["Limited to Python projects"],
        "use_cases": [
            "Setting up pytest for a new project",
            "Adding test coverage reporting to CI",
            "Migrating from unittest to pytest",
        ],
        "score_quality": 72,
        "score_usefulness": 68,
        "score_novelty": 45,
        "score_description": 60,
        "score_reusability": 55,
    }


def test_validate_valid_response():
    """A well-formed response should pass validation."""
    errors = validate_contract(ENRICHMENT_CONTRACT, _valid_response())
    assert errors == [], f"Expected no errors, got: {errors}"


def test_validate_missing_required_field():
    """Missing a required field should produce an error."""
    data = _valid_response()
    del data["summary"]
    errors = validate_contract(ENRICHMENT_CONTRACT, data)
    assert any("summary" in e for e in errors)


def test_validate_score_out_of_range():
    """Scores outside 0-100 should be caught."""
    data = _valid_response()
    data["score_quality"] = 150
    errors = validate_contract(ENRICHMENT_CONTRACT, data)
    assert any("score_quality" in e for e in errors)


def test_validate_wrong_type():
    """String instead of list should be caught."""
    data = _valid_response()
    data["domains"] = "coding"  # should be a list
    errors = validate_contract(ENRICHMENT_CONTRACT, data)
    assert any("domains" in e for e in errors)


def test_validate_too_few_tags():
    """Tags must have exactly 5 entries."""
    data = _valid_response()
    data["tags"] = ["a", "b"]
    errors = validate_contract(ENRICHMENT_CONTRACT, data)
    assert any("tags" in e for e in errors)


def test_validate_too_many_domains():
    """Domains must have 1-3 entries."""
    data = _valid_response()
    data["domains"] = ["a", "b", "c", "d"]
    errors = validate_contract(ENRICHMENT_CONTRACT, data)
    assert any("domains" in e for e in errors)


def test_validate_short_summary():
    """Summary must be at least 10 characters."""
    data = _valid_response()
    data["summary"] = "Short"
    errors = validate_contract(ENRICHMENT_CONTRACT, data)
    assert any("summary" in e for e in errors)


def test_render_contract_contains_fields():
    """Rendered markdown should contain all required field names."""
    rendered = render_contract("test", ENRICHMENT_CONTRACT)
    for field in ENRICHMENT_CONTRACT["required"]:
        assert field in rendered, f"Field '{field}' missing from rendered contract"


def test_render_contract_has_example():
    """Rendered markdown should include the example JSON."""
    rendered = render_contract("test", ENRICHMENT_CONTRACT)
    assert "Example" in rendered
    assert "score_quality" in rendered


def test_validate_non_dict_input():
    """Non-dict input should fail."""
    errors = validate_contract(ENRICHMENT_CONTRACT, "not a dict")
    assert errors == ["Input must be a JSON object"]
