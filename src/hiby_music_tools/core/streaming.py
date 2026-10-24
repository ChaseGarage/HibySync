"""Measured binary copying shared by CLI sync and device transports."""
import os

CHUNK = 512 * 1024


def copy_stream(source, destination, *, progress=lambda count: None, checkpoint=lambda: None,
                tolerate_flush_errors=False):
    copied = 0
    while True:
        checkpoint()
        block = source.read(CHUNK)
        if not block:
            break
        view = memoryview(block)
        while view:
            checkpoint()
            written = destination.write(view)
            if written is None or written <= 0:
                raise OSError('The destination stopped accepting data')
            view = view[written:]
            copied += written
            try:
                os.fsync(destination.fileno())
            except OSError:
                if not tolerate_flush_errors:
                    raise
            progress(copied)  # Bytes written and flushed, never a timer estimate.
    return copied
