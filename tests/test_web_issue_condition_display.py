import web_app


def test_humanize_character_loyalty_condition_hides_machine_threshold():
    text = web_app._humanize_condition("character.毛文龙.loyalty >= 65")

    assert text == "毛文龙忠诚回稳"
    assert "character" not in text
    assert "65" not in text
