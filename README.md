# websocks

通过 websocket 转发本地 http 代理服务器接收到的 TCP 数据。

## 协议设计

实现了[使用 Websocket 进行网络穿透(续)](https://abersheeran.com/articles/Fuck-GFW-WebSocket-/)中的设计。

## 使用说明

websocks 分两个部分： `client` 与 `server`。

首先需要使用 `pipenv install` 安装好 websocks 所需的依赖。

在项目根目录创建 `.env` 文件，在其中配置环境变量：

* WEBSOCKS_USER： 用户名

* WEBSOCKS_PASS： 密码

* WEBSOCKS_SERVER： 服务器地址

其中，服务器地址应为 `wss://your-domain` 形式。

然后可以使用启动命令：

- 启动服务端使用： `pipenv run python -m websocks.server`

- 启动客户端使用： `pipenv run python -m websocks.client`

在启动服务端后，应使用 nginx 等反向代理服务器进行反向代理，并配置 SSL 证书。如果能够配置 CDN 代理 websocket 连接，那是最好的。

在启动客户端后，可使用 [proxifier](https://www.proxifier.com/) 等工具将本地 TCP 走 websocks 的代理。**websocks 并不会愚蠢的把你所有数据流量都通过远程服务器发送，所以尽可放心。**

### 通过 docker 启动

如果你的PC/服务器上没有安装 Python3.6+，并且你并不想安装，那么可以使用 docker 去启动 websocks。

以下分别为服务端和客户端的 `docker-compose.yml` 样例。

```python
version: '3.3'
services:
  websocks:
    image: abersheeran/websocks
    command: python3 -m websocks.server
    environment:
      WEBSOCKS_USER: your username
      WEBSOCKS_PASS: your password
    ports:
      - "8765:8765"
    restart: always
```

```python
version: '3.3'
services:
  websocks:
    image: abersheeran/websocks
    command: python3 -m websocks.client
    environment:
      WEBSOCKS_USER: your username
      WEBSOCKS_PASS: your password
      WEBSOCKS_SERVER: wss://your-server
    ports:
      - "3128:3128"
    restart: always
```

## 将要做的

- [ ] 集成 [GFWList](https://github.com/gfwlist)，更快的分辨是否代理

- [ ] 支持多用户名. 支持流量统计.
