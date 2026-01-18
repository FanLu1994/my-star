# GitHub Star 标注器

> 自动分析你的 GitHub Star 收藏，使用 LLM 进行智能分类和描述。

**注意**: `README.md` 是由程序自动生成的 Star 收藏列表。本文档 `SETUP.md` 是项目配置说明。

## 功能特性

- 每天自动同步你的 GitHub Star 列表
- 使用 LLM 智能分析仓库内容
- 自动分类：AI/机器学习、Web开发、移动开发、数据库等
- 生成结构化的 Markdown 文档
- 自动清理已取消 Star 的仓库
- 跳过已处理的仓库，提高效率

## 配置步骤

### 1. 准备 GitHub Token

1. 访问 [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. 点击 "Generate new token" -> "Generate new token (classic)"
3. 勾选以下权限：
   - `repo` (完整仓库访问权限)
   - `user` (读取用户信息)
4. 生成并复制 token

### 2. 准备 LLM API Key

支持以下 AI 服务提供商（均为 OpenAI 兼容 API）：

| 提供商 | 获取地址 | 特点 |
|--------|---------|------|
| **DeepSeek** | [platform.deepseek.com](https://platform.deepseek.com/api_keys) | 性价比高，中文友好 |
| **智谱 GLM** | [open.bigmodel.cn](https://open.bigmodel.cn/usercenter/apikeys) | 国产大模型，免费额度 |
| **通义千问** | [dashscope.aliyuncs.com](https://dashscope.console.aliyun.com/apiKey) | 阿里云出品 |
| **OpenAI** | [platform.openai.com](https://platform.openai.com/api-keys) | 原版 GPT |
| **Moonshot** | [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys) | Kimi 背后的模型 |
| **本地模型** | 通过 Ollama 等部署 | 完全免费，隐私安全 |

### 3. 配置仓库 Secrets

在你的 GitHub 仓库中设置以下 Secrets：

1. 进入仓库的 `Settings` -> `Secrets and variables` -> `Actions`
2. 点击 `New repository secret` 添加以下密钥：

| Secret 名称 | 说明 | 示例 |
|------------|------|------|
| `OPENAI_API_KEY` | LLM API 密钥 | `sk-xxx...` |
| `OPENAI_BASE_URL` | API 基础 URL | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 模型名称 | `gpt-4o-mini` |
| `MY_GITHUB_TOKEN` | GitHub Token（步骤1中创建） | `ghp_xxx...` |

**重要**: `MY_GITHUB_TOKEN` 不能使用 GitHub Action 默认提供的 `GITHUB_TOKEN`，**必须**使用步骤1中手动创建的 Personal Access Token，否则将无法正常工作。

### 4. API 配置示例

#### DeepSeek（推荐，性价比最高）
```bash
OPENAI_API_KEY: sk-xxx...
OPENAI_BASE_URL: https://api.deepseek.com/v1
OPENAI_MODEL: deepseek-chat
# 或使用更便宜的 deepseek-ai/DeepSeek-V3
```

#### 智谱 GLM
```bash
OPENAI_API_KEY: xxx...  # 格式: id.secret
OPENAI_BASE_URL: https://open.bigmodel.cn/api/paas/v4
OPENAI_MODEL: glm-4-flash    # 免费，速度快
# 或 glm-4-plus / glm-4-air
```

#### 通义千问
```bash
OPENAI_API_KEY: sk-xxx...
OPENAI_BASE_URL: https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL: qwen-plus       # 推荐
# 或 qwen-turbo（便宜） / qwen-max（更强）
```

#### Moonshot（Kimi）
```bash
OPENAI_API_KEY: sk-xxx...
OPENAI_BASE_URL: https://api.moonshot.cn/v1
OPENAI_MODEL: moonshot-v1-8k   # 或 moonshot-v1-32k
```

#### OpenAI
```bash
OPENAI_API_KEY: sk-xxx...
OPENAI_BASE_URL: https://api.openai.com/v1
OPENAI_MODEL: gpt-4o-mini      # 最便宜的 GPT-4
# 或 gpt-4o / gpt-3.5-turbo
```

#### 本地 Ollama
```bash
OPENAI_API_KEY: ollama  # 任意字符串
OPENAI_BASE_URL: http://localhost:11434/v1
OPENAI_MODEL: qwen2:7b  # 或其他已下载的模型
```

## 本地运行

1. 克隆仓库并安装依赖：

```bash
pip install -r requirements.txt
```

2. 复制 `.env.example` 为 `.env` 并配置：

```bash
cp .env.example .env
```

3. 编辑 `.env` 文件：

```env
# GitHub Token
MY_GITHUB_TOKEN=your_github_token_here

# 使用 DeepSeek（推荐）
OPENAI_API_KEY=sk-xxx...
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat

# 或使用智谱 GLM
# OPENAI_API_KEY=xxx...
# OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
# OPENAI_MODEL=glm-4-flash

REPO_OWNER=your_username
REPO_NAME=your_repo_name
```

4. 运行脚本：

```bash
python main.py
```

## GitHub Action 自动运行

配置完成后，GitHub Action 会：

1. 每天 UTC 0:00（北京时间 8:00）自动运行
2. 分析你的 Star 列表
3. 生成 Markdown 文档并提交到 `data/README.md`

你也可以手动触发：进入仓库的 `Actions` 页面，选择 `Daily Star Analyzer` 工作流，点击 `Run workflow`。

## 生成的文件

- `data/stars.json` - 原始 star 数据
- `data/processed.json` - 已处理的仓库数据
- `data/README.md` - 生成的分类文档

## 分类说明

仓库会被自动分类到以下类别之一：

- AI/机器学习
- Web开发
- 移动开发
- 数据库
- 工具/库
- 框架
- DevOps/基础设施
- 游戏
- 教育
- 其他

## 成本对比（参考）

假设每天分析 100 个仓库，每月约 3000 次调用：

| 提供商 | 模型 | 价格 (输入/输出) | 月成本估算 |
|--------|------|-----------------|-----------|
| DeepSeek | deepseek-chat | ¥1/1M tokens | ~¥1-2 |
| 智谱 GLM | glm-4-flash | 免费 | ¥0 |
| 通义千问 | qwen-turbo | ¥0.8/1M tokens | ~¥1 |
| Moonshot | moonshot-v1-8k | ¥12/1M tokens | ~¥10 |
| OpenAI | gpt-4o-mini | $0.15/1M tokens | ~¥3 |

**推荐组合**：
- 日常使用：DeepSeek（性价比最高）
- 零成本：智谱 GLM 免费版
- 本地部署：Ollama + Qwen2/GLM（完全免费）

## 常见问题

### Q: 如何切换 AI 提供商？
A: 只需修改 Secrets 中的三个配置（API_KEY、BASE_URL、MODEL）即可，无需修改代码。

### Q: 本地运行和 GitHub Action 使用不同的配置怎么办？
A: 本地使用 `.env` 文件，GitHub Action 使用 Secrets，两者互不影响。

### Q: API 调用失败了怎么办？
A: 脚本会跳过失败的仓库并继续处理，已处理的仓库会被缓存，下次运行会跳过。

## 许可证

MIT
