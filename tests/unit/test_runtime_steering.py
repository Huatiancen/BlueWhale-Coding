from bluewhale_agent.agent.steering import (
    QueuedFollowUpQueue,
    RuntimeInstructionQueue,
)


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


def test_follow_up_queue_trims_content_and_pops_in_fifo_order() -> None:
    queue = QueuedFollowUpQueue()
    first = queue.enqueue("  先解释原因  ")
    second = queue.enqueue("再修复测试")

    assert first.content == "先解释原因"
    assert queue.pop_next() == first
    assert queue.pop_next() == second
    assert queue.pop_next() is None
    assert queue.pending == ()


def test_follow_up_can_only_be_consumed_once() -> None:
    queue = QueuedFollowUpQueue()
    steered = queue.enqueue("现在调整方向")
    withdrawn = queue.enqueue("取消下一问")

    assert queue.take_for_steering(steered.id) == steered
    assert queue.take_for_steering(steered.id) is None
    assert queue.withdraw(withdrawn.id) == withdrawn
    assert queue.withdraw(withdrawn.id) is None
