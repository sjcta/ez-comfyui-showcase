# Branching Strategy

## Branches

| Branch | Purpose | Rules |
|--------|---------|-------|
| `main` | **稳定发布版** | 只从其他分支合并，禁止直接提交 |
| `design` | **设计风格** | CSS/HTML/UI 样式改动，合并到 main |
| `feature` | **功能开发** | 新功能/后端逻辑，合并到 main |
| `hotfix` | **紧急修复** | 从 main 创建，修复后合并回 main |

## Workflow

```
design ──→ main ←── feature
                 ↑
              hotfix
```

1. 设计/样式改动 → `design` 分支
2. 功能/后端改动 → `feature` 分支
3. 紧急修复 → `hotfix` 分支
4. 稳定后合并到 `main` → 打 tag 发布

## 部署

```bash
# DGX 部署脚本
ssh sjcta@10.10.10.75 "bash /home/sjcta/deploy.sh"
```

部署脚本 `deploy.sh` 会：
1. `git fetch origin`
2. `git checkout main`
3. `git reset --hard origin/main`（纯净拉取）
4. 重启服务并验证 HTTP 200
