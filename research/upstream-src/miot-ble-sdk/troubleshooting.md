# 排障决策树 —— 官方原版 App，无任何模块

> 前提：手机是国区小米账号，米家 App 为官方原版（未 root、未装任何模块），
> 设备固件由本 SDK 构建。**不适用**于"改 App 绕过"的场景，本仓库也不提供这类手段。

---

## Q1. 添加设备时红字「手机网络异常」/「设备绑定账号失败 (104,did=…)」

**不是网络问题。**

配网页三个步骤的含义：

| 步骤 | 走的通道 | 通过意味着 |
|---|---|---|
| 连接设备成功 | BLE GATT（本地） | 广播与 GATT 服务结构正确 |
| 普通认证成功 | BLE 本地认证 | 设备端协议实现正确 |
| 设备绑定账号失败 | **云端**（要联网） | App 拿 did 去云端查产品档案，查不到 |

米家把第 3 步的所有云端失败统一渲染成「手机网络异常」，真实原因在括号里。
服务端原始响应形如：

```json
{"code":-8,"message":"cant find did <did>","result":null}
```

### 为什么会查不到

本 SDK **不设置 did**。BLE 设备的 did 由云端在 REGISTER 阶段通过 92B 加密帧下发
（`docs/protocol.md` §7），固件解密后存 NVS 再回传。所以只可能是下面几种情况：

| 情况 | 判断方法 | 处理 |
|---|---|---|
| 固件自己填了 did | did 不是 `blt.3.*` 形态 | 删掉硬编码，did 只能由云端下发 |
| model/PID 与档案不符 | 特别是国区/海外 PID 混用 | 用档案里的真实 PID（温湿度计3 mini 国区 `0x55B5`，海外 `0x5BEA` 扫不到） |
| 92B 帧没解开 | 串口出现 `REGISTER: encrypted did decrypt FAIL` | 记录 App 版本 + 该行日志反馈；属版本差异 |
| 该 did 已被别的账号绑定 | 响应通常是"已绑定"类错误，不是 cant find did | 解绑或换设备 |

### 不要做

换网络、重启路由器、清 App 缓存、重装 App —— 前两步都过了，这些一律无效。

---

## Q2. App 扫不到设备

按顺序查：

1. **广播里有没有 PID**（温湿度计2 = `0x055B`，字节序 `5B 05`）。
   App 是靠 PID 匹配云端产品库来决定显示哪台设备的，没有 PID 就没有卡片。
2. **绑定前的 FC 是否是 `30 58`**：
   - `0x30` = MAC(0x10) + Capability(0x20)，未加密
   - `0x58` = version 5 + authMode 2（标准认证）+ registered 0
   写成加密形态（`0x58`）或漏掉 Capability，App 会当成"已绑定/不支持"而忽略。
3. **广播有没有带 MAC**：iOS 与部分安卓机型按帧内 MAC 做归属判定。
4. **长度**：`flags(3) + [len][0x16][95 FE](4) + 帧` 总计 ≤ 31B。
   串口若出现 `adv_set_fields rc=4`，就是超长（`4` = `BLE_HS_EMSGSIZE`）。
5. **GATT 服务是否注册了 `0xFE95`** 与 `0x0010/0x0019/0x001A`：扫到但连不上多半是这里。
6. **⭐ 这个 MAC 是不是已经在账号里绑过别的设备**（2026-11-14 实锤，最容易漏的一条）。
   米家「附近设备」按 **MAC 去重**：同一个 MAC 只要在账号里已经有一台设备（比如这颗芯片
   之前跑 `t3pro_adv` 绑成了温湿度计 3 Pro），列表会把它当成"那台已添加的设备"直接过滤，
   **扫多久都不会出现**，串口也看不到任何 CONNECT。
   判断方法：用手机 BLE 调试工具/`bleak` 扫一下，确认广播在、内容对，但 App 就是不列；
   把广播 MAC 和账号里已有设备的 MAC 对一下，撞了就是它。
   解法：像 `multi_dev` / `esp32/btn2_adv` / `esp32/scale_adv` 那样，在 `app_main` 最前面
   `esp_base_mac_addr_set()` 派生一个本项目专属基础 MAC（C3 的 BT MAC = 基础末字节 +2），
   并换一个 NVS 命名空间，重烧即可。

---

## Q3. 扫到了，一直「正在连接」然后超时

九成是 Q2 第 4 条的后果：`adv_set_fields` 失败后仍处于"广播已停止"状态。

