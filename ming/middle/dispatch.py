"""分派：声明或「接不住」→ 账本的一类事实。皇帝原话由这里在落账时写入，不经过转译。"""

from ming.ledger import Ledger
from ming.middle.declaration import Declaration
from ming.middle.translate import Unhandled


def dispatch(ledger: Ledger, result: Declaration | Unhandled, emperor_words: str) -> None:
    if isinstance(result, Unhandled):
        detail = {"model_text": result.model_text, "failure_point": result.failure_point}
        ledger.record_text("unhandled", emperor_words, detail)
        return
    for assign in result.assigns:
        ledger.record_affair(assign.assignees, emperor_words, {"task": assign.task})
    for grant in result.grants:
        ledger.record_number(
            "grant_nominal", grant.amount_taels, emperor_words, {"recipient": grant.recipient, "purpose": grant.purpose}
        )
