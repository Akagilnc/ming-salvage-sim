def test_for_role_advanced_drops_placeholder_key():
    # ship-pre CMR round-4：advanced_api_key 占位符不该泄漏到 advanced 角色的 OpenAI client。
    from ming_sim.llm_config import for_role
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(
        api_key="sk-main", base_url="https://api.x/v1", model="m",
        advanced_model="gpt-adv", advanced_api_key="cli-backend", channel="api",
    )
    adv = for_role(cfg, "simulator")

    assert adv.api_key == "sk-main"
    assert adv.api_key != "cli-backend"
