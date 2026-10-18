"""分派：声明或「接不住」→ 账本的一类事实。皇帝原话由这里在落账时写入，不经过转译。"""

from ming.ledger import Ledger
from ming.middle.declaration import Assign, Grant, NoOrder
from ming.middle.translate import Declaration, Unhandled


def dispatch(ledger: Ledger, result: Declaration | Unhandled, emperor_words: str) -> None:
    match result:
        case Assign(assignees=assignees, task=task):
            ledger.record_affair(assignees, emperor_words, {"task": task})
        case Grant(recipient=recipient, amount_taels=amount, purpose=purpose):
            ledger.record_number("grant_nominal", amount, emperor_words, {"recipient": recipient, "purpose": purpose})
        case Unhandled(model_text=model_text, failure_point=failure_point):
            detail = {"model_text": model_text, "failure_point": failure_point}
            ledger.record_text("unhandled", emperor_words, detail)
        case NoOrder():
            pass
