# ez-comfyui-showcase Agent Notes

## 项目

- 项目名: ez-comfyui-showcase
- 日期: 2026-06-18
- 技术栈: FastAPI/Python 后端，静态 HTML/CSS/JavaScript 前端，SQLite/JSON 配置数据，ComfyUI 工作流与实例管理。

## 工作原则

- 默认中文沟通，代码、命令、变量名使用英文。
- 先说明结论，再说明原因和对用户的影响。
- 文件改动前先读取上下文，保持小范围修改。
- 不回退用户或其他 agent 已产生的改动。
- 前端静态资源改动后，同步更新 `static/index.html` 与 `static/js/module_loader.js` 的缓存版本。

## 本地约束

- 本地站点默认访问: `http://localhost:18000/`
- 主要快速出图逻辑: `static/js/modules/generate.js`
- 项目记忆: `MEMORY.md`

