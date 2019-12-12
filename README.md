# websocks

基于隧道与拟态流量混淆的匿名通信系统

## 协议设计

TCP 部分实现了[使用 Websocket 进行网络穿透(续)](https://abersheeran.com/articles/Fuck-GFW-WebSocket-/)中的设计。

UDP 部分正在设计中……

## 将要做的

客户端：

- [ ] 支持流量、网速、延迟等统计数据

- [ ] web 端界面用于管理客户端与服务器

服务端：

- [ ] 支持多用户. 支持流量统计.

- [ ] 提供 websocket 接口用于管理