正确做法：

- 帧超预算就拆帧（一个对象一帧），不要停广播；
- `set_fields` 失败时用最小帧头重建，**绝不能留在 stop 状态**；
- 加一个 5s 定时兜底：`!ble_gap_adv_active()` 就重新拉起。

---

## Q4. 绑定过程中 App 断开，串口无 device info

`device info sent (did=0B)` 这行没出现，或出现得很晚：

- `miot_auth_prepare()` 没调用，或放在了 `0x0015` 写回调里。
  ESP32-C3 生成 P-256 密钥对约 **390ms**，放在回调里会让 device info 迟到，
  App 以 `-51` 断开。必须在 `app_main` 里预生成。
- 检查 `miot_crypto_set_ops()` 是否在 `miot_auth_prepare()` 之前调用。

---

## Q5. 绑定成功，但设备页没有数值 / 数值不刷新

| 检查 | 期望 |
|---|---|
| 属性 siid/piid | 直接用 `thermometer_init()`，不要自造；温湿度计2 是双 spec 兼容（温度 float 2.1001 / 3.1001） |
| 是否 LOGIN 成功后再上报 | 串口要先有 `STD LOGIN COMPLETE`，否则 `send_props_changed` 返回 -1 |
| 上报后有没有 get 回读 | 串口出现 `spec req` 说明链路通 |
| 是否连了网关 | 走手机直连时只在设备页可见；网关首报要等一轮轮询 |

---

## Q6. 「未连接蓝牙网关」

环境侧问题，不是固件问题：插拔网关电源 + 重启米家 App，通常恢复。
多台设备都复现过（见 `docs/testing.md` 结果汇总表）。

---

## Q7. 断开重连后要求重新绑定 / 重启后设备丢了

`miot_auth_port_t` 的 `save` / `load` 没实现。把
`miot_auth_identity_t`（含 `did`、`token`、`bind_key`、`dev_key`）写进 NVS，
开机 `load` 回来即可。参考 [AGENTS.md](../AGENTS.md) S3.1。

---

## Q8. `LOGIN: app confirm MISMATCH`

`devConfirm` 的重发机制没生效。要求：首发延后 120ms，之后每 400ms 补发，最多 4 次
（`miot_auth_poll()` 每 50~100ms 调一次）。少发会让 App 偶尔收不到 `0x0C`，
15s 后按 notify timeout 断开。

---

## Q9. 想换别的设备档案

先看 [clean-app-matrix.md](clean-app-matrix.md)。有些型号走 legacy PSK 认证，
本 SDK 未实现 PSK，**官方原版 App 下绑不上**——这不是 bug，也不是靠调参能解决的。

---

## Q10. 重烧固件后「添加成功、详情页一直连接超时」

**先判断在哪一段**，三段的处置完全不同（串口 `STAT` 行是关键证据）：

| 现象 | 串口证据 | 根因 | 处置 |
|---|---|---|---|
| 米家扫不到 / 添加失败 | `bound=1`，mfg 帧 `30 29 dd03 …` | 已绑定态广播，而米家「添加」只认 `0x20` | 设备端串口 `factory` → `bound=0` 再扫 |
| 已添加，点详情页超时，`conn=0` 持续几分钟 | `STAT bound=1 login=0 conn=0 adv=1` | **Android 缓存了旧 GATT 服务表**；重烧后句柄全变，连接直接 `status 133` | **手机关蓝牙 → 等 5 秒 → 再开**，或重启手机 |
| 刚添加成功马上点详情页超时 | 45~139s 内零连接 | 正常真空期，App 停在「添加成功」页 | 退出页面等 2 分钟再进（`nightl2-ag2-handoff.md` §11.3） |

**设备侧自查**（排除固件问题最快的办法）：PC 上 `bleak` 直连目标 MAC，
能列出 `0xFE95` 全套特征、读到 `0x0004` 返回版本字符串，就说明固件与 GATT 表没问题，
锅在手机侧 —— 不要再去改固件参数。

```python
import asyncio
from bleak import BleakClient
async def main():
    async with BleakClient("10:00:3B:CE:70:03") as c:
        print(await c.read_gatt_char("00000004-0000-1000-8000-00805f9b34fb"))
asyncio.run(main())
```

> 另一个容易自己坑自己的点：ESP32-C3 走 USB-Serial-JTAG，**每次打开串口都会复位芯片**。
> 一边抓日志一边让手机连，连接会被复位打断，看起来就像「又超时了」。

