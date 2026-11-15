# Windows 反向代理、TLS 与认证

生产环境不要直接把 8000/8501 暴露到 LAN/公网。推荐：

```
浏览器 --TLS--> IIS/Nginx/Caddy --Windows 认证/OIDC--> 127.0.0.1:8501 (Streamlit)
                                                   └──> 127.0.0.1:8000 (API, 可选)
```

## 原则

- API 和 Streamlit 只绑定 `127.0.0.1`；
- 反代监听 443，证书由企业 CA 或 Let's Encrypt 签发；
- 登录使用 Windows 集成认证/OIDC/反向代理 Basic Auth；
- 若浏览器直接访问 API，必须加 `X-API-Key` 或改为同源代理注入；
- Streamlit 走 WebSocket，IIS 需启用 WebSocket 协议，Nginx 需 `proxy_http_version 1.1` + `Upgrade` 头；
- `/docs` 和 `/api/v1/retention/*` 仅管理员可访问。

## Nginx 示例

```nginx
server {
    listen 443 ssl;
    server_name noise.example.local;
    ssl_certificate     C:/certs/noise.crt;
    ssl_certificate_key C:/certs/noise.key;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header X-API-Key "change-me";
        proxy_set_header Host $host;
    }

    location /health/ {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

## IIS 要点

- 安装 ARR + URL Rewrite + WebSocket Protocol；
- 反向代理到 `http://127.0.0.1:8501`，启用 WebSocket；
- 启用 Windows 身份验证，禁用匿名；
- 为 API 路径添加 URL Rewrite 到 `127.0.0.1:8000`，由 IIS 注入 `X-API-Key`；
- 增加请求超时、上传限制、访问日志。

## 验收

- 外网/非授权网段无法直连 8000/8501；
- 443 登录后 UI 可用，WebSocket 刷新正常；
- API Key 不出现于浏览器源码；
- 证书有效期/NTP 时间正确。
