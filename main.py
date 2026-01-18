#!/usr/bin/env python3
"""
GitHub Star 标注器
定时拉取用户的star列表，使用LLM分析仓库并生成分类的markdown文件
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI

# 加载环境变量
load_dotenv()


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
        self.stars_file = self.data_dir / "stars.json"
        self.processed_file = self.data_dir / "processed.json"
        self.markdown_file = Path("README.md")  # 输出到根目录
        self.setup_file = Path("SETUP.md")  # 项目说明文档

        # 加载已处理的数据
        self.processed_stars = self._load_processed()

    def _load_processed(self) -> Dict[str, Any]:
        """加载已处理的star数据"""
        if self.processed_file.exists():
            with open(self.processed_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_processed(self):
        """保存已处理的star数据"""
        with open(self.processed_file, "w", encoding="utf-8") as f:
            json.dump(self.processed_stars, f, ensure_ascii=False, indent=2)

    def _github_api_request(self, url: str, params: Optional[Dict] = None) -> Any:
        """GitHub API 请求"""
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_starred_repos(self) -> List[Dict[str, Any]]:
        """获取用户star的所有仓库"""
        print("正在获取star列表...")
        stars = []
        page = 1
        per_page = 100

        while True:
            try:
                url = f"https://api.github.com/user/starred"
                params = {"page": page, "per_page": per_page}
                data = self._github_api_request(url, params)

                if not data:
                    break

                stars.extend(data)
                print(f"已获取 {len(stars)} 个star...")
                page += 1
                time.sleep(0.1)  # 避免触发限流

            except requests.exceptions.RequestException as e:
                print(f"获取star列表时出错: {e}")
                break

        print(f"总共获取到 {len(stars)} 个star")
        return stars

    def analyze_repo(self, repo: Dict[str, Any]) -> Dict[str, str]:
        """使用LLM分析仓库"""
        repo_name = repo["full_name"]
        description = repo.get("description", "")
        topics = repo.get("topics", [])
        language = repo.get("language", "")
        homepage = repo.get("homepage", "")

        # 如果已经处理过且有描述，跳过
        repo_id = repo["id"]
        if repo_id in self.processed_stars and self.processed_stars[repo_id].get("description"):
            print(f"跳过已处理: {repo_name}")
            return self.processed_stars[repo_id]

        print(f"正在分析: {repo_name}")

        # 构建分析提示
        prompt = f"""请分析以下GitHub仓库，用中文回答。

仓库名: {repo_name}
描述: {description}
编程语言: {language}
标签: {', '.join(topics) if topics else '无'}
主页: {homepage if homepage else '无'}

请提供以下信息（JSON格式）:
{{
    "description": "用一句话描述这个仓库是做什么的",
    "category": "仓库分类，请选择以下之一: AI/机器学习, Web开发, 移动开发, 数据库, 工具/库, 框架, DevOps/基础设施, 游戏, 教育, 其他",
    "tags": ["标签1", "标签2"],
    "use_case": "简述使用场景"
}}