---

## Q11. 添加设备时弹「-27」

**官方定义**（小米 IoT 平台《BLE 类产品开发常见问题》）：`-27 = Enable Notify 失败`，
常见原因是**扩展程序端判定的设备类型与固件端不一致** —— 例如 App/插件认为这是一台
「高安全设备」（要求安全芯片证书链），而固件做的是标准认证；Mesh 设备则表现为 App
去订阅 Mesh Proxy 通道的 notify，而固件只注册了 `0xFE95` 的 spec 特征。

**先看懂这个码的价值**：能弹 `-27` 说明三件事都成立 —— PID 被 App 认出来了、设备出现在
「附近设备」列表、GATT 连接也建立了。它比「扫不到」前进了一大步，**问题不在广播帧**。
配套的「扫不到」才查 PID/registered 位（见 Q2）。

**排查顺序**（成本从低到高）

| 步骤 | 做法 | 判据 |
|---|---|---|
| 1 | 米家里删掉同名旧设备 → 手机后台杀掉米家 → 清缓存 → 重进 | 官方 FAQ 第一条；旧绑定记录残留也会报 -27 |
| 2 | 换 PID 重烧（`pid 0xXXXX` + `erase-flash`） | 换到「标准认证 + BLE 直连」的档案才可能过 |
| 3 | 查该 PID 在米家的归属 | 灯具类里 `0x06EB`（MJDP09YL）/ `0x0926`（Yeelight Mesh Bulb M2）都是 **Mesh 插件**，要 Mesh 通道，spec 直连固件必 -27 |

**不要误判的点**：特征数量不是原因。`0x055B`（温湿度计2）、`0x03DD`（夜灯2）同为
`0010/0019/001A/001B` 四个特征，纯净 App 都能绑 —— 所以不要为了消 `-27` 去加
`0x0017/0x0018`，那是 Mesh 协议栈的入口，不是补个空特征就能骗过去的。

**2026-11-14 实例**：`esp32/bulb_gatt` 填 `0x06EB` 后米家报 `-27`。该 PID 对应
MJDP09YL —— 米家 Mesh 灯泡（插件 `yeelink.light.meshbulb1`，官方要求 Mesh 网关），
而本工程走的是 spec 直连，类型先天不匹配。结论：灯具要「真能绑」，目前只有
`0x03DD`（夜灯2）这条已验证的路。

**2026-11-14 22:06 logcat 实证**（`adb logcat`，米家 18799 进程）——`0x06EB` 的完整时间线：

```
22:06:54.332  BluetoothGattServer  连接建立（device …71:05）
22:06:54.648  BluetoothGatt        discoverServices()
22:06:54.829  BluetoothGatt        onSearchComplete() status=0      ← GATT 表读到了
22:06:54.917  BluetoothGatt        cancelOpen()
22:06:54.925  BluetoothGatt        onClientConnectionState connected=false
22:06:54.926  BluetoothGatt        refresh()                        ← App 还主动刷了缓存
```

**593ms 内零次 `setCharacteristicNotification` / `writeDescriptor` / `writeCharacteristic`。**
服务发现一成功就主动断开——这不是「订阅失败」，是 App 拿到 GATT 表后判定
「这台不是我认识的设备类型」，直接放弃，再把结果映射成 `-27`。

三个推论：
1. 固件的 notify 注册**没问题**（压根没走到订阅那一步），别再去改 CCCD。
2. Android GATT 缓存也**不是**原因（App 自己调了 `refresh()`）。
3. PID 就是原因本身：`0x06EB` 在米家产品库里是 Mesh 灯泡，App 期望的是 Mesh 通道。

**判据表**（下次直接用）：

| 现象 | 含义 |
|---|---|
| 列表里根本没有 | PID 错 / registered 位不对 / 扫描过滤 |
| 连上很快就断，无任何 write | **PID 类型不匹配**（本例，-27） |
| 有 `setCharacteristicNotification` 后失败 | 特征/CCCD 注册问题 |
| 写了 `0xA2` 但无 `0x11` 回应 | 认证链路问题（查 nonce/时间戳） |

### Q11 附：挂上 Mesh 栈之后仍然 `-27`（2026-11-14 22:28 复核）

把 `multi_dev` 的米家 Mesh 承载（NimBLE Mesh + 6 个移植补丁 + vendor model `0x038f0000`）
整段搬到 `bulb_gatt`，让设备真的同时具备 spec 通道和 SIG Mesh 配网通道，再添加一次：

