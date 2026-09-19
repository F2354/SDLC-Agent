from app.services.process_graph import get_stage_dependencies


def test_v_model_exposes_parallel_verification_dependencies():
    codes = [
        "requirements",
        "architecture",
        "detailed-design",
        "coding",
        "unit-test",
        "integration-test",
        "system-test",
    ]
    assert get_stage_dependencies("v-model", "unit-test", codes) == ["coding"]
    assert get_stage_dependencies("v-model", "integration-test", codes) == ["coding"]
    assert get_stage_dependencies("v-model", "system-test", codes) == ["coding"]


def test_waterfall_remains_a_strict_dependency_chain():
    codes = ["requirements", "architecture", "detailed-design", "coding", "testing"]
    assert get_stage_dependencies("waterfall", "requirements", codes) == []
    assert get_stage_dependencies("waterfall", "testing", codes) == ["coding"]


def test_unknown_model_falls_back_to_displayed_order():
    codes = ["one", "two", "three"]
    assert get_stage_dependencies("custom", "three", codes) == ["two"]
