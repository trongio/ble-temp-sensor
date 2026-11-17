| 文档状态 | 更新时间 |
|---|---|
| 进行中 | 2026-07-14 |

# Mesh Registration Probe

## 安全边界

- 仅发送 `MESH_REG_START = 40 00 00 00`。
- 不发送证书、签名、LTMK、NetKey、AppKey、地址或确认绑定指令。
- 不写 NVS。
- 记录订阅状态、原始响应、写状态、会话时长和断开原因。

## 判定

| 结果 | 解释 | 下一步 |
|---|---|---|
| 返回 `0x40` 系列状态或证书流 | 私有入口确认 | 实现帧分类器并还原下一交换 |
| 返回 `ERR_INVALID_OOB (0xE3)` | 缺 OOB/云材料 | 抓米家 App 同阶段输入 |
| 主动 `0x13` 断开且无响应 | 入口格式、设备窗口或前置握手仍不匹配 | 对比真实 App 抓包，不再猜后续密钥帧 |

## 2026-07-14 实测记录

- 探针固件已成功构建并刷入 ESP32-S3，仅更新 application 分区。
- 启动自检通过：MiBLE crypto、BLE observer、Wi-Fi 与 HTTP API 均正常；设备地址为 `192.168.1.2`。
- 连续执行 3 次、每次 10 秒扫描；扫描均成功并发现其他 BLE 设备，但 PID `0x612c` 的目标香薰机未广播，`xiaomi_count=0`、`diffuser_found=false`。
- 因目标不可达，本轮没有发送 `40 00 00 00`，没有建立 GATT 会话，也没有改变香薰机或 ESP32 NVS 状态。
- 继续条件：让香薰机进入待配网/广播状态后，再调用 `GET /api/ble/gatt?target=diffuser&hold=1&mesh_register_probe=1`。
- ESP32 重启后再次确认 Wi-Fi 地址 `192.168.1.2`、HTTP 与 BLE 扫描正常；守护脚本以 5 秒扫描窗口实跑 7 轮，均为 `found=False`，门控正确且没有触发 GATT 写入。
- 第三轮目标可达性审计再次执行 10 秒 `stop_on_solicited=1` 扫描，结果仍为 `diffuser_found=false`、`diffuser_solicited=false`；设备侧实验因此暂停，等待物理设备进入配网广播状态。

为避免错过短暂的 `solicited=1` 窗口，可运行一次性守护脚本：

```bash
FLUXTERM_PASSWORD='...' python3 -B tools/wait_for_mesh_registration_probe.py
```

脚本只在 PID `0x612c` 且 `solicited=1` 时调用一次 Mesh 探针；结果写入外置盘
`/Volumes/Mac/Code/.tmp/xiaomi-mesh-probe`，成功、超时或探针失败后都会退出。