```bash
串口：MIOT-MESH: bt_mesh_init OK  elems=1  models=cfg+health+vnd
      MIOT-MESH: prov_enable rc=0     （PB-ADV/PB-GATT beacon 已开）
GATT：0000fe95  0010/0019/001A/001B
      00001827  Mesh Provisioning  2adb(Data In) / 2adc(Data Out + CCCD)
```

App 侧（米家 18799）时间线 —— **与没有 Mesh 栈时逐毫秒同构**：

```
22:28:07.372  discoverServices()
22:28:07.648  onSearchComplete() status=0     ← 上面那张表它全拿到了
22:28:07.742  cancelOpen()                    ← 94ms 后放弃
22:28:07.752  断开 + unregisterApp
22:28:07.760  refresh() + close()
```

**零次** `setCharacteristicNotification` / `writeDescriptor` / `writeCharacteristic` ——
连 PB-GATT 的 `2adb` 都没碰过。所以：

- 0x1827 / 2ADB / 2ADC 齐备也**不改变结论**，Mesh 通道不是缺的东西；
- 拒绝点在 **PID → 插件类型** 这一层（App 扫描阶段就知道 PID，连接只是复核），
  任何 GATT 侧增删都不会让 `-27` 消失；
- 结论：MJDP003 想绑上，只能拿到**真机真 PID** 并确认它到底走哪种承载；
  用 MJDP09YL 的 pdid 顶替是死路。本次试验的代码已回滚，`bulb_gatt` 回到纯 spec 形态。

**副作用留档**：Mesh 栈注册 GATT 服务必须在 host 启动（`ble_gatts_start`）之前完成，
晚了 PB-GATT 的 handle 解析会断言崩溃；Mesh 起来后 `bt_le_adv_start` 会抢广播实例，
MiBeacon 必须让位给 mesh beacon，否则设备在空中消失。这两条在 `multi_dev` 里已有实现。
---

## Q12. 添加设备时弹「-28」（2026-11-15，pir2s_adv 实例）

**官方定义**（小米 IoT 平台《BLE 类产品开发常见问题》+ 配网错误码表）：
`-28 = 数据传输过程中，数据发送失败`。官方点名的场景：**有按键的「设备确认配对」蓝牙设备**
—— 手机与设备刚直连上时，设备没有处于确认配对状态：**直连后 1~2s 内广播必须继续保持
「请求被连接」形态**（官方 SDK 里对应 `miio_ble_user_adv_init(1)`），如果连上后广播形态
变了（官方例子是切到 `miio_ble_user_adv_init(0)`）就报 -28。

**为什么 pir2s 中招而 motion_adv 不会**：两者固件骨架相同（连上即 `ble_gap_adv_stop()`），
差别在云端产品档案 —— pir1（人体传感器2S，真机有确认按键）配的是「设备确认即配对」流程，
App 在 GATT 直连后还要**盯 1~2s 广播来确认设备处于配对态**；0x0A8D（老人体传感器2）走
标准流程没这一步。所以「连上就停播」的骨架对 pir1 必 -28，对其余广播型 PID 无感。

**修复**（esp32/pir2s_adv，2026-11-15）：
1. `BLE_GAP_EVENT_CONNECT` 不再停播，重建同内容帧后切 **非连接 beacon** 继续广播
   （NimBLE MAX_CONNECTIONS=1 发不了可连接广播，NON 形态正是真机连接期间的行为）；
2. `adv_start()` 连接态强制 `BLE_GAP_CONN_MODE_NON`，未绑定态保持快间隔（160/320）；
3. `BLE_GAP_EVENT_DISCONNECT` 改 `adv_refresh()`（stop/start 换回可连接形态）。

**判别表**（与 -27 对照）：

| 码 | 阶段 | 含义 | 查哪里 |
|---|---|---|---|
| -27 | 连接后订阅前 | PID → 插件类型不匹配（读完服务表零写入即断） | 换 PID / 确认承载类型 |
| -28 | 直连后数据阶段 | 连接后广播形态变了 / 停播，App 确认不了配对态 | 连接期间保持同形态广播 |

**不要误判的点**：-28 不是认证失败（那类报 -31/-51/-52），也不用动 ECDH/密钥链路；
也和绑定身份残留无关（长按擦 NVS 没用）。抓包特征是：GATT 握手正常走、设备侧看到
连接事件，App 在直连后 1~2s 内断开并报 -28 —— 对应设备串口里「手机连上来了」之后
紧接 DISCONNECT，没有任何 spec 写入。