只返回JSON，不要有其他内容。"""

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

            result_text = response.choices[0].message.content.strip()

            # 清理可能的markdown标记
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            result_text = result_text.strip()

            analysis = json.loads(result_text)

            # 补充原始信息
            analysis.update({
                "repo_name": repo_name,
                "repo_url": repo["html_url"],
                "language": language,
                "stars": repo["stargazers_count"],
                "starred_at": repo.get("starred_at", ""),
                "original_description": description
            })

            # 保存到已处理列表
            self.processed_stars[repo_id] = analysis
            self._save_processed()

            print(f"分析完成: {repo_name} -> {analysis.get('category')}")
            time.sleep(0.5)  # 避免触发限流

            return analysis

        except Exception as e:
            print(f"分析 {repo_name} 时出错: {e}")
            # 返回基础信息
            return {
                "description": description or "无描述",
                "category": "其他",
                "tags": topics if topics else [],
                "use_case": "",
                "repo_name": repo_name,
                "repo_url": repo["html_url"],
                "language": language,
                "stars": repo["stargazers_count"],
                "starred_at": repo.get("starred_at", ""),
                "original_description": description
            }

    def cleanup_removed_stars(self, current_stars: List[Dict[str, Any]]):
        """清理已经取消star的仓库"""
        current_ids = {repo["id"] for repo in current_stars}
        processed_ids = set(self.processed_stars.keys())

        removed_ids = processed_ids - current_ids
        if removed_ids:
            print(f"发现 {len(removed_ids)} 个已取消star的仓库")
            for repo_id in removed_ids:
                del self.processed_stars[repo_id]

            self._save_processed()

    def generate_markdown(self, repos: List[Dict[str, Any]]) -> str:
        """生成markdown文档"""
        # 按分类分组
        categories: Dict[str, List[Dict[str, Any]]] = {}
        # 收集所有标签
        all_tags: Dict[str, List[Dict[str, Any]]] = {}

        for repo in repos:
            category = repo.get("category", "其他")
            if category not in categories:
                categories[category] = []
            categories[category].append(repo)

            # 收集标签
            tags = repo.get("tags", [])
            for tag in tags:
                if tag not in all_tags:
                    all_tags[tag] = []
                all_tags[tag].append(repo)

        # 排序
        category_order = [
            "AI/机器学习", "Web开发", "移动开发", "框架",
            "数据库", "工具/库", "DevOps/基础设施", "游戏", "教育", "其他"
        ]

        # 按标签使用次数排序
        sorted_tags = sorted(all_tags.items(), key=lambda x: len(x[1]), reverse=True)

        # 生成markdown
        lines = [
            "# 我的 GitHub Star 收藏 :star:\n",
            f"> 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | ",
            f"总计: **{len(repos)}** 个仓库 | ",
            f"分类: **{len(categories)}** 个 | ",
            f"标签: **{len(all_tags)}** 个\n",
            "\n---\n"
        ]

        # 分类目录
        lines.append("## :open_file_folder: 分类目录\n")
        for cat in category_order:
            if cat in categories:
                count = len(categories[cat])
                lines.append(f"| [{cat}](#{self._slugify(cat).lower()}) | {count} |")
        lines.append("\n---\n")

        # 标签云导航
        lines.append("## :label: 标签导航\n\n")
        if sorted_tags:
            # 按使用数量分组显示
            lines.append("| 标签 | 数量 | 标签 | 数量 |\n")
            lines.append("|------|------|------|------|\n")

            # 两列布局
            for i in range(0, len(sorted_tags), 2):
                tag1, count1 = sorted_tags[i][0], len(sorted_tags[i][1])
                tag_link1 = f"#{self._slugify('tag-' + tag1).lower()}"
                col1 = f"[`{tag1}`]({tag_link1}) ({count1})"

                if i + 1 < len(sorted_tags):
                    tag2, count2 = sorted_tags[i + 1][0], len(sorted_tags[i + 1][1])
                    tag_link2 = f"#{self._slugify('tag-' + tag2).lower()}"
                    col2 = f"[`{tag2}`]({tag_link2}) ({count2})"
                else:
                    col2 = ""

                lines.append(f"| {col1} | {col2} |\n")

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

                # 标签（可点击跳转）
                tags = repo.get("tags", [])
                if tags:
                    tags_with_links = []
                    for tag in tags:
                        tag_anchor = f"#{self._slugify('tag-' + tag).lower()}"
                        tags_with_links.append(f"[`{tag}`]({tag_anchor})")
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

        for tag, tag_repos in sorted_tags[:50]:  # 只显示前50个标签
            lines.append(f"\n#### `{tag}`\n")
            lines.append(f"<a name=\"{self._slugify('tag-' + tag).lower()}\"></a>\n")
            # 按star数排序，最多显示10个
            sorted_tag_repos = sorted(tag_repos, key=lambda x: x.get("stars", 0), reverse=True)[:10]
            repo_links = []
            for r in sorted_tag_repos:
                repo_links.append(f"- [{r.get('repo_name', 'Unknown')}]({r.get('repo_url', '')}) ({r.get('stars', 0)} :star:)")
            lines.append("\n".join(repo_links))
            lines.append("\n")

        return "\n".join(lines)

    def _slugify(self, text: str) -> str:
        """生成URL友好的slug"""
        import re
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
        self.cleanup_removed_stars(current_stars)

        # 3. 分析每个仓库
        analyzed_repos = []
        for repo in current_stars:
            analysis = self.analyze_repo(repo)
            analyzed_repos.append(analysis)

        # 4. 生成markdown
        print("正在生成markdown文档...")
        markdown_content = self.generate_markdown(analyzed_repos)

        # 保存markdown
        self.markdown_file.parent.mkdir(exist_ok=True)
        with open(self.markdown_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        print(f"markdown已保存到: {self.markdown_file}")

        # 5. 提交到仓库
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
