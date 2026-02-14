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

## Git 规则

- 仓库已忽略：`web_data/`
- `web_data/` 已从版本追踪中移除（仅移除 Git 索引，不删除本地文件）。