---

## Q13. 添加设备时弹「-55」（2026-11-15，occ_adv / pir2s_adv 实例）

**官方定义**：`-55 = 普通蓝牙设备绑定时 notify 超时` —— App 发完注册命令（`0x0010` 上写
`A2`）后，等设备在 `0x0019` 上 notify 的 **device info**，等不到就 16s 超时断开报 -55。

**实测现场（occ_adv，串口日志）**：

```
wr 0010 #1 cmd=A2 → notify h=19 len=8 ok（device info，连发 4 次含 150ms 重发兜底）
... 16.0s 零响应 ...
App 订阅 0x0010/0x0019 关闭 → disconnected reason=0x213
```

设备侧 `ble_gatts_notify_custom` 全部返回 0、帧长 8B 远小于 MTU-3，**固件这头没有任何问题**；
是手机侧这一轮会话完全不消费通知。判据：**只要设备侧出现 `notify h=19 len=8 ok` 而 App 无
后续 `cmd=15`，就是 App 侧卡住，不是固件**。

**处理**：米家 App **多任务里彻底杀掉后台** → 重进 → 重试一次。 pir2s / occ 两台都是
「首次或连续失败一次 → 杀后台 → 一次过」。原因推测为 App 在上一轮 -28/cancelOpen 之后
残留了 bind 会话状态机。

**固件侧顺带加的兜底**（2026-11-15，`src/miot_auth.c`）：注册阶段 device info 在 150ms 后
自动重发（最多 3 次，间隔 400ms），并在 `gatt_miot.c` 里给 ≤24B 的小帧打 `notify ... ok`
日志，便于一眼区分「没发出去」和「发了 App 不收」。

**错误码族对照（同一阶段）**：

| 码 | 现象（设备侧串口） | 含义 | 动作 |
|---|---|---|---|
| -27 | 读完服务表，零写入即断 | PID 类型不匹配 | 换 PID / 确认承载类型 |
| -28 | GATT 正常走，直连后 1~2s 断开 | 连接期间广播形态变了（确认配对类产品） | 保持请求配对广播（Q12） |
| -55 | `A2` 后设备连发 device info，App 16s 无反应 | App 侧会话卡住 | 杀 App 后台重试（Q13） |

---

## Q14. 电量 / 属性一直「--」，但设备在线、其它属性正常（2026-11-17，door3_adv 实例）

**现象**：门窗传感器3（`0x8C05`）绑定成功、开合状态实时变化，唯独**电量恒为 `--`**。
云端实时读 `3:1107` 返回 `null`（错误码 `-704220043`「属性未激活」）。

**根因：载荷类型与 spec 不匹配 —— 比对象号错更隐蔽。**

门3 的电量 spec 是 **枚举**，不是百分比：

```
battery-level  3.1107  format:uint8  value_list:[{0:Fully 充足},{1:Low 不足}]
```

一开始照门窗2 的习惯发百分比 `95`（对象号 0x4C6B 其实是对的），网关**整帧丢弃** ——
帧长度、CRC、加密全部正常，串口看「发出去了」，但网关解析枚举时越界就把整帧不要，
云端永远是 `null`。改发 `0` 或 `1` 立即通。

**判据（云端实时 prop 读，不碰手机）**：

```
miot_device_status_read(did, prop="3:1107")   # 门3 电量
  → value=null code=-704220043   # 对象号或类型不对
  → value=0     code=0           # 通了（0=Fully）
```

错误码速查：`-704010000`=属性存在但无值（广播没上报到）／`-704040003`=属性不存在（spec 无此 piid）／
`-704220043`=属性未激活（**对象号或载荷类型不对**）。

**排查顺序**（从便宜到贵）：

1. 先确认**载荷类型**对不对（`miot_get_device_spec` 看 `format` 和 `value_list`）——
   枚举发枚举值、百分比发百分比、bool 发 0/1。
2. 再确认**对象号**：新式 spec 用公式 `0x4000|(siid<<10)|(piid-1000)`，别照抄老型号的标准号。
3. 两个都对还不通 → 用串口 `obj`/`batt`/`bval` 命令盲测候选（一次连接遍历，比反复烧录快）。

**注意**：部分设备电量走标准对象 `0x100A`（pir2s 实测），部分走公式（门3 是 `0x4C6B`）——
不是统一规律，以实测为准。但**类型错优先于对象号错**先排查。
