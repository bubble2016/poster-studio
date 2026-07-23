# 部署与数据持久化

## 目标

- 升级代码时，不覆盖用户账号信息和用户配置。

## 关键点

- 用户数据默认存放在 `web_data/`。
- 支持环境变量 `POSTER_DATA_DIR` 指定数据目录。
- 建议将数据目录放在代码目录之外（持久化目录或挂载卷）。

## 启动示例（Windows PowerShell）

```powershell
$env:POSTER_DATA_DIR = "D:\poster_data"
py app.py
```

## 启动示例（Linux）

```bash
export POSTER_DATA_DIR=/data/poster_data
python3 app.py
```

## 发布建议

1. 只上传代码，不覆盖数据目录。
2. 不要使用会删除远端未上传文件的同步策略（如 `--delete`）处理数据目录。
3. 发布前备份：
   - `users.json`
   - `user_configs/`

## 生产性能配置

仓库中的 `deploy/zhizhuli.com.conf` 是当前腾讯云站点的 Nginx 配置模板，包含：

- CSS、JavaScript、JSON 和 SVG 的 Gzip 压缩。
- 版本化静态资源一年强缓存，未带版本资源一小时短缓存。
- 静态文件和字体由 Nginx 直接发送，不占用 Gunicorn。
- 首页和用户 API 继续由 Gunicorn 动态处理。

上线前先备份现有配置，再检查差异：

```bash
stamp=$(date +%Y%m%d-%H%M%S)
cp -a /etc/nginx/conf.d/zhizhuli.com.conf \
  "/etc/nginx/conf.d/zhizhuli.com.conf.$stamp.bak"
diff -u /etc/nginx/conf.d/zhizhuli.com.conf \
  /www/wwwroot/poster-generator/deploy/zhizhuli.com.conf
```

确认项目路径仍为 `/www/wwwroot/poster-generator` 后再替换，并执行：

```bash
cp /www/wwwroot/poster-generator/deploy/zhizhuli.com.conf \
  /etc/nginx/conf.d/zhizhuli.com.conf
nginx -t
systemctl reload nginx
```

验证压缩和缓存：

```bash
curl -kfsSI --compressed https://www.zhizhuli.com/
curl -kfsSI --compressed \
  'https://www.zhizhuli.com/static/app.js?v=20260723v3'
```

带版本的 `app.js` 应返回 `Content-Encoding: gzip` 和
`Cache-Control: public, max-age=31536000, immutable`。首页 HTML 应保持
`Cache-Control: no-cache`。

## 本次前端性能策略

- 首屏和普通编辑使用系统中文字体在浏览器即时预览，不下载大型项目字体。
- 只有用户明确切换字体方案时，才在非省流量、非 2G/3G 网络下准备所选字体。
- 项目字体未准备好时，图片导出自动走服务端，保证最终字体和排版一致。
- SortableJS 在首张预览完成后异步加载，不再阻塞 HTML 解析。
- 上传图片按用途缩放：背景最长边 2560px，其余素材最长边 1200px。
- 图片优先转为 WebP；Logo、印章和二维码保留透明通道并使用无损压缩。

## Git 规则

- 仓库已忽略：`web_data/`
- `web_data/` 已从版本追踪中移除（仅移除 Git 索引，不删除本地文件）。
