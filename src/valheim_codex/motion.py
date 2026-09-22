"""Renew short input leases, never invent or prolong the model's travel intent."""
import threading


class MotionHeartbeat:
    def __init__(self, client, epoch):
        self.client, self.epoch = client, epoch
        self.closed = threading.Event()
        self.failure = None
        self.thread = threading.Thread(target=self._run, name="player-travel", daemon=True)
        self.thread.start()

    def _run(self):
        while not self.closed.wait(.2):
            try:
                result = self.client.request("/control/travel-heartbeat", {"epoch": self.epoch}, timeout=1)
                # A map/inventory temporarily rejects gameplay renewal. Keep
                # checking while the supervisor exists; a false response grants
                # no input, and neither a heartbeat nor a late retry starts a
                # route. Stop/resume epochs remain checked by the gateway.
            except Exception as exc:
                self.failure = type(exc).__name__
                # Do not resume or retry: the plugin's <=900ms lease expires.
                return

    def close(self):
        self.closed.set()
        self.thread.join(timeout=2)
