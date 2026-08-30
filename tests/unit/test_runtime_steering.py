from bluewhale_agent.agent.steering import RuntimeInstructionQueue


def test_queue_drains_in_order_and_can_withdraw_pending_instruction() -> None:
    queue = RuntimeInstructionQueue()
    first = queue.enqueue("先检查测试")
    second = queue.enqueue("不要修改配置")

    withdrawn = queue.withdraw(second.id)
    drained = queue.drain()

    assert withdrawn == second
    assert drained == (first,)
    assert queue.pending == ()


def test_cannot_withdraw_an_instruction_after_delivery() -> None:
    queue = RuntimeInstructionQueue()
    item = queue.enqueue("继续")
    queue.drain()

    assert queue.withdraw(item.id) is None
