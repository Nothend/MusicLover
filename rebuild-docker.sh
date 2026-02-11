#!/bin/bash
# Docker重新部署脚本 - 修复CSS加载问题后使用

echo "🔧 开始重新部署MusicLover Docker服务..."
echo ""

# 1. 停止并删除旧容器
echo "📦 步骤 1/4: 停止并删除旧容器..."
docker-compose down
echo "✅ 旧容器已停止"
echo ""

# 2. 重新构建镜像（不使用缓存，确保使用最新代码）
echo "🏗️  步骤 2/4: 重新构建Docker镜像（不使用缓存）..."
docker-compose build --no-cache
if [ $? -ne 0 ]; then
    echo "❌ 镜像构建失败，请检查错误信息"
    exit 1
fi
echo "✅ 镜像构建成功"
echo ""

# 3. 启动新容器
echo "🚀 步骤 3/4: 启动新容器..."
docker-compose up -d
if [ $? -ne 0 ]; then
    echo "❌ 容器启动失败，请检查错误信息"
    exit 1
fi
echo "✅ 容器启动成功"
echo ""

# 4. 显示日志
echo "📋 步骤 4/4: 显示容器日志（按Ctrl+C退出日志查看）..."
echo "请检查日志中是否显示正确的静态文件路径："
echo "  📁 静态文件路径: /app/src/static"
echo "  📄 模板文件路径: /app/src/templates"
echo ""
echo "开始显示日志..."
echo "----------------------------------------"
docker-compose logs -f

# 注意：按Ctrl+C会退出日志查看，但不会停止容器
