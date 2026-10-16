# 模板

此目录中的 `index.html` 是当前构建流程建立前遗留的旧文件。它引用的 `static/js/` 和
`static/css/` 目录结构已与当前应用的构建和服务方式不符。`flask_app.py` 不会调用 Flask 的
`render_template()`，也不会读取此目录；它会通过 `serve_spa()` 直接提供 `static/app/` 中的 React
生产构建文件由 `scripts/build_frontend.sh` 与 `scripts/sync_frontend_to_ros.sh` 生成和同步。

常规前端改动应放在仓库根目录的 `web/` 中，而非此处。此目录目前未被使用，可以忽略；清理无用文件时也可考虑删除。
