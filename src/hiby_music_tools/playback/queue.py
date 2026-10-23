"""Queue policy independent of Qt, the library views, and the audio engine."""

import random
import uuid


class MusicQueue:
    def __init__(self):
        self.entries = []
        self.current = ''
        self.shuffle = False
        self.repeat = 'off'
        self._order = []

    @property
    def index(self):
        return next((i for i, entry in enumerate(self.entries) if entry['qid'] == self.current), -1)

    def _make(self, tracks):
        return [{**track, 'qid': uuid.uuid4().hex} for track in tracks]

    def replace(self, tracks, selected='', shuffle=None):
        self.entries = self._make(tracks)
        self._order = [entry['qid'] for entry in self.entries]
        self.current = next((e['qid'] for e in self.entries if e['id'] == selected),
                            self.entries[0]['qid'] if self.entries else '')
        if shuffle is not None:
            self.shuffle = shuffle
        if self.shuffle:
            self._shuffle_remaining(include_history=True)

    def add(self, tracks, next_up=False):
        entries = self._make(tracks)
        at = self.index + 1 if next_up and self.index >= 0 else len(self.entries)
        self.entries[at:at] = entries
        self._order.extend(e['qid'] for e in entries)
        if not self.current and self.entries:
            self.current = self.entries[0]['qid']

    def remove(self, qid):
        index = next((i for i, e in enumerate(self.entries) if e['qid'] == qid), -1)
        if index < 0:
            return
        self.entries.pop(index)
        self._order = [key for key in self._order if key != qid]
        if qid == self.current:
            self.current = self.entries[min(index, len(self.entries) - 1)]['qid'] if self.entries else ''

    def move(self, qid, target):
        index = next((i for i, e in enumerate(self.entries) if e['qid'] == qid), -1)
        if index < 0:
            return
        self.entries.insert(max(0, min(len(self.entries) - 1, target)), self.entries.pop(index))
        if not self.shuffle:
            self._order = [e['qid'] for e in self.entries]

    def _shuffle_remaining(self, include_history=False):
        index = self.index
        if include_history:
            current = [e for e in self.entries if e['qid'] == self.current]
            rest = [e for e in self.entries if e['qid'] != self.current]
            random.shuffle(rest)
            self.entries = current + rest
        else:
            rest = self.entries[index + 1:]
            random.shuffle(rest)
            self.entries[index + 1:] = rest

    def set_shuffle(self, enabled):
        if enabled == self.shuffle:
            return
        self.shuffle = enabled
        if enabled:
            self._shuffle_remaining()
        else:
            rank = {key: i for i, key in enumerate(self._order)}
            self.entries.sort(key=lambda e: rank.get(e['qid'], len(rank)))

    def adjacent(self, direction, *, completed=False):
        if not self.entries:
            return ''
        index = self.index
        if completed and self.repeat == 'one':
            return self.current
        target = index + direction
        if self.repeat == 'all':
            target %= len(self.entries)
        return self.entries[target]['qid'] if 0 <= target < len(self.entries) else ''

    def snapshot(self):
        return dict(version=1, entries=self.entries, current=self.current,
                    order=self._order, shuffle=self.shuffle, repeat=self.repeat)

    def restore(self, state):
        if state.get('version') != 1:
            return
        entries = state.get('entries', [])
        if not isinstance(entries, list):
            raise ValueError('Invalid saved queue')
        keys = set()
        self.entries = []
        for entry in entries[:100000]:
            if (isinstance(entry, dict) and isinstance(entry.get('qid'), str)
                    and entry['qid'] not in keys and isinstance(entry.get('id'), str)
                    and isinstance(entry.get('path'), str) and entry['path'].startswith('/')):
                self.entries.append(entry)
                keys.add(entry['qid'])
        self.current = state.get('current') if state.get('current') in keys else (self.entries[0]['qid'] if self.entries else '')
        order = state.get('order', [])
        self._order = [key for key in order if isinstance(key, str) and key in keys] if isinstance(order, list) else []
        ordered = set(self._order)
        self._order.extend(e['qid'] for e in self.entries if e['qid'] not in ordered)
        self.shuffle = bool(state.get('shuffle', False))
        self.repeat = state.get('repeat') if state.get('repeat') in ('off', 'all', 'one') else 'off'
