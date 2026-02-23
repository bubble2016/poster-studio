# Poster Studio

面向打包站与中小商家的公告海报生成工具，支持实时预览、模板复用、批量调价与一键导出，适合高频公告发布场景。

## 功能特性

- 实时预览 + 导出：`PNG` / `JPEG` / `PDF`
- 模板管理：系统模板与自定义模板（保存、切换、删除）
- 文案处理：自动格式化、批量调价、内容校验
- 视觉配置：主题色、卡片样式、背景参数、印章参数
- 素材管理：背景图 / Logo / 印章 / 二维码上传
- 账号与草稿：访客草稿、登录后继续编辑

## 快速开始

```bash
py -m pip install -r requirements.txt
py app.py
```

浏览器访问：`http://127.0.0.1:5173`

## 项目结构

- `app.py`: Web 服务入口
- `poster_engine.py`: 海报渲染核心
- `templates/`: 页面模板
- `static/`: 前端脚本与样式
- `web_data/`: 配置、上传与导出数据
- `tests/`: 自动化测试

## 相关文档

- Web 使用说明：`README_WEB.md`
- 部署说明：`DEPLOY.md`
- 更新日志：`CHANGELOG.md`
