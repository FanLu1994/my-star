#!/usr/bin/env python3
"""
GitHub Star 标注器
定时拉取用户的star列表，使用LLM分析仓库并生成分类的markdown文件
"""

import os
import re
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI

# 加载环境变量
load_dotenv()

# 仓库分类（同时决定 README 中的分类顺序）
CATEGORIES = [
    "AI/机器学习", "Web开发", "移动开发", "框架",
    "数据库", "工具/库", "DevOps/基础设施", "游戏", "教育", "其他"
]
DEFAULT_CATEGORY = "其他"

# 每新分析多少个仓库保存一次缓存
SAVE_INTERVAL = 10

# LLM 分析失败（请求出错、JSON 解析或字段校验失败）时的最大尝试次数
LLM_MAX_ATTEMPTS = 3

# README 中生成详情和跳转链接的标签数量（按使用次数取前N个）
TAG_DETAIL_LIMIT = 50

# prompt 中提供给 LLM 复用的常用标签数量
PROMPT_TAG_LIMIT = 50

# GitHub API 请求超时（秒）
GITHUB_TIMEOUT = 30

# README 中显示的时区（北京时间）
DISPLAY_TZ = timezone(timedelta(hours=8))


class GitHubStarAnalyzer:
    """GitHub Star 分析器"""

    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.repo_owner = os.getenv("REPO_OWNER")
        self.repo_name = os.getenv("REPO_NAME")
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)

        # 初始化OpenAI客户端
        self.openai_client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        )

        # 数据文件路径
        self.processed_file = self.data_dir / "processed.json"
        self.markdown_file = Path("README.md")  # 输出到根目录

        # 加载已处理的数据
        self.processed_stars = self._load_processed()

    def _load_processed(self) -> Dict[str, Any]:
        """加载已处理的star数据"""
        if self.processed_file.exists():
            with open(self.processed_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_processed(self):
        """保存已处理的star数据（先写临时文件再替换，避免写入中断导致文件损坏）"""
        tmp_file = self.processed_file.with_name(self.processed_file.name + ".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.processed_stars, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, self.processed_file)

    def get_starred_repos(self) -> List[Dict[str, Any]]:
        """获取用户star的所有仓库"""
        print("正在获取star列表...")
        stars = []
        page = 1
        per_page = 100

        while True:
            try:
                url = "https://api.github.com/user/starred"
                params = {"page": page, "per_page": per_page}

                # star+json 格式才会返回 starred_at，结构为 {"starred_at": ..., "repo": {...}}
                headers = {
                    "Authorization": f"token {self.github_token}",
                    "Accept": "application/vnd.github.star+json"
                }
                response = requests.get(url, headers=headers, params=params, timeout=GITHUB_TIMEOUT)
                response.raise_for_status()

                # 检查是否还有下一页
                link_header = response.headers.get('Link', '')
                has_next = 'rel="next"' in link_header

                data = response.json()

                if not data:  # 空结果，结束
                    break

                stars.extend({**item["repo"], "starred_at": item.get("starred_at", "")} for item in data)
                print(f"  第{page}页: 获取到 {len(data)} 个，累计 {len(stars)} 个star")
                page += 1

                if not has_next:  # 没有下一页了
                    break

                time.sleep(0.2)  # 避免触发限流

            except requests.exceptions.RequestException as e:
                print(f"获取star列表时出错: {e}")
                status_code = e.response.status_code if e.response is not None else None
                if status_code == 401:
                    print("错误: GitHub Token 无效或已过期，请检查 GITHUB_TOKEN")
                elif status_code == 403:
                    print("错误: API 速率限制，请稍后再试")
                # 列表不完整时不能继续，否则后续清理会误删缓存
                raise

        print(f"总共获取到 {len(stars)} 个star")
        return stars

    def _build_meta(self, repo: Dict[str, Any]) -> Dict[str, Any]:
        """从 GitHub 返回数据中提取仓库元数据（每次运行都会刷新）"""
        return {
            "repo_name": repo["full_name"],
            "repo_url": repo["html_url"],
            "language": repo.get("language", ""),
            "stars": repo["stargazers_count"],
            "starred_at": repo.get("starred_at", ""),
            "original_description": repo.get("description", "")
        }

    def _tag_key(self, tag: str) -> str:
        """标签归一化键：忽略大小写、空格、下划线和连字符"""
        return re.sub(r"[\s_-]", "", tag.lower())

    def _build_tag_display(self, repos: List[Dict[str, Any]]) -> Dict[str, str]:
        """把同一标签的不同写法映射为使用次数最多的写法

        Returns:
            Dict[str, str]: 原始标签 -> 显示标签
        """
        variants: Dict[str, Counter] = defaultdict(Counter)
        for repo in repos:
            for tag in repo.get("tags", []):
                variants[self._tag_key(tag)][tag] += 1
        return {
            tag: counter.most_common(1)[0][0]
            for counter in variants.values()
            for tag in counter
        }

    def _count_tags(self, repos: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """按合并后的标签收集仓库（同一仓库内重复的写法只计一次）"""
        tag_display = self._build_tag_display(repos)
        tag_repos: Dict[str, List[Dict[str, Any]]] = {}
        for repo in repos:
            for tag in dict.fromkeys(tag_display[t] for t in repo.get("tags", [])):
                tag_repos.setdefault(tag, []).append(repo)
        return tag_repos

    def _common_tags(self, limit: int) -> List[str]:
        """已缓存数据中使用次数最多的标签"""
        tag_repos = self._count_tags(list(self.processed_stars.values()))
        sorted_tags = sorted(tag_repos.items(), key=lambda x: len(x[1]), reverse=True)
        return [tag for tag, _ in sorted_tags[:limit]]

    def _validate_analysis(self, analysis: Any) -> Dict[str, Any]:
        """校验 LLM 返回的分析结果，不合法时抛出 ValueError"""
        if not isinstance(analysis, dict):
            raise ValueError("返回结果不是JSON对象")
        for field in ("description", "use_case"):
            if not isinstance(analysis.get(field), str):
                raise ValueError(f"字段 {field} 缺失或不是字符串")
        tags = analysis.get("tags")
        if not isinstance(tags, list):
            raise ValueError("字段 tags 缺失或不是列表")
        analysis["tags"] = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
        if analysis.get("category") not in CATEGORIES:
            analysis["category"] = DEFAULT_CATEGORY
        return analysis

    def _request_analysis(self, prompt: str) -> Dict[str, Any]:
        """调用 LLM 并解析结果，失败时重试"""
        last_error: Optional[Exception] = None
        for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
            try:
                response = self.openai_client.chat.completions.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    messages=[
                        {"role": "system", "content": "你是一个专业的软件分析师，擅长分析GitHub仓库并进行分类。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=500
                )

                result_text = (response.choices[0].message.content or "").strip()

                # 清理可能的markdown标记
                if result_text.startswith("```json"):
                    result_text = result_text[7:]
                if result_text.startswith("```"):
                    result_text = result_text[3:]
                if result_text.endswith("```"):
                    result_text = result_text[:-3]
                result_text = result_text.strip()

                return self._validate_analysis(json.loads(result_text))

            except Exception as e:
                last_error = e
                print(f"  第{attempt}次尝试失败: {e}")
                if attempt < LLM_MAX_ATTEMPTS:
                    time.sleep(2 * attempt)

        raise last_error

    def analyze_repo(self, repo: Dict[str, Any]) -> Dict[str, str]:
        """使用LLM分析仓库"""
        repo_name = repo["full_name"]
        description = repo.get("description", "")
        topics = repo.get("topics", [])
        language = repo.get("language", "")
        homepage = repo.get("homepage", "")
        repo_id = str(repo["id"])  # 转换为字符串，因为JSON的key是字符串

        print(f"正在分析: {repo_name}")

        common_tags = self._common_tags(PROMPT_TAG_LIMIT)

        # 构建分析提示
        prompt = f"""请分析以下GitHub仓库，用中文回答。

仓库名: {repo_name}
描述: {description}
编程语言: {language}
标签: {', '.join(topics) if topics else '无'}
主页: {homepage if homepage else '无'}

常用标签（tags 请优先从中选择，没有合适的再自拟）: {', '.join(common_tags) if common_tags else '无'}

请提供以下信息（JSON格式）:
{{
    "description": "用一句话描述这个仓库是做什么的",
    "category": "仓库分类，请选择以下之一: {', '.join(CATEGORIES)}",
    "tags": ["标签1", "标签2"],
    "use_case": "简述使用场景"
}}

只返回JSON，不要有其他内容。"""

        try:
            analysis = self._request_analysis(prompt)

            # 补充原始信息
            analysis.update(self._build_meta(repo))

            # 保存到已处理列表（内存中）
            self.processed_stars[repo_id] = analysis
            # 注意：不在这里写入文件，统一在最后保存

            print(f"分析完成: {repo_name} -> {analysis.get('category')}")
            time.sleep(0.5)  # 避免触发限流

            return analysis

        except Exception as e:
            print(f"分析 {repo_name} 时出错: {e}")
            # 返回基础信息
            return {
                "description": description or "无描述",
                "category": DEFAULT_CATEGORY,
                "tags": topics if topics else [],
                "use_case": "",
                **self._build_meta(repo)
            }

    def cleanup_removed_stars(self, current_stars: List[Dict[str, Any]]) -> bool:
        """清理已经取消star的仓库（只修改内存，不立即写入文件）

        Returns:
            bool: 是否有数据被清理
        """
        current_ids = {str(repo["id"]) for repo in current_stars}  # 转换为字符串
        processed_ids = set(self.processed_stars.keys())

        removed_ids = processed_ids - current_ids
        if removed_ids:
            print(f"发现 {len(removed_ids)} 个已取消star的仓库，将从缓存中移除...")
            for repo_id in removed_ids:
                del self.processed_stars[repo_id]
            return True
        return False

    def generate_markdown(self, repos: List[Dict[str, Any]]) -> str:
        """生成markdown文档"""
        # 按分类分组
        categories: Dict[str, List[Dict[str, Any]]] = {}

        for repo in repos:
            category = repo.get("category", DEFAULT_CATEGORY)
            if category not in CATEGORIES:
                category = DEFAULT_CATEGORY
            if category not in categories:
                categories[category] = []
            categories[category].append(repo)

        category_order = CATEGORIES

        # 收集所有标签（合并大小写、空格、连字符不同的写法）
        tag_display = self._build_tag_display(repos)
        all_tags = self._count_tags(repos)

        # 按标签使用次数排序
        sorted_tags = sorted(all_tags.items(), key=lambda x: len(x[1]), reverse=True)

        # 只有前 TAG_DETAIL_LIMIT 个标签生成详情和锚点，锚点重复时追加序号
        linked_tags = sorted_tags[:TAG_DETAIL_LIMIT]
        tag_anchors: Dict[str, str] = {}
        for tag, _ in linked_tags:
            base = anchor = self._slugify("tag-" + tag).lower()
            suffix = 2
            while anchor in tag_anchors.values():
                anchor = f"{base}-{suffix}"
                suffix += 1
            tag_anchors[tag] = anchor

        # 生成markdown
        lines = [
            "# 我的 GitHub Star 收藏 :star:\n",
            f"> 最后更新: {datetime.now(DISPLAY_TZ).strftime('%Y-%m-%d %H:%M:%S')} | ",
            f"总计: **{len(repos)}** 个仓库 | ",
            f"分类: **{len(categories)}** 个 | ",
            f"标签: **{len(all_tags)}** 个\n",
            "\n---\n"
        ]

        # 分类目录
        lines.append("## :open_file_folder: 分类目录\n\n")
        lines.append("| 分类 | 数量 | 分类 | 数量 |\n")
        lines.append("|------|------|------|------|\n")

        # 两列布局 - 确保表格行连续（无空行）
        active_cats = [cat for cat in category_order if cat in categories]
        for i in range(0, len(active_cats), 2):
            cat1 = active_cats[i]
            count1 = len(categories[cat1])
            col1 = f"[{cat1}](#{self._slugify(cat1).lower()})"

            if i + 1 < len(active_cats):
                cat2 = active_cats[i + 1]
                count2 = len(categories[cat2])
                col2 = f"[{cat2}](#{self._slugify(cat2).lower()})"
            else:
                col2 = ""
                count2 = ""

            # 表格行末尾加 \n，用空字符串join避免双换行
            lines.append(f"| {col1} | {count1} | {col2} | {count2} |\n")

        lines.append("\n---\n")

        # 标签云导航
        lines.append("## :label: 标签导航\n\n")
        if linked_tags:
            # 按使用数量分组显示（无表头，但需要空表头行）
            lines.append("| | | | |\n")
            lines.append("|---|---|---|---|\n")

            # 四列布局 - 确保表格行连续（无空行）
            for i in range(0, len(linked_tags), 4):
                cols = []
                for j in range(4):
                    if i + j < len(linked_tags):
                        tag, count = linked_tags[i + j][0], len(linked_tags[i + j][1])
                        cols.append(f"[`{tag}`](#{tag_anchors[tag]}) ({count})")
                    else:
                        cols.append("")
                # 表格行末尾加 \n，用空字符串join避免双换行
                lines.append(f"| {cols[0]} | {cols[1]} | {cols[2]} | {cols[3]} |\n")

        lines.append("\n---\n")

        # 分类内容
        for category in category_order:
            if category not in categories:
                continue

            repos_in_cat = sorted(
                categories[category],
                key=lambda x: x.get("stars", 0),
                reverse=True
            )

            lines.append(f"\n## {category}\n")
            lines.append(f"<a name=\"{self._slugify(category).lower()}\"></a>\n")
            lines.append(f"**{len(repos_in_cat)}** 个仓库\n\n")

            for repo in repos_in_cat:
                # 标题行
                name = repo.get("repo_name", "Unknown")
                url = repo.get("repo_url", "")
                stars = repo.get("stars", 0)
                language = repo.get("language", "")

                lines.append(f"### [{name}]({url})")
                lines.append(f"\n**⭐ {stars}** | **{language}**\n\n")

                # 描述
                desc = repo.get("description", "")
                if desc:
                    lines.append(f"{desc}\n\n")

                # 标签（有详情的标签可点击跳转）
                tags = list(dict.fromkeys(tag_display[t] for t in repo.get("tags", [])))
                if tags:
                    tags_with_links = []
                    for tag in tags:
                        if tag in tag_anchors:
                            tags_with_links.append(f"[`{tag}`](#{tag_anchors[tag]})")
                        else:
                            tags_with_links.append(f"`{tag}`")
                    tags_str = " ".join(tags_with_links)
                    lines.append(f"标签: {tags_str}\n\n")

                # 使用场景
                use_case = repo.get("use_case", "")
                if use_case:
                    lines.append(f"**使用场景**: {use_case}\n\n")

                lines.append("---\n")

        # 标签详情部分（每个标签下的仓库列表）
        lines.append("\n---\n")
        lines.append("## :bookmark_tabs: 按标签查看\n\n")

        for tag, tag_repos in linked_tags:
            lines.append(f"\n#### `{tag}`\n")
            lines.append(f"<a name=\"{tag_anchors[tag]}\"></a>\n")
            # 按star数排序，最多显示10个
            sorted_tag_repos = sorted(tag_repos, key=lambda x: x.get("stars", 0), reverse=True)[:10]
            repo_links = []
            for r in sorted_tag_repos:
                repo_links.append(f"- [{r.get('repo_name', 'Unknown')}]({r.get('repo_url', '')}) ({r.get('stars', 0)} :star:)")
            lines.append("\n".join(repo_links))
            lines.append("\n")

        # 直接合并，因为每个元素已经包含了正确的换行
        return "".join(lines)

    def _slugify(self, text: str) -> str:
        """生成URL友好的slug"""
        text = text.lower()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s]+', '-', text)
        return text.strip('-')

    def commit_to_repo(self):
        """提交更改到GitHub仓库"""
        if not self.repo_owner or not self.repo_name:
            print("未配置REPO_OWNER和REPO_NAME，跳过提交")
            return

        print(f"正在提交到 {self.repo_owner}/{self.repo_name}...")

        # 这里可以添加git提交逻辑
        # 在GitHub Action中会自动处理

    def run(self):
        """主运行函数"""
        print("=" * 50)
        print("GitHub Star 标注器启动")
        print("=" * 50)

        # 1. 获取star列表
        current_stars = self.get_starred_repos()

        # 2. 清理已取消的star
        has_removed = self.cleanup_removed_stars(current_stars)

        # 3. 分析每个仓库
        print(f"\n开始分析 {len(current_stars)} 个仓库...")
        analyzed_repos = []
        skipped_count = 0
        new_count = 0
        need_save = False  # 标记是否需要保存

        try:
            for repo in current_stars:
                repo_id = str(repo["id"])  # 转换为字符串
                cached = self.processed_stars.get(repo_id)
                # 检查是否已处理
                if cached and cached.get("category"):
                    skipped_count += 1
                    # 刷新元数据（star数、语言、描述等），LLM 分析结果保持不变
                    meta = self._build_meta(repo)
                    if any(cached.get(k) != v for k, v in meta.items()):
                        cached.update(meta)
                        need_save = True
                    analyzed_repos.append(cached)
                    continue

                new_count += 1
                need_save = True
                analyzed_repos.append(self.analyze_repo(repo))
                if new_count % SAVE_INTERVAL == 0:
                    self._save_processed()
        finally:
            # 4. 保存缓存（只在数据有变化时保存；中途异常也会保存已完成的分析）
            if need_save or has_removed:
                print("正在保存缓存数据...")
                self._save_processed()

        print(f"\n分析完成:")
        print(f"  - 跳过已处理: {skipped_count} 个")
        print(f"  - 新分析: {new_count} 个")

        # 5. 生成markdown
        print("\n正在生成markdown文档...")
        markdown_content = self.generate_markdown(analyzed_repos)

        # 保存markdown
        self.markdown_file.parent.mkdir(exist_ok=True)
        with open(self.markdown_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        print(f"markdown已保存到: {self.markdown_file}")

        # 6. 提交到仓库
        self.commit_to_repo()

        print("=" * 50)
        print("完成!")
        print("=" * 50)


def main():
    """主入口"""
    analyzer = GitHubStarAnalyzer()
    analyzer.run()


if __name__ == "__main__":
    main()
