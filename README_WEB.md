# 公告海报生成器 Web（移动端）

## 启动

```bash
py -m pip install -r requirements.txt
py app.py
```

浏览器打开：`http://127.0.0.1:5173`

## 已保留功能

- 海报实时预览与最终导出（PNG/JPEG/PDF）
- 系统模版/自定义模版管理（保存、删除、切换）
- 自动格式化、批量调价、内容校验
- 店铺信息、主题色、卡片样式、背景参数、印章参数
- Logo/背景/印章/二维码上传
- 水印开关、文字、透明度
- 生成后模式：复制图片、复制文案、仅打开文件（浏览器能力范围内）

## 数据目录

- 配置：`web_data/web_config.json`
- 上传：`web_data/uploads/`
- 导出：`web_data/outputs/`
