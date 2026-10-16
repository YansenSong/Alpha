# React 生成文件

此目录由以下命令生成：

```bash
bash scripts/build_frontend.sh
bash scripts/sync_frontend_to_ros.sh
```

请勿提交此目录中生成的 `index.html`、`asset-manifest.json`、`ros/` 或 `static/` 构建文件。
这些均为构建产物，可能导致 UI 提供过期资源。
