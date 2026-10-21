# Month boundary recordings (#1948)

Captured on 2026-10-20 through the existing OpenAI-compatible development endpoint.
The `.txt` files are model responses, not hand-built declarations; Markdown fences
and the malformed `changes` object are intentionally retained. Tests pass the
whole response to the real Pydantic AI translation boundary and assert structured
ledger results, not prose.

| Recording | Native model | Input |
| --- | --- | --- |
| `month_empty.txt` | `anthropic/claude-haiku-4.5` | 本月诸务平稳，未有新事。没有字段变化，没有文字新事实，也没有需要请旨的事情。 |
| `month_money_300000.txt` | `deepseek/deepseek-v4-flash` | 本月国库向内库拨银300000两。 |
| `month_money_3200000.txt` | `deepseek/deepseek-v4-flash` | 本月国库向内库拨银3200000两。 |
| `month_money_5000000.txt` | `anthropic/claude-haiku-4.5` | 已有国库、内库；已议准拨银五百万两，另有官员奏报已如数解银，奏报只记文字。 |
| `month_petition.txt` | `deepseek/deepseek-v4-flash` | 陕西饥民待赈，巡抚奏请皇帝选择：一、先赈饥民，二、先修仓廪。记到已有事务 `world:1627:10` 的 `petition`。 |
| `month_invalid.txt` | `deepseek/deepseek-v4-flash` | 同一请旨输入，未使用 typed output 的原始错误回话。 |

Money inputs also supplied the declaration field shape and reciprocal counterpart
requirement; petition inputs supplied the existing affair identity and allowed
field. These recordings prove deterministic landing for correctly supplied
inputs, not a model's ability to interpret a complete audience. Full real-model
north-star runs and genuine CLI failures are separate acceptance evidence in the
#1948 coder run ledger.

## Named-step recordings (#1956)

These complete `model output:` records were copied unchanged from
`~/WorkSpace/vault/ak-cc-wiki/raw/ming-llm-runner/2026-10-20/northstar-accept/A/saves/df549bf5-99de-4fff-8182-6516f929f1ce.errors.log`:

| Recording | Source lines (inclusive) |
| --- | --- |
| `deliberation.txt` | 2–42 |
| `simulation.txt` | 43–75 |
| `gazette.txt` | 740–773 |

Only the log's `model output: ` prefix was removed. In particular, the gazette's
editorial postscript is retained. Native `Agent.override` substitutes each named
call independently; recordings do not determine the identity or permissions of
its tools. The complete-month tests drain night precomputation before presenting
the existing-world petition recording, so that its referenced entity exists.

The above translation recordings do **not** include a valid new-affair
petition followed by a valid final declaration creating that affair.
`month_petition.txt` is not evidence for that boundary. The #1956 coder receipt
reports the separate native-CLI acceptance and old-logic mutation run; no
synthetic replacement or vacuous absence assertion has been added.
