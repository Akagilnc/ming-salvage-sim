def test_run_agent_text_without_prior_passes_plain_prompt():
    from ming_sim.agents import run_agent_text

    captured: list[object] = []

    class _Agent:
        def run(self, input):
            captured.append(input)

            class _Out:
                content = "x"
                messages = None

            return _Out()

    assert run_agent_text(_Agent(), "solo", tag="t") == "x"
    assert captured == ["solo"]
