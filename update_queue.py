"""In-memory update lease. Admission is serialized by the server's operation lock."""
import time
import re


class UpdateQueue:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.ticket = None
        self.expires = 0
        self.stopping = False

    def status(self):
        if not self.stopping and self.clock() >= self.expires:
            self.ticket = None
        return {'queued': self.ticket is not None, 'stopping': self.stopping}

    def queue(self, ticket):
        if not isinstance(ticket, str) or not re.fullmatch('[a-f0-9]{32}', ticket):
            raise ValueError('Invalid update request.')
        if self.status()['queued'] and ticket != self.ticket:
            raise ValueError('An update helper is already waiting.')
        self.ticket, self.expires = ticket, self.clock() + 300

    def claim(self, ticket, state):
        if not self.status()['queued'] or ticket != self.ticket:
            raise ValueError('Update cancelled or expired. Open the update helper again.')
        self.expires = self.clock() + 300
        if state.get('status') == 'running':
            return False
        if state.get('status') == 'ready' and not state.get('deliveryCompleted'):
            return False
        self.stopping = True
        return True

    def cancel(self):
        if self.stopping:
            raise ValueError('Installation has started. Wait for eznest to restart.')
        self.ticket = None
        self.expires = 0
