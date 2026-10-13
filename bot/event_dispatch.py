"""Process independent LINE senders concurrently, in arrival order per sender."""
import asyncio
import logging


class UserEventDispatcher:
    def __init__(self, concurrency=8):
        self._slots = asyncio.Semaphore(concurrency)
        self._tails = {}

    def submit(self, user_id, work):
        previous = self._tails.get(user_id)

        async def run():
            try:
                if previous:
                    try:
                        await asyncio.shield(previous)
                    except Exception:
                        pass  # A failed event must not block later events.
                async with self._slots:
                    return await asyncio.to_thread(work)
            finally:
                if self._tails.get(user_id) is asyncio.current_task():
                    del self._tails[user_id]

        task = asyncio.create_task(run())
        self._tails[user_id] = task
        # Retrieve exceptions even if the HTTP requester disconnects.
        def completed(result):
            if not result.cancelled():
                error = result.exception()
                if error:
                    logging.error("LINE event processing failed: %s", type(error).__name__)
        task.add_done_callback(completed)
        return task


webhook_dispatcher = UserEventDispatcher()
