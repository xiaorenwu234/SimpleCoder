# Simple Coder 安装指南

## 环境要求

- Python 3.11 或 3.12
- Conda 或 Mamba
- (可选) Docker - 用于 MCP 工具

## 快速安装

### 1. 创建 Conda 环境

```bash
conda env create -f environment_portable.yaml
```

### 2. 激活环境

```bash
conda activate simple-coder
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的 API 密钥：

```env
# 使用通义千问 (推荐)
DASHSCOPE_API_KEY=your_api_key_here
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-plus

# 或使用 OpenAI
# OPENAI_API_KEY=your_openai_key
# OPENAI_API_BASE=https://api.openai.com/v1
```

### 4. 运行程序

```bash
python main.py
```

## 版本兼容性

本项目使用以下核心依赖版本（已验证兼容）：

- **langgraph**: 0.2.53
- **langchain-core**: 0.3.86
- **langchain**: 0.3.7
- **langchain-mcp-adapters**: 0.1.11

⚠️ **重要提示**：不要随意升级这些包！版本不兼容会导致错误。

## 常见问题

### Q1: 出现 `No module named 'langchain_core.messages.content'` 错误

**原因**：langchain-core 版本不兼容（可能是 1.x 版本）

**解决方法**：
```bash
pip install 'langchain-core==0.3.86' 'langgraph==0.2.53'
```

### Q2: 出现 `ImportError: cannot import name 'Interrupt'` 错误

**原因**：langgraph 版本问题

**解决方法**：
```bash
pip install 'langgraph==0.2.53'
```

### Q3: MCP 工具加载失败

这是正常的！MCP 工具需要 Docker 支持。如果没有 Docker，程序会使用本地工具继续运行。

要启用 MCP 工具：
1. 安装并启动 Docker
2. 确保网络可以拉取 Docker 镜像

### Q4: 依赖冲突

如果安装时出现依赖冲突，尝试：
```bash
# 删除现有环境
conda env remove -n simple-coder

# 重新创建
conda env create -f environment_portable.yaml
```

## 特殊命令

程序运行后可以使用以下命令：

- `/help` - 显示帮助信息
- `/rollback` - 查看操作历史
- `/rollback <id>` - 回退指定操作
- `/history` - 查看对话历史
- `/stats` - 查看工具使用统计
- `/index` - 重新索引代码库

## 项目结构

```
claude_code_clone-main/
├── agent.py              # 主 Agent 逻辑
├── main.py               # 入口文件
├── tools/                # 工具目录
│   ├── code_edit.py      # 代码编辑工具
│   ├── run_command.py    # 命令执行工具
│   ├── safe_code_edit.py # 安全代码编辑（带备份）
│   └── ...
├── environment_portable.yaml  # 环境配置
└── .env.example          # 环境变量示例
```

## 技术支持

如遇到其他问题，请检查：
1. Python 版本是否为 3.11 或 3.12
2. 是否正确激活了 conda 环境
3. .env 文件是否正确配置
