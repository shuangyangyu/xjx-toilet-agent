# xjx-toilet-agent

独立 Docker 服务：本地 miIO **双速轮询**小鲸洗马桶，经 MQTT Discovery 接入 Home Assistant。

协议与指令来自 [xiaomi_miio_toilet](https://github.com/shuangyangyu/xiaomi_miio_toilet)。本服务把轮询从 HA Core 里拆出来，避免 UDP 超时拖累 HA。

## 为什么独立

| | HA 集成 `xjx_toilet` | 本 Agent |
|--|--|--|
| 着坐延迟 | 默认整轮 ~30s | 默认 **5s** 只问 `seating` |
| 其它状态 | 同间隔 | **30s** 全量/轮流读 |
| 故障隔离 | 在 HA 进程内 | 容器可单独重启 |
| 控制 | Config Entry | MQTT switch / number / button |

> 马桶仍是问答式 miIO，**不能主动推送**。Agent 只是轮询策略更合理。

## 架构

```text
马桶 192.168.1.34  --miIO UDP-->  xjx-toilet-agent (241)
                                      |
                                   MQTT
                                      v
                              HA 192.168.1.249
                         (MQTT Discovery 自动出实体)
```

建议部署在 **241**（`network_mode: host`，与马桶同网段）。  
上线后建议在 HA **禁用/删除** 原 `xjx_toilet` 集成，避免双轮询抢设备。

## 快速开始

```bash
cd hass/xjx-toilet-agent
cp agent/.env.example agent/.env
# 填 TOILET_TOKEN、MQTT_PASSWORD

docker compose up -d --build
docker compose logs -f
```

本地一次性探测（不跑 MQTT）：

```bash
cd agent
cp .env.example .env   # 填 token
PYTHONPATH=src python -m xjx_toilet_agent status
```

## 环境变量

见 [`agent/.env.example`](./agent/.env.example)。关键项：

| 变量 | 默认 | 说明 |
|------|------|------|
| `TOILET_HOST` | `192.168.1.34` | 马桶 IP |
| `TOILET_TOKEN` | （必填） | 32 hex，从原 HA 集成 / 米家扫码 |
| `SEATING_INTERVAL_SEC` | `5` | 着坐轮询间隔 |
| `FULL_INTERVAL_SEC` | `30` | 全量状态间隔 |
| `MQTT_HOST` | `192.168.1.249` | HA Mosquitto |

## HA 实体

MQTT Discovery 前缀设备名默认「小鲸洗马桶」，包括：

- **binary_sensor**：着坐、臀洗/妇洗/烘干进行中  
- **switch**：座圈加热、夜灯、臀洗、妇洗、烘干、移动喷洗、按摩  
- **number**：水温/水量/位置/烘干温度（1–3 档）  
- **button**：冲水、自洁、防臭、泡沫盾  
- **sensor**：各档位只读镜像  

状态 topic：`xjx/toilet/state`（JSON）。  
控制：`xjx/toilet/<entity>/set`。

清洗类开关未着坐时会拒绝启动（设备安全锁）。

## 网络质量

每次着坐轮询会统计 miIO RTT，并在 HA 上暴露：

| 实体 | 含义 |
|------|------|
| 网络质量 | `excellent` / `good` / `fair` / `poor` / `offline` |
| 网络延迟 | 最近一次成功着坐轮询 RTT（ms） |
| 网络平均延迟 | 近 60 次成功轮询平均 RTT |
| 网络成功率 | 近 60 次轮询成功百分比 |
| 网络连续失败 | 当前连续失败次数（≥5 判 offline） |

评级大致：成功率≥95% 且延迟≤600ms → excellent；再差依次 good / fair / poor。

## 目录

```text
xjx-toilet-agent/
├── docker-compose.yml
├── agent/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example
│   └── src/xjx_toilet_agent/
└── README.md
```
