# websocks

通过 websocket 转发本地 socks5 代理服务器接收到的 TCP 数据。

## 协议设计

实现了[使用 Websocket 进行网络穿透(续)](https://abersheeran.com/articles/Fuck-GFW-WebSocket-/)中的设计。

## 使用说明

websocks 分两个部分： `client` 与 `server`。

首先需要使用 `pip install websocks` 安装。

然后可以使用启动命令：

- 启动服务端使用： `websocks server -U USERNAME:PASSWORD 127.0.0.1 8765`

- 启动客户端使用： `websocks client -s USERNAME:PASSWORD@HOST:PORT 0.0.0.0 3128`

在启动服务端后，应使用 nginx 等反向代理服务器进行反向代理，并配置 SSL 证书（可参考[Wiki](https://github.com/abersheeran/websocks/wiki/Nginx-%E9%85%8D%E7%BD%AE-WebSocket)）。如果能够配置 CDN 代理 websocket 连接，那是最好的。

在启动客户端后，可使用 [proxifier](https://www.proxifier.com/) 等工具将本地 TCP 走 websocks 的代理。**websocks 并不会愚蠢的把你所有数据流量都通过远程服务器发送，所以尽可放心。**

### 通过 docker 启动

如果你的PC/服务器上没有安装 Python3.6+，并且你并不想安装，那么可以使用 docker 去启动 websocks。

本仓库有 docker 的自动构建，点此查看：[hub.docker](https://cloud.docker.com/u/abersheeran/repository/docker/abersheeran/websocks)

以下分别为服务端和客户端的 `docker-compose.yml` 样例。

```python
version: '3.3'
services:
  websocks:
    image: abersheeran/websocks
    command: websocks server -U USERNAME:PASSWORD 0.0.0.0 8765
    ports:
      - "8765:8765"
    restart: always
```

```python
version: '3.3'
services:
  websocks:
    image: abersheeran/websocks
    command: websocks client -s USERNAME:PASSWORD@HOST:PORT 0.0.0.0 3128
    ports:
      - "3128:3128"
    restart: always
```

如果你不懂 docker，也没关系，你只需要安装好 docker 与 docker-compose。然后在任意路径创建 `docker-compose.yml` 文件，写入如上内容并将一些需要你自己填写的部分替换。最后在同一目录下执行 `docker-compose up -d`，服务将能启动。

需要更新时，使用 `docker-compose pull` + `docker-compose up -d` 两条命令即可。

## 代理与否

由于 GFWList 是不断变化的，并且对于不同地区的网络屏蔽力度不同。所以 websocks 的代理策略由两部分组成

1. 名单: 使用 [GFWlist](https://github.com/gfwlist/gfwlist) 作为黑名单。自身编写了一个白名单 [whitelist](https://github.com/abersheeran/websocks/blob/master/websocks/whitelist.txt)。欢迎对白名单做出贡献

2. 自动连接: 由上所知，不同的网络环境下，需要加速的 Host 是不同的。所以当一个 Host 不在名单中时，会首先使用本地网络环境连接，超时后则转为使用代理连接。并且会将 Host 记录在内存里，下次访问直接使用代理。重新启动 websocks 后，此记录失效。

但如果你有全部代理的需求，可以在启动客户端时指定选项`-p PROXY`。

## 将要做的

客户端：

- [ ] 支持流量、网速、延迟等统计数据

- [ ] web 端界面用于管理客户端与服务器

服务端：

- [ ] 支持多用户. 支持流量统计.

- [ ] 提供 websocket 接口用于管理
