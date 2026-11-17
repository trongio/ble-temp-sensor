| 文档状态 | 更新时间 | 范围 |
|---|---|---|
| 进行中 | 2026-07-14 | 小米 BLE Mesh 私有首次入网 |

# 小米 BLE Mesh 网关调研

**[HWPR]** 目标与判断
> 我们要让自己的 ESP32 成为小米 BLE Mesh Provisioner/网关，而不是依赖米家网关完成首次配网。目前判断 HomePod 只适合作为 HomeKit 家庭中枢，私有 Mesh Provision 和无线控制应放在 ESP32 上。协议未知时优先做不写密钥、可证伪的探针。

**[AWOR]** 已验证事实

- 目标设备为 `xiaomi.diffuser.02wh`，PID `24876 (0x612c)`，MiBeacon 标志为 `mesh=true`、`registered=false`、`auth_mode=1`。
- 广播只包含小米 Service Data `0xFE95`，没有标准 Unprovisioned Device Beacon。
- GATT 服务只有 `0x1800`、`0x1801`、`0xFE95`、`0xA00A`，没有标准 Mesh Provisioning Service `0x1827`。
- 传统 MiBLE 注册入口 `0xA2` 与 Mesh 登录入口 `0x50` 均不能完成未绑定设备的首次 Mesh 注册。
- Telink 官方公开 SDK 把该流程称为 `mesh_auth` / “私有 mesh 设备绑定流程”。公开头文件定义 `MESH_REG_START=0x40`，并列出服务端/设备端证书、公钥和签名校验结果；真正实现未以源码发布。

## 关键发现

| 维度 | 发现 | 对我们的启示 |
|---|---|---|
| 商业实现 | 米家 App/小爱网关实现私有注册 | 只把官方网关当协议 oracle，不作为最终依赖 |
| 开源实现 | ESP-IDF 提供标准 Provisioner；Telink SDK 暴露小米节点侧接口但隐藏 `mesh_auth` 实现 | 复用 ESP-IDF 的标准 Mesh 网络层，自行补 GATT 私有认证前置层 |
| 技术演进 | 标准 Mesh 使用 PB-ADV/PB-GATT；目标设备在未绑定阶段不暴露这些入口 | 第一个实验必须走 `0xFE95` 的 Mesh 注册 opcode，而不是 PB-GATT |
| 用户体验 | 目标是无需额外米家网关即可加入 Apple Home | ESP32 最终需同时承担 Provisioner、Proxy/控制器和 HomeKit/Matter 桥接 |
| 安全与合规 | 注册交换证书、ECDH/ECDSA，并产生长期密钥和 Mesh 密钥 | 探针不得记录私钥/LTMK/NetKey/AppKey；正式存储需加密 NVS |

## 对我们的启示

下一次最小实验是订阅 MiBLE `0x0010/0x0016` 后，仅向 prepare 特征写入四字节小端 `0x40` (`40 00 00 00`) 并停止。若设备返回能力或证书流，确认私有 Mesh 注册入口；若直接返回 `ERR_REGISTERED/ERR_INVALID_OOB` 或断开，则根据原始响应更新假设。该实验不发送网络密钥，不会完成或持久化绑定。

## 来源

- Telink `tc_ble_mesh` 官方公开 SDK（本机只读副本：`/Volumes/Mac/AI_Cache/source/tc_ble_mesh`）
- ESP-IDF ESP-BLE-MESH Provisioner 文档
- Bluetooth Mesh Protocol Specification
- 当前设备的扫描与 GATT 记录：`/Volumes/Mac/tmp/diffuser_scan_current.json`、`/Volumes/Mac/tmp/diffuser_gatt_current.json`
