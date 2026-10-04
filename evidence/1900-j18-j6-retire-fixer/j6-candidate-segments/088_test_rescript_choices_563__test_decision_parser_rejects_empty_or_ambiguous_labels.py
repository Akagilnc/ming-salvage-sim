def test_decision_parser_rejects_empty_or_ambiguous_labels(labels):
    from ming_sim.settlement_payload import parse_decision_blocks

    block = {
        "title": "歧义抉择", "context": "c",
        "options": [{"label": label, "hint": "h"} for label in labels],
    }
    raw = f"<<DECISION>>{json.dumps(block, ensure_ascii=False)}<<END>>"
    decisions = parse_decision_blocks(raw)
    assert decisions == []
