import unittest
import verify_home_bridge
import verify_worker_latency


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_completion_and_command_admission(self):
        await verify_home_bridge.main()

    async def test_worker_cleanup_and_no_motor_replay(self):
        await verify_worker_latency.main()
