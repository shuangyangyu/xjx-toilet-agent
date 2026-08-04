"""Local miIO client for xjx.toilet.*."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from miio import Device, DeviceException

log = logging.getLogger(__name__)
logging.getLogger("miio.miioprotocol").setLevel(logging.CRITICAL)

PROP_SEATING = "seating"
PROP_SEAT_TEMP = "seat_temp"
PROP_STATUS_SEATHEAT = "status_seatheat"
PROP_STATUS_LED = "status_led"
PROP_AUTO_LED = "auto_led"
PROP_STATUS_TUNWASH = "status_tunwash"
PROP_STATUS_WOMENWASH = "status_womenwash"
PROP_STATUS_WARMDRY = "status_warmdry"

METHOD_FLUSH_ON = "flush_on"
METHOD_WORK_SEATHEAT = "work_seatheat"
METHOD_SEND_SEAT_HEAT = "send_seat_heat"
METHOD_WORK_NIGHT_LED = "work_night_led"
METHOD_SET_AUTO_LED = "set_auto_led"
METHOD_WORK_TUN_WASH = "work_tun_wash"
METHOD_WORK_WOMEN_WASH = "work_women_wash"
METHOD_WORK_WARM_DRY = "work_warm_dry"
METHOD_SELF_CLEAN_ON = "self_clean_on"
METHOD_AIR_FILTER_ON = "air_filter_on"
METHOD_BUBBLE_SHIELD_ON = "bubble_shield_on"
METHOD_SET_MOVING = "set_moving"
METHOD_SET_MASSAGE = "set_massage"
METHOD_SET_WATER_TEMP_T = "set_water_temp_t"
METHOD_SET_WATER_STRONG_T = "set_water_strong_t"
METHOD_SET_WATER_POS_T = "set_water_pos_t"
METHOD_SET_WATER_TEMP_W = "set_water_temp_w"
METHOD_SET_WATER_STRONG_W = "set_water_strong_w"
METHOD_SET_WATER_POS_W = "set_water_pos_w"
METHOD_SET_FAN_TEMP = "set_fan_temp"
METHOD_SEND_WATER_TEMP_T = "send_water_temp_t"
METHOD_SEND_WATER_STRONG_T = "send_water_strong_t"
METHOD_SEND_WATER_POS_T = "send_water_pos_t"
METHOD_SEND_MOVING_T = "send_moving_t"
METHOD_SEND_MASSAGE_T = "send_massage_t"
METHOD_SEND_WATER_TEMP_W = "send_water_temp_w"
METHOD_SEND_WATER_STRONG_W = "send_water_strong_w"
METHOD_SEND_WATER_POS_W = "send_water_pos_w"
METHOD_SEND_MOVING_W = "send_moving_w"
METHOD_SEND_MASSAGE_W = "send_massage_w"
METHOD_SEND_WARM_DRY = "send_warm_dry"


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, list):
        if not value:
            return default
        value = value[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _parse_wash(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, list) or len(raw) < 6:
        return {
            "running": False,
            "water_temp": None,
            "water_strong": None,
            "water_pos": None,
            "moving": False,
            "massage": False,
        }
    return {
        "running": _as_int(raw[0]) == 1,
        "water_temp": _as_int(raw[1]),
        "water_strong": _as_int(raw[2]),
        "water_pos": _as_int(raw[3]),
        "moving": _as_int(raw[4]) == 1,
        "massage": _as_int(raw[5]) != 0,
    }


def _parse_dry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, list) or len(raw) < 2:
        return {"running": False, "fan_temp": None}
    return {"running": _as_int(raw[0]) == 1, "fan_temp": _as_int(raw[1])}


@dataclass
class ToiletState:
    """Normalized toilet snapshot for MQTT."""

    online: bool = False
    seating: bool = False
    seat_temp: int | None = None
    seat_heat: bool = False
    night_led: bool = False
    auto_led: int | None = None
    tun_wash: bool = False
    women_wash: bool = False
    warm_dry: bool = False
    water_temp_t: int | None = None
    water_strong_t: int | None = None
    water_pos_t: int | None = None
    moving_t: bool = False
    massage_t: bool = False
    water_temp_w: int | None = None
    water_strong_w: int | None = None
    water_pos_w: int | None = None
    moving_w: bool = False
    massage_w: bool = False
    fan_temp: int | None = None
    updated_at: float = field(default_factory=time.time)

    def to_mqtt(self) -> dict[str, Any]:
        data = asdict(self)
        data["updated_at"] = int(self.updated_at)
        return data


class ToiletClient:
    """Poll / command XiaoJingXi toilet over miIO."""

    def __init__(self, host: str, token: str, *, timeout: float = 8.0, poll_gap: float = 0.35):
        self.device = Device(host, token, timeout=timeout)
        self.poll_gap = poll_gap
        self._fail_streak = 0
        self._wash_rotate = 0
        self.state = ToiletState()

    def _sleep(self) -> None:
        time.sleep(self.poll_gap)

    def _get_one(self, prop: str) -> Any | None:
        try:
            raw = self.device.get_properties([prop])
        except DeviceException as err:
            log.debug("prop %s failed: %s", prop, err)
            return None
        if not isinstance(raw, list) or not raw:
            return None
        return raw[0]

    def send(self, method: str, params: list[Any] | None = None) -> None:
        params = params or []
        try:
            result = self.device.send(method, params)
        except DeviceException as err:
            raise RuntimeError(f"指令失败: {method}: {err}") from err
        if result == "error" or result == ["error"]:
            raise RuntimeError(f"设备拒绝指令: {method}")

    def poll_seating(self) -> ToiletState:
        """Fast path: only seating."""
        seating = self._get_one(PROP_SEATING)
        if seating is None:
            self._fail_streak += 1
            if self._fail_streak >= 5:
                self.state.online = False
            self.state.updated_at = time.time()
            return self.state

        self._fail_streak = 0
        self.state.online = True
        self.state.seating = _as_int(seating) == 1
        self.state.updated_at = time.time()
        return self.state

    def poll_full(self) -> ToiletState:
        """Slower path: seating + other properties (rotated wash vector)."""
        seating = self._get_one(PROP_SEATING)
        if seating is None:
            self._fail_streak += 1
            if self._fail_streak >= 5:
                self.state.online = False
            self.state.updated_at = time.time()
            return self.state

        self._fail_streak = 0
        self.state.online = True
        self.state.seating = _as_int(seating) == 1

        self._sleep()
        seat_temp = self._get_one(PROP_SEAT_TEMP)
        if seat_temp is not None:
            self.state.seat_temp = _as_int(_scalar(seat_temp))

        self._sleep()
        seatheat = self._get_one(PROP_STATUS_SEATHEAT)
        if seatheat is not None:
            self.state.seat_heat = _as_int(seatheat) == 1

        self._sleep()
        led = self._get_one(PROP_STATUS_LED)
        if led is not None:
            self.state.night_led = _as_int(led) == 1

        self._sleep()
        auto_led = self._get_one(PROP_AUTO_LED)
        if auto_led is not None:
            self.state.auto_led = _as_int(auto_led)

        wash_props = (PROP_STATUS_TUNWASH, PROP_STATUS_WOMENWASH, PROP_STATUS_WARMDRY)
        prop = wash_props[self._wash_rotate % len(wash_props)]
        self._wash_rotate += 1
        self._sleep()
        value = self._get_one(prop)
        if value is not None:
            if prop == PROP_STATUS_TUNWASH:
                tun = _parse_wash(value)
                self.state.tun_wash = tun["running"]
                self.state.water_temp_t = tun["water_temp"]
                self.state.water_strong_t = tun["water_strong"]
                self.state.water_pos_t = tun["water_pos"]
                self.state.moving_t = tun["moving"]
                self.state.massage_t = tun["massage"]
            elif prop == PROP_STATUS_WOMENWASH:
                women = _parse_wash(value)
                self.state.women_wash = women["running"]
                self.state.water_temp_w = women["water_temp"]
                self.state.water_strong_w = women["water_strong"]
                self.state.water_pos_w = women["water_pos"]
                self.state.moving_w = women["moving"]
                self.state.massage_w = women["massage"]
            else:
                dry = _parse_dry(value)
                self.state.warm_dry = dry["running"]
                self.state.fan_temp = dry["fan_temp"]

        self.state.updated_at = time.time()
        return self.state

    def require_seating(self) -> None:
        if not self.state.seating:
            raise RuntimeError("请先着坐后再启动清洗或烘干")

    def set_seat_heat(self, on: bool) -> None:
        if on:
            self.send(METHOD_WORK_SEATHEAT, [1])
            self.send(METHOD_SEND_SEAT_HEAT, [1])
        else:
            self.send(METHOD_WORK_SEATHEAT, [0])
        self.state.seat_heat = on

    def set_night_led(self, on: bool) -> None:
        if not on:
            try:
                self.send(METHOD_SET_AUTO_LED, [0])
            except RuntimeError:
                log.debug("set_auto_led skipped")
        self.send(METHOD_WORK_NIGHT_LED, [1 if on else 0])
        self.state.night_led = on

    def set_tun_wash(self, on: bool) -> None:
        if on:
            self.require_seating()
            self.send(METHOD_WORK_TUN_WASH, [1])
            self._send_tun_params()
        else:
            self.send(METHOD_WORK_TUN_WASH, [0])
        self.state.tun_wash = on

    def set_women_wash(self, on: bool) -> None:
        if on:
            self.require_seating()
            self.send(METHOD_WORK_WOMEN_WASH, [1])
            self._send_women_params()
        else:
            self.send(METHOD_WORK_WOMEN_WASH, [0])
        self.state.women_wash = on

    def set_warm_dry(self, on: bool) -> None:
        if on:
            self.require_seating()
            fan = self.state.fan_temp or 2
            self.send(METHOD_SEND_WARM_DRY, [fan])
            self.send(METHOD_WORK_WARM_DRY, [1])
        else:
            self.send(METHOD_WORK_WARM_DRY, [0])
        self.state.warm_dry = on

    def set_moving(self, on: bool) -> None:
        self.send(METHOD_SET_MOVING, [1 if on else 0])
        self.state.moving_t = on
        self.state.moving_w = on

    def set_massage(self, on: bool) -> None:
        self.send(METHOD_SET_MASSAGE, [1 if on else 0])
        self.state.massage_t = on
        self.state.massage_w = on

    def set_level(self, kind: str, level: int) -> None:
        level = max(1, min(3, int(level)))
        mapping = {
            "water_temp_t": METHOD_SET_WATER_TEMP_T,
            "water_strong_t": METHOD_SET_WATER_STRONG_T,
            "water_pos_t": METHOD_SET_WATER_POS_T,
            "water_temp_w": METHOD_SET_WATER_TEMP_W,
            "water_strong_w": METHOD_SET_WATER_STRONG_W,
            "water_pos_w": METHOD_SET_WATER_POS_W,
            "fan_temp": METHOD_SET_FAN_TEMP,
        }
        method = mapping.get(kind)
        if not method:
            raise RuntimeError(f"未知档位: {kind}")
        self.send(method, [level])
        setattr(self.state, kind, level)

    def flush(self) -> None:
        self.send(METHOD_FLUSH_ON, [])

    def self_clean(self) -> None:
        self.send(METHOD_SELF_CLEAN_ON, [])

    def air_filter(self) -> None:
        self.send(METHOD_AIR_FILTER_ON, [])

    def bubble_shield(self) -> None:
        self.send(METHOD_BUBBLE_SHIELD_ON, [])

    def _send_tun_params(self) -> None:
        pairs = (
            (METHOD_SEND_WATER_STRONG_T, self.state.water_strong_t),
            (METHOD_SEND_WATER_TEMP_T, self.state.water_temp_t),
            (METHOD_SEND_MASSAGE_T, 1 if self.state.massage_t else 0),
            (METHOD_SEND_MOVING_T, 1 if self.state.moving_t else 0),
            (METHOD_SEND_WATER_POS_T, self.state.water_pos_t),
        )
        for method, value in pairs:
            if value is None:
                continue
            try:
                self.send(method, [value])
            except RuntimeError:
                log.debug("skip optional %s", method)

    def _send_women_params(self) -> None:
        pairs = (
            (METHOD_SEND_WATER_STRONG_W, self.state.water_strong_w),
            (METHOD_SEND_WATER_TEMP_W, self.state.water_temp_w),
            (METHOD_SEND_MASSAGE_W, 1 if self.state.massage_w else 0),
            (METHOD_SEND_MOVING_W, 1 if self.state.moving_w else 0),
            (METHOD_SEND_WATER_POS_W, self.state.water_pos_w),
        )
        for method, value in pairs:
            if value is None:
                continue
            try:
                self.send(method, [value])
            except RuntimeError:
                log.debug("skip optional %s", method)
