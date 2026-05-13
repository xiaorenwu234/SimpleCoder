# Simple Coder - AI 编程助手

基于 LangGraph 和 LangChain 的智能编程助手，支持代码编辑、命令执行、代码搜索、操作回滚等功能。

## 📋 环境要求

- **Python**: 3.11 或 3.12
- **pip**: 用于安装依赖
- **Conda** (可选): 用于环境管理
- **(可选) Docker**: 用于 MCP 工具（如 DuckDuckGo 搜索、GitHub API 等）

## 🚀 快速开始

### 1. 克隆或下载项目

```bash
cd SimpleCoder
```

### 2. 安装依赖

**方法 1: 使用 pip + requirements.txt（推荐）**

```bash
# 确保 Python 版本为 3.11 或 3.12
python --version

# 安装所有依赖
pip install -r requirements.txt
```

> ⏱️ 这个过程可能需要 3-5 分钟，取决于网络速度。

**方法 2: 使用 Conda（可选）**

```bash
# 创建 conda 环境
conda create -n simple-coder python=3.12

# 激活环境
conda activate simple-coder

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置环境变量

复制环境变量模板：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的 API 密钥：

```env
# 使用通义千问（推荐，国内可用）
DASHSCOPE_API_KEY=你的API密钥
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-plus
```

### 4. 运行程序

```bash
python main.py
```

## 🛠️ 特殊命令

程序运行后，可以使用以下斜杠命令：

| 命令 | 说明 | 示例 |
|------|------|------|
| `/help` | 显示帮助信息 | `/help` |
| `/rollback` | 查看操作历史 | `/rollback` |
| `/rollback <id>` | 回退指定操作 | `/rollback 5` |
| `/history` | 查看对话历史 | `/history` |
| `/stats` | 查看工具使用统计 | `/stats` |
| `/index` | 重新索引代码库 | `/index` |

## 📦 核心功能

### 本地工具（16个）

- ✅ **文件操作**: 读取、写入、搜索文件
- ✅ **代码编辑**: 安全编辑（自动备份）、代码格式化、代码检查
- ✅ **命令执行**: 安全执行命令、运行测试
- ✅ **代码搜索**: 语义搜索、代码索引
- ✅ **版本控制**: Git diff、操作回滚
- ✅ **记忆系统**: 跨会话记忆、工具统计

### MCP 工具（可选，需要 Docker）

- 🔍 DuckDuckGo 搜索
- 🐙 GitHub API（只读）

## ❓ 常见问题

### Q1: MCP 工具加载失败

这是**正常现象**！MCP 工具需要 Docker 支持。没有 Docker 时，程序会使用本地工具继续运行。

**要启用 MCP 工具：**

1. 安装 Docker Desktop
2. 启动 Docker
3. 确保网络可以拉取 Docker 镜像

### Q2: 浏览器工具无法使用

需要配置梯子，duckduckgo浏览器无法使用国内网络访问

## 📁 项目结构

```
claude_code_clone-main/
├── agent.py                      # 主 Agent 逻辑
├── main.py                       # 入口文件
├── tools/                        # 工具目录
│   ├── code_edit.py             # 代码编辑工具
│   ├── safe_code_edit.py        # 安全代码编辑（带备份）
│   ├── run_command.py           # 命令执行工具
│   ├── safe_run_command.py      # 安全命令执行
│   ├── code_search_tool.py      # 代码搜索工具
│   ├── code_indexer.py          # 代码索引器
│   ├── operation_rollback.py    # 操作回滚
│   ├── agent_memory.py          # Agent 记忆系统
│   └── ...                      # 其他工具
├── requirements.txt             # ✅ Python 依赖配置
├── .env.example                 # 环境变量模板
└── INSTALL.md                   # 详细安装指南
```

## 🔧 在其他电脑上安装

### 方法 1: 使用 pip（推荐）

```bash
# 1. 复制项目到新电脑
# 2. 确保 Python 3.11 或 3.12
python --version

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置 .env 文件
cp .env.example .env
# 编辑 .env，填入 API 密钥

# 5. 运行
python main.py
```

### 方法 2: 使用 Conda

```bash
# 1. 复制项目到新电脑
# 2. 创建环境
conda create -n simple-coder python=3.11

# 3. 激活环境
conda activate simple-coder

# 4. 安装依赖
pip install -r requirements.txt

# 5. 配置 .env 文件
cp .env.example .env
# 编辑 .env，填入 API 密钥

# 6. 运行
python main.py
```

## 📝 开发指南

### 添加新工具

1. 在 `tools/` 目录创建新的工具文件
2. 实现工具类或函数
3. 在 `agent.py` 的 `initialize()` 方法中注册工具

### 调试模式

```bash
# 查看详细日志
export LOG_LEVEL=DEBUG
python main.py
```

## 🤝 技术支持

如遇到其他问题：

1. 检查 Python 版本：`python --version`（应为 3.11 或 3.12）
2. 确认依赖已安装：`pip list | grep langchain`
3. 检查依赖版本：`pip show langgraph`
4. 查看日志文件：`cat agent.log`

## 📄 许可证

详见 LICENSE 文件。

## 🌟 特性亮点

- 🔒 **安全执行**: 沙盒环境 + 自动备份
- 🔄 **操作回滚**: 支持撤销任何文件修改
- 🔍 **智能搜索**: 代码索引 + 语义搜索
- 🧠 **持久记忆**: 跨会话保存上下文
- 📊 **统计分析**: 工具使用统计和成功率
- ⚡ **并行执行**: 支持并行工具调用

---

**祝使用愉快！** 🎉
