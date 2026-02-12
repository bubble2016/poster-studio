# 部署与数据持久化

## 目标
- 升级代码时，不覆盖用户注册信息和用户配置。

## 关键点
- 用户数据默认在 `web_data/`。
- 现在支持环境变量 `POSTER_DATA_DIR` 指定数据目录。
- 建议把数据目录放到代码目录外（持久化目录/挂载卷）。

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
2. 不要使用会删除远端未上传文件的同步策略（如 `--delete`）去处理数据目录。
3. 发布前备份：
   - `users.json`
   - `user_configs/`

## Git 规则
- 仓库已加入忽略：`web_data/`
- 已把 `web_data/` 从版本跟踪中移除（仅移除 Git 索引，不删除本地文件）。
