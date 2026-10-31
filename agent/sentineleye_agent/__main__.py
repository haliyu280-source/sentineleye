"""Agent entry point: collect -> validate -> send, on a fixed interval.

Usage:
    python -m sentineleye_agent                 run continuously (what systemd does)
    python -m sentineleye_agent --once          collect and send one sample, then exit
    python -m sentineleye_agent --print         collect one sample and print it; nothing is sent
"""

import argparse
import json
import logging
import random
import signal
import sys
import threading
import time

from . import __version__
from .client import BackendClient, DeliveryError
from .collector import CollectionError, Collector, validate_sample
from .config import ConfigError, load_config

log = logging.getLogger("sentineleye.agent")


class Agent:
    def __init__(self, config, collector=None, client=None, sleep=None, rng=None):
        self.config = config
        self.collector = collector or Collector(disk_path=config.disk_path)
        self.client = client or BackendClient(config)
        self.stop_event = threading.Event()
        self._sleep = sleep or self.stop_event.wait
        self._rng = rng or random.Random()
        # Failures since the last successful delivery, reported to the backend with the next sample
        self.failed_attempts = 0
        self.last_error: str | None = None

    def backoff(self, attempt: int) -> float:
        """Exponential backoff with jitter, capped so retries never outlast the collection interval."""
        base = min(2 ** attempt, 60)
        cap = max(1.0, self.config.interval_seconds / 2)
        return min(base * self._rng.uniform(0.8, 1.2), cap)

    def deliver(self, sample: dict) -> bool:
        for attempt in range(self.config.max_retries + 1):
            sample["delivery"] = {"failed_attempts": self.failed_attempts, "last_error": self.last_error}
            try:
                result = self.client.send(sample)
            except DeliveryError as err:
                if err.status == 409:
                    # Usually an earlier attempt got through but its response was lost
                    log.warning("Backend already has this or a newer sample; skipping it")
                    return False
                self.failed_attempts += 1
                self.last_error = str(err)[:500]
                if not err.retryable:
                    log.error("Delivery rejected: %s", err)
                    return False
                if attempt == self.config.max_retries or self.stop_event.is_set():
                    log.error("Delivery failed after %d attempt(s): %s", attempt + 1, err)
                    return False
                delay = self.backoff(attempt)
                log.warning("Delivery failed (%s); retrying in %.1fs", err, delay)
                self._sleep(delay)
                continue

            if self.failed_attempts:
                log.info("Delivered after %d failed attempt(s)", self.failed_attempts)
            self.failed_attempts = 0
            self.last_error = None
            log.debug("Sample accepted; server status %s", result.server_status)
            return True
        return False

    def run_once(self) -> bool:
        try:
            sample = self.collector.collect(self.config.server_id)
            validate_sample(sample)
        except (CollectionError, OSError, ValueError) as err:
            log.error("Collection failed: %s", err)
            return False
        return self.deliver(sample)

    def run_forever(self) -> None:
        log.info(
            "SentinelEye agent %s reporting to %s every %ss as server %s",
            __version__, self.config.backend_url, self.config.interval_seconds, self.config.server_id,
        )
        while not self.stop_event.is_set():
            started = time.monotonic()
            self.run_once()
            elapsed = time.monotonic() - started
            self.stop_event.wait(max(0.0, self.config.interval_seconds - elapsed))
        log.info("Agent stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentineleye-agent", description="SentinelEye Linux monitoring agent")
    parser.add_argument("--config", help="KEY=VALUE file, e.g. /etc/sentineleye-agent/agent.env")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="send one sample and exit")
    mode.add_argument("--print", action="store_true", help="print one sample without sending it")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.print:
        collector = Collector()
        try:
            collector.check_supported()
            sample = collector.collect(server_id=0)
            validate_sample(sample)
        except CollectionError as err:
            log.error("%s", err)
            return 1
        print(json.dumps(sample, indent=2))
        return 0

    try:
        config = load_config(config_file=args.config)
        Collector().check_supported()
    except (ConfigError, CollectionError, OSError) as err:
        log.error("Cannot start: %s", err)
        return 2

    agent = Agent(config)
    if args.once:
        return 0 if agent.run_once() else 1

    def _stop(signum, _frame):
        log.info("Received signal %s, stopping", signum)
        agent.stop_event.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    agent.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
