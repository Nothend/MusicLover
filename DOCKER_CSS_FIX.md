# 🔧 Docker部署CSS加载失败 - 快速修复指南

## ⚠️ 问题症状
- Docker部署后网页打开，但**没有样式**（页面看起来很简陋）
- 浏览器控制台（F12）显示 `style.css` 或 `main.js` 加载失败（404错误）
- 本地运行正常，但Docker容器中运行异常

## ✅ 已修复的问题
已修改 `src/main.py` 文件，明确指定Flask的静态文件和模板文件夹路径，解决Docker环境中的路径识别问题。

## 🚀 快速部署步骤

### 方法1: 使用自动化脚本（推荐）

```bash
# 1. 确保你在项目根目录
cd /path/to/MusicLover

# 2. 运行重新部署脚本
./rebuild-docker.sh
```

脚本会自动完成以下操作：
1. 停止并删除旧容器
2. 重新构建Docker镜像（不使用缓存）
3. 启动新容器
4. 显示运行日志

### 方法2: 手动执行命令

```bash
# 1. 停止并删除旧容器
docker-compose down

# 2. 重新构建镜像（重要：必须使用 --no-cache）
docker-compose build --no-cache

# 3. 启动容器
docker-compose up -d

# 4. 查看日志（可选）
docker-compose logs -f musiclover
```

## 🔍 验证修复是否成功

### 1. 检查启动日志
运行 `docker-compose logs musiclover`，应该能看到类似以下内容：

```
📁 静态文件路径: /app/src/static
📄 模板文件路径: /app/src/templates
```

### 2. 访问网页
打开浏览器访问：`http://localhost:5151` 或 `http://你的服务器IP:5151`

**正常情况应该看到**：
- ✅ 页面有完整的样式（颜色、布局正确）
- ✅ 按钮、输入框等元素显示正常
- ✅ 页面顶部有"高品质音乐无损解析"标题

### 3. 检查浏览器控制台（F12）
1. 打开浏览器开发者工具（按F12键）
2. 切换到 **Network（网络）** 标签
3. 刷新页面（Ctrl+R 或 Cmd+R）
4. 查找 `style.css` 和 `main.js`

**正常情况应该看到**：
- ✅ `style.css` - 状态码 200（绿色）
- ✅ `main.js` - 状态码 200（绿色）
- ❌ 如果看到404（红色），说明问题仍未解决

## 🐛 如果问题仍然存在

### 检查1: 确认文件是否在容器内
```bash
# 进入容器
docker exec -it musiclover sh

# 检查静态文件是否存在
ls -la /app/src/static/
# 应该看到: style.css, favicon.ico, js/ 等文件

ls -la /app/src/templates/
# 应该看到: index.html

# 退出容器
exit
```

### 检查2: 查看详细错误日志
```bash
# 查看最近100行日志
docker-compose logs --tail=100 musiclover

# 实时查看日志
docker-compose logs -f musiclover
```

### 检查3: 清除浏览器缓存
有时浏览器会缓存旧的404错误：
1. 按 `Ctrl+Shift+Delete`（或 `Cmd+Shift+Delete`）
2. 清除缓存和Cookie
3. 或者使用**隐私模式/无痕模式**重新访问

### 检查4: 确认端口映射正确
```bash
# 查看容器是否正在运行
docker ps | grep musiclover

# 应该看到类似：
# 0.0.0.0:5151->5151/tcp
```

## 📝 技术细节

### 修改内容
**文件**: `src/main.py`

**修改前**:
```python
app = Flask(__name__)
```

**修改后**:
```python
# 明确指定static和template文件夹路径
current_dir = Path(__file__).parent
app = Flask(__name__, 
            static_folder=str(current_dir / 'static'),
            template_folder=str(current_dir / 'templates'))
```

### 为什么需要这个修复？
- Flask默认使用相对路径查找静态文件和模板
- 在Docker容器中，由于工作目录切换等原因，相对路径可能失效
- 使用绝对路径可以确保Flask始终能找到正确的文件夹

## 📞 获取帮助

如果按照以上步骤操作后问题仍未解决，请：

1. **提供以下信息**：
   - 容器日志：`docker-compose logs musiclover > logs.txt`
   - 浏览器控制台截图（F12 → Console和Network标签）
   - 访问的URL地址

2. **提交Issue**：
   - GitHub: https://github.com/Nothend/MusicLover/issues
   - 标题：[Docker] CSS加载失败问题

## 🎉 成功标志

修复成功后，你应该能看到一个**美观的网页界面**，包括：
- 渐变色背景
- 卡片式布局
- 响应式设计
- 完整的交互功能

---

**最后更新**: 2026-02-11  
**修复版本**: v2.0.1
