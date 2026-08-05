"""Agent service: dual-speed poll + MQTT."""

from __future__ import annotations

import logging
import signal
import threading
import time
from dataclasses import replace

from .config import Settings
from .mqtt_bridge import MqttBridge
from .toilet import ToiletClient, ToiletState

log = logging.getLogger(__name__)


class AgentService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.toilet = ToiletClient(
            settings.toilet_host,
            settings.toilet_token,
            timeout=settings.miio_timeout,
            poll_gap=settings.poll_gap_sec,
        )
        self.mqtt = MqttBridge(
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            username=settings.mqtt_user,
            password=settings.mqtt_password,
            prefix=settings.mqtt_prefix,
            client_id=settings.mqtt_client_id,
            discovery_prefix=settings.mqtt_discovery_prefix,
            device_name=settings.toilet_name,
            model=settings.toilet_model,
            mac=settings.toilet_mac,
            on_command=self._on_command,
        )
        self._stop = threading.Event()
        # Serializes all miIO access + MQTT publish of toilet state.
        self._device_lock = threading.Lock()
        self._last_published: ToiletState | None = None

    def run_forever(self) -> None:
        self.mqtt.connect()
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        seating_iv = max(1.0, self.settings.seating_interval_sec)
        full_iv = max(seating_iv, self.settings.full_interval_sec)
        next_seating = 0.0
        next_full = 0.0

        log.info(
            "started host=%s seating=%ss full=%ss mqtt=%s:%s",
            self.settings.toilet_host,
            seating_iv,
            full_iv,
            self.settings.mqtt_host,
            self.settings.mqtt_port,
        )

        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if now >= next_full:
                    with self._device_lock:
                        state = self.toilet.poll_full()
                        self._publish(state)
                    next_full = now + full_iv
                    next_seating = now + seating_iv
                elif now >= next_seating:
                    with self._device_lock:
                        state = self.toilet.poll_seating()
                        self._publish(state)
                    next_seating = now + seating_iv
            except Exception:  # noqa: BLE001
                log.exception("poll loop error")

            sleep_for = min(next_seating, next_full) - time.monotonic()
            self._stop.wait(timeout=max(0.2, sleep_for))

        self.mqtt.stop()
        log.info("stopped")

    def _handle_signal(self, *_args: object) -> None:
        self._stop.set()

    def _publish(self, state: ToiletState) -> None:
        self.mqtt.publish_state(state)
        self._last_published = replace(state)

    def _on_command(self, entity: str, payload: str) -> None:
        raw = payload.strip()
        upper = raw.upper()
        want_on = upper in {"ON", "1", "TRUE"}
        with self._device_lock:
            try:
                if entity == "flush" and upper in {"PRESS", "ON", "1", "TRUE"}:
                    self.toilet.flush()
                elif entity == "self_clean" and upper in {"PRESS", "ON", "1", "TRUE"}:
                    self.toilet.self_clean()
                elif entity == "air_filter" and upper in {"PRESS", "ON", "1", "TRUE"}:
                    self.toilet.air_filter()
                elif entity == "bubble_shield" and upper in {"PRESS", "ON", "1", "TRUE"}:
                    self.toilet.bubble_shield()
                elif entity == "seat_heat":
                    self.toilet.set_seat_heat(want_on)
                elif entity == "night_led":
                    self.toilet.hold_night_led(want_on)
                    self._publish(self.toilet.state)
                    self.toilet.set_night_led(want_on)
                elif entity == "tun_wash":
                    self.toilet.set_tun_wash(want_on)
                elif entity == "women_wash":
                    self.toilet.set_women_wash(want_on)
                elif entity == "warm_dry":
                    self.toilet.set_warm_dry(want_on)
                elif entity in {"moving_t", "moving"}:
                    self.toilet.set_moving(want_on)
                elif entity in {"massage_t", "massage"}:
                    self.toilet.set_massage(want_on)
                elif entity in {
                    "water_temp_t",
                    "water_strong_t",
                    "water_pos_t",
                    "water_temp_w",
                    "water_strong_w",
                    "water_pos_w",
                    "fan_temp",
                }:
                    self.toilet.set_level(entity, int(float(raw)))
                else:
                    log.warning("unknown command entity=%s payload=%s", entity, payload)
                    return
            except Exception as err:  # noqa: BLE001
                log.error("command %s failed: %s", entity, err)
                return

            log.info("command ok entity=%s payload=%s", entity, payload)
            self._publish(self.toilet.state)
            if entity == "night_led":
                return
            time.sleep(0.8)
            self._publish(self.toilet.poll_full())
