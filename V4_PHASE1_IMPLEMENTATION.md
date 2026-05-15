# Phase 1 — 用户认证系统 实现方案

## 后端实现（app.py）

### 新依赖
```python
# 需要安装: pip install python-jose[cryptography] passlib[bcrypt]
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timedelta
```

### 配置常量
```python
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7
```

### 用户表 SQL
```sql
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    avatar TEXT DEFAULT '',
    created_at DATETIME DEFAULT (datetime('now','localtime'))
)
```

### API 端点

```
POST /auth/register
  Body: { username, password }
  Response: { id, username, token }

POST /auth/login
  Body: { username, password }
  Response: { id, username, token }

GET /auth/me (需要 Authorization: Bearer <token>)
  Response: { id, username, avatar, created_at }
```

### JWT 中间件
```python
def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(401)
    token = auth.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(401)
```

## 前端实现

### 新文件: static/js/modules/auth.js
- 登录弹窗逻辑
- 注册弹窗逻辑
- token 管理（localStorage）
- 登录状态检查
- API 请求拦截器（自动带 Authorization header）

### index.html 修改
- 标题栏右侧加「登录」「注册」按钮（未登录时）
- 已登录显示用户名 +「退出」
- 登录/注册模态框 HTML

## 安全注意事项
1. 密码最少 6 位
2. 注册用户名唯一
3. JWT 密钥通过环境变量配置
4. 密码用 bcrypt 哈希
5. 所有 /auth/ 开头 API 返回 JSON（不需要 auth）
6. 受限 API 通过 get_current_user 依赖注入保护
