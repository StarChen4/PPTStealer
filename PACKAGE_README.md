# 项目打包说明

## 打包结果

打包后的可执行程序位于：`dist/WeChatPPT/`

### 目录结构
```
dist/WeChatPPT/
├── WeChatPPT.exe          # 主程序（可执行文件）
├── 启动工具.bat            # 友好的启动脚本
├── 使用说明.txt            # 使用说明文档
├── web/                   # 前端静态资源
│   └── dist/              # 打包后的前端文件
└── [其他依赖文件]          # Python运行时和库文件
```

## 使用方法

### 方式1：双击启动（推荐）
直接双击 `启动工具.bat` 或 `WeChatPPT.exe`

### 方式2：命令行启动
```cmd
cd dist\WeChatPPT
WeChatPPT.exe
```

程序会自动：
1. 启动后端服务在端口8000
2. 1.5秒后自动打开默认浏览器
3. 访问 http://localhost:8000

## 分发说明

### 打包整个文件夹
将 `dist/WeChatPPT/` 整个文件夹打包成 zip 或 rar：
- 文件夹大小约 100-200 MB
- 包含所有运行所需的依赖
- 无需安装Python、Node.js等运行环境

### 给用户
1. 解压 `WeChatPPT.zip` 到任意目录
2. 双击 `启动工具.bat` 或 `WeChatPPT.exe`
3. 等待浏览器自动打开

## 技术说明

### 打包工具
- **PyInstaller 6.17.0**：将Python应用打包成Windows可执行文件
- **Vite**：前端构建工具，生成优化后的静态资源

### 打包内容
- Python 3.14 运行时
- FastAPI + Uvicorn 后端
- React 前端（静态文件）
- 所有Python依赖库：
  - httpx（HTTP客户端）
  - beautifulsoup4 + lxml（HTML解析）
  - reportlab（PDF生成）
  - pillow（图片处理）

### 与开发版的区别

| 特性 | 开发版 | 打包版 |
|------|--------|--------|
| Python环境 | 需要安装 | 内置 |
| Node.js环境 | 需要安装 | 不需要 |
| 依赖安装 | 需要 pip/npm | 不需要 |
| 启动方式 | 分别启动前后端 | 单一可执行文件 |
| 文件大小 | 小 | 大（~150MB） |
| 热重载 | 支持 | 不支持 |
| 适用场景 | 开发调试 | 分发使用 |

## 原项目不受影响

打包过程**不会修改**原项目：
- `api/main.py` - 保持不变（开发版）
- `api/main_standalone.py` - 新增（打包版）
- `web/` - 保持不变
- `web/dist/` - 构建产物（可删除）

开发时仍然可以使用：
```bash
# 后端
cd api
.venv\Scripts\activate
uvicorn main:app --reload

# 前端
cd web
npm run dev
```

## 重新打包

如果需要重新打包（例如修改代码后）：

```bash
# 1. 重新构建前端
cd web
npm run build

# 2. 重新打包
cd ..
api\.venv\Scripts\pyinstaller.exe build.spec --clean
```

打包后的文件会覆盖 `dist/WeChatPPT/` 目录。

## 注意事项

1. **文件路径**：打包后的程序可以移动到任何目录运行
2. **网络需求**：需要联网才能抓取微信文章
3. **端口占用**：确保8000端口未被占用
4. **杀毒软件**：首次运行可能被杀毒软件拦截，添加信任即可
5. **兼容性**：支持 Windows 7 及以上版本

## 高级配置

### 修改端口
编辑 `api/main_standalone.py` 第208行：
```python
port = 8000  # 改为其他端口
```
然后重新打包。

### 自定义图标
在 `build.spec` 中添加：
```python
icon='path/to/icon.ico'
```

### 减小文件大小
在 `build.spec` 中：
```python
upx=True,  # 使用UPX压缩（已启用）
exclude_binaries=False,  # 将所有内容打包到单个exe
```

## 问题排查

### 程序无法启动
- 检查是否有杀毒软件拦截
- 确认端口8000未被占用
- 查看命令行窗口的错误信息

### 浏览器没有自动打开
- 手动访问 http://localhost:8000
- 检查防火墙设置

### 无法生成PDF
- 确认网络连接正常
- 检查微信文章链接是否有效
- 查看命令行窗口的错误日志
