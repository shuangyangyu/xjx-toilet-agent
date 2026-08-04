"""MQTT Home Assistant discovery + command bridge."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from .toilet import ToiletState

log = logging.getLogger(__name__)

OnCommand = Callable[[str, str], None]


class MqttBridge:
    """Publish state / discovery; receive set / button commands."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        prefix: str,
        client_id: str,
        discovery_prefix: str,
        device_name: str,
        model: str,
        mac: str,
        on_command: OnCommand,
    ) -> None:
        self.prefix = prefix.rstrip("/")
        self.discovery_prefix = discovery_prefix.rstrip("/")
        self.on_command = on_command
        self.mac = mac
        self.slug = "".join(c for c in mac.lower() if c.isalnum()) or "toilet"
        self._device = {
            "identifiers": [f"xjx_toilet_{self.slug}"],
            "name": device_name,
            "manufacturer": "XiaoJingXi",
            "model": model,
            "connections": [["mac", mac]] if mac else [],
            "sw_version": "0.1.2",
        }
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        if username:
            self._client.username_pw_set(username, password or None)
        self._client.will_set(self.availability_topic, "offline", qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._last_payload: dict[str, Any] | None = None

    @property
    def availability_topic(self) -> str:
        return f"{self.prefix}/status"

    @property
    def state_topic(self) -> str:
        return f"{self.prefix}/state"

    @property
    def command_topic(self) -> str:
        return f"{self.prefix}/command"

    def connect(self) -> None:
        self._client.connect(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        try:
            self.publish_availability("offline")
        except Exception:  # noqa: BLE001
            pass
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client: mqtt.Client, *_args: Any) -> None:
        log.info("MQTT connected")
        client.subscribe(f"{self.command_topic}/#", qos=1)
        client.subscribe(f"{self.prefix}/+/set", qos=1)
        self.publish_availability("online")
        self.publish_discovery()
        if self._last_payload is not None:
            self._publish_json(self.state_topic, self._last_payload, retain=True)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        # xjx/toilet/command/<action>  or  xjx/toilet/<entity>/set
        try:
            if topic.startswith(f"{self.command_topic}/"):
                action = topic[len(self.command_topic) + 1 :]
                self.on_command(action, payload)
                return
            if topic.startswith(f"{self.prefix}/") and topic.endswith("/set"):
                entity = topic[len(self.prefix) + 1 : -4]
                self.on_command(entity, payload)
        except Exception:  # noqa: BLE001
            log.exception("command handler failed topic=%s payload=%s", topic, payload)

    def publish_availability(self, status: str) -> None:
        with self._lock:
            self._client.publish(self.availability_topic, status, qos=1, retain=True)

    def _publish_json(self, topic: str, payload: dict[str, Any], *, retain: bool) -> None:
        with self._lock:
            self._client.publish(
                topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=retain
            )

    def publish_state(self, state: ToiletState) -> None:
        payload = state.to_mqtt()
        self._last_payload = payload
        self._publish_json(self.state_topic, payload, retain=True)
        # Availability = agent↔MQTT 链路，不要和马桶 miIO 通断绑在一起。
        self.publish_availability("online")

    def _disc(self, component: str, object_id: str) -> str:
        return f"{self.discovery_prefix}/{component}/xjx_toilet_{self.slug}_{object_id}/config"

    def publish_discovery(self) -> None:
        """Register HA MQTT entities (JSON state + templates)."""
        avail = {
            "availability": [
                {
                    "topic": self.availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                }
            ],
            "device": self._device,
        }
        state = self.state_topic

        binaries = [
            ("online", "设备在线", "connectivity", "mdi:lan-connect"),
            ("seating", "着坐", "occupancy", "mdi:toilet"),
            ("tun_wash", "臀洗进行中", None, "mdi:shower-head"),
            ("women_wash", "妇洗进行中", None, "mdi:shower-head"),
            ("warm_dry", "烘干进行中", None, "mdi:hair-dryer"),
        ]
        for key, name, device_class, icon in binaries:
            cfg: dict[str, Any] = {
                **avail,
                "name": name,
                "unique_id": f"xjx_toilet_{self.slug}_{key}",
                "state_topic": state,
                "value_template": (
                    f"{{{{ 'ON' if value_json.{key} else 'OFF' }}}}"
                ),
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": icon,
            }
            if device_class:
                cfg["device_class"] = device_class
            self._publish_json(self._disc("binary_sensor", key), cfg, retain=True)

        sensors = [
            ("seat_temp", "座温档位", "mdi:thermometer", None, None),
            ("water_temp_t", "臀洗水温", "mdi:thermometer-water", None, None),
            ("water_strong_t", "臀洗水量", "mdi:water", None, None),
            ("water_pos_t", "臀洗位置", "mdi:arrow-expand-vertical", None, None),
            ("water_temp_w", "妇洗水温", "mdi:thermometer-water", None, None),
            ("water_strong_w", "妇洗水量", "mdi:water", None, None),
            ("water_pos_w", "妇洗位置", "mdi:arrow-expand-vertical", None, None),
            ("fan_temp", "烘干温度", "mdi:fan", None, None),
            ("net_rtt_ms", "网络延迟", "mdi:timer-outline", "ms", "measurement"),
            ("net_rtt_avg_ms", "网络平均延迟", "mdi:timer-sand", "ms", "measurement"),
            ("net_success_pct", "网络成功率", "mdi:percent-outline", "%", "measurement"),
            ("net_fail_streak", "网络连续失败", "mdi:alert-circle-outline", None, "measurement"),
            ("net_quality", "网络质量", "mdi:wifi", None, None),
        ]
        for key, name, icon, unit, state_class in sensors:
            cfg: dict[str, Any] = {
                **avail,
                "name": name,
                "unique_id": f"xjx_toilet_{self.slug}_{key}",
                "state_topic": state,
                "value_template": f"{{{{ value_json.{key} }}}}",
                "icon": icon,
            }
            if unit:
                cfg["unit_of_measurement"] = unit
            if state_class:
                cfg["state_class"] = state_class
            self._publish_json(self._disc("sensor", key), cfg, retain=True)

        switches = [
            ("seat_heat", "座圈加热", "mdi:heating-coil"),
            ("night_led", "夜灯", "mdi:lightbulb-night"),
            ("tun_wash", "臀洗", "mdi:shower"),
            ("women_wash", "妇洗", "mdi:shower"),
            ("warm_dry", "烘干", "mdi:hair-dryer-outline"),
            ("moving_t", "移动喷洗", "mdi:arrow-left-right"),
            ("massage_t", "按摩", "mdi:vibrate"),
        ]
        for key, name, icon in switches:
            cfg = {
                **avail,
                "name": name,
                "unique_id": f"xjx_toilet_{self.slug}_sw_{key}",
                "state_topic": state,
                "value_template": (
                    f"{{{{ 'ON' if value_json.{key} else 'OFF' }}}}"
                ),
                "payload_on": "ON",
                "payload_off": "OFF",
                "command_topic": f"{self.prefix}/{key}/set",
                "icon": icon,
            }
            self._publish_json(self._disc("switch", key), cfg, retain=True)

        numbers = [
            ("water_temp_t", "臀洗水温档", "mdi:thermometer-water"),
            ("water_strong_t", "臀洗水量档", "mdi:water-plus"),
            ("water_pos_t", "臀洗位置档", "mdi:arrow-expand-vertical"),
            ("water_temp_w", "妇洗水温档", "mdi:thermometer-water"),
            ("water_strong_w", "妇洗水量档", "mdi:water-plus"),
            ("water_pos_w", "妇洗位置档", "mdi:arrow-expand-vertical"),
            ("fan_temp", "烘干温度档", "mdi:fan"),
        ]
        for key, name, icon in numbers:
            cfg = {
                **avail,
                "name": name,
                "unique_id": f"xjx_toilet_{self.slug}_num_{key}",
                "state_topic": state,
                "value_template": f"{{{{ value_json.{key} }}}}",
                "command_topic": f"{self.prefix}/{key}/set",
                "min": 1,
                "max": 3,
                "step": 1,
                "mode": "slider",
                "icon": icon,
            }
            self._publish_json(self._disc("number", key), cfg, retain=True)

        buttons = [
            ("flush", "冲水", "mdi:toilet"),
            ("self_clean", "自洁", "mdi:shimmer"),
            ("air_filter", "防臭", "mdi:air-filter"),
            ("bubble_shield", "泡沫盾", "mdi:circle-outline"),
        ]
        for key, name, icon in buttons:
            cfg = {
                **avail,
                "name": name,
                "unique_id": f"xjx_toilet_{self.slug}_btn_{key}",
                "command_topic": f"{self.prefix}/{key}/set",
                "payload_press": "PRESS",
                "icon": icon,
            }
            self._publish_json(self._disc("button", key), cfg, retain=True)

        log.info("MQTT discovery published for %s", self.slug)
