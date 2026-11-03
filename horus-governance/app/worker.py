import fcntl
import json
import os
import signal
from threading import Event
from time import time

from .service import Governance
from .settings import Settings


def main():
    os.umask(0o077)
    settings = Settings.load()
    settings.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    stopping = Event()
    signal.signal(signal.SIGTERM, lambda signum, frame: stopping.set())
    signal.signal(signal.SIGINT, lambda signum, frame: stopping.set())
    with (settings.state_root / "worker.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        governance = Governance(settings)
        with governance.ledger.transaction() as connection:
            connection.execute("UPDATE submissions SET status='error',error=? WHERE status='running'",
                               ("Analysis was interrupted. No automatic reanalysis or approval was issued.",))
        print("Horus analysis worker ready", flush=True)
        while not stopping.is_set():
            (settings.state_root / "worker-status.json").write_text(json.dumps({"updated_at": time()}))
            if governance.work_once():
                print("Analysis queue item completed", flush=True)
            else:
                stopping.wait(1)


if __name__ == "__main__":
    main()