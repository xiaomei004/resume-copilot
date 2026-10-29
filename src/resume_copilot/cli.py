"""命令行入口。

    resume-copilot doctor                 # 自检：key / 依赖 / soffice / 检索
    resume-copilot agents                 # 看各 Agent 的角色与权限
    resume-copilot run --jd a.txt --resume old.pdf --info note.md
    resume-copilot run --dir ./materials  # 目录自动分类（文件名含 jd/简历 即可）
    resume-copilot serve                  # 起 Web 界面
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, agents
from .config import Config
from .ingest import collect_dir, load_sources
from .llm import LLM, LLMError
from .pipeline import prepare_inputs, run
from .render import capabilities

BANNER = "resume-copilot · 多 Agent 简历优化流水线"


def _ensure_utf8() -> None:
    """Windows 控制台默认 GBK，直接 print 中文/符号会炸；能改就改成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def _print_step(record: dict) -> None:
    mark = {"ok": "✓", "skip": "→", "fail": "✗"}.get(record.get("status", "ok"), "·")
    detail = f" — {record['detail']}" if record.get("detail") else ""
    print(f"  {mark} {record['title']}{detail}")


def cmd_doctor(args) -> int:
    cfg = Config.from_env(args.env)
    caps = capabilities(cfg.soffice)
    print(BANNER, f"v{__version__}\n")
    rows = [
        ("配置文件", args.env if Path(args.env).is_file() else "未找到 .env（可用环境变量）"),
        ("API Key", cfg.masked_key()),
        ("模型", f"{cfg.model} @ {cfg.base_url}"),
        ("视觉模型", cfg.vision_model or "未配置（图片版 JD 将跳过）"),
        ("联网检索", "已启用 Tavily" if cfg.research_ready else "未配置，检索环节自动降级"),
        ("LibreOffice", caps["soffice"] or "未找到（无法校验页数/出 PDF）"),
        ("PDF 读取", "pymupdf 可用" if caps["pdf_read"] else "未安装 pymupdf"),
        ("输出目录", str(cfg.out_dir.resolve())),
    ]
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        print(f"  {key.ljust(width)} : {value}")

    print("\n依赖检查：")
    for module in ("docx", "fastapi", "uvicorn", "PIL", "pymupdf"):
        try:
            __import__(module)
            print(f"  ✓ {module}")
        except ImportError:
            hint = {
                "docx": "pip install python-docx",
                "fastapi": "pip install 'resume-copilot[web]'",
                "uvicorn": "pip install 'resume-copilot[web]'",
                "PIL": "pip install 'resume-copilot[image]'",
                "pymupdf": "pip install 'resume-copilot[pdf]'",
            }[module]
            print(f"  ✗ {module}（{hint}）")

    if not cfg.has_key:
        print("\n⚠ 未检测到 OPENAI_API_KEY。可以：")
        print("  1) 复制 .env.example 为 .env 并填入你的 key（任何 OpenAI 兼容服务都行）")
        print("  2) 先跑离线演示：resume-copilot run --mock --dir ./examples/materials")
        return 1
    try:
        info = LLM(cfg).ping()
        print(f"\n连通性：✓ {info['model']} 回复 {info['reply'][:20]!r}")
    except LLMError as exc:
        print(f"\n连通性：✗ {exc}")
        return 1
    return 0


def cmd_agents(args) -> int:
    print(BANNER, f"v{__version__}\n")
    print(f"{'Agent':<16}{'prompt':<22}权限")
    print("-" * 96)
    for spec in agents.ALL_AGENTS:
        print(f"{spec.title:<14}{spec.prompt_file:<24}{', '.join(spec.permissions)}")
        if spec.note:
            print(f"{'':<14}{spec.note}")
    print("\n原则：能上网的不写简历，写简历的不上网 —— 杜绝把检索到的漂亮话直接抄进简历。")
    return 0


def cmd_run(args) -> int:
    cfg = Config.from_env(args.env)
    if args.out:
        cfg.out_dir = Path(args.out)
    if args.no_research:
        cfg.research_enabled = False
    if args.rounds is not None:
        cfg.max_revision_rounds = args.rounds

    try:
        if args.dir:
            buckets = collect_dir(args.dir)
            jd_sources, resume_sources, info_sources = buckets["jd"], buckets["resume"], buckets["info"]
            if not jd_sources:
                print(f"✗ {args.dir} 里没找到 JD（文件名请包含 jd / 岗位 / 招聘）", file=sys.stderr)
                return 2
        else:
            jd_sources = load_sources(args.jd or [], "jd")
            resume_sources = load_sources(args.resume or [], "resume")
            info_sources = load_sources(args.info or [], "info")
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 读取输入失败：{exc}", file=sys.stderr)
        return 2

    inputs = prepare_inputs(jd_sources, resume_sources, info_sources, args.role)

    mock = None
    if args.mock:
        path = Path(args.mock_fixtures)
        if not path.is_file():
            print(f"✗ mock 需要 fixtures 文件：{path}", file=sys.stderr)
            return 2
        mock = json.loads(path.read_text(encoding="utf-8"))
        print(BANNER, "（离线演示模式，不消耗 token）\n")
    else:
        print(BANNER, f"\n模型：{cfg.model} @ {cfg.base_url}")
    print(f"输入：JD {len(jd_sources)} 份 / 旧简历 {len(resume_sources)} 份 / 补充 {len(info_sources)} 份\n")

    try:
        result = run(
            cfg,
            inputs,
            photo=args.photo,
            theme_name=args.theme,
            on_step=_print_step,
            mock_fixtures=mock,
        )
    except LLMError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        print("  提示：先跑 resume-copilot doctor 检查 key 与网络。", file=sys.stderr)
        return 1

    manifest = result["manifest"]
    print(f"\n状态：{manifest['status']}")
    if manifest.get("error"):
        print(f"错误：{manifest['error']}")
    art = manifest["artifacts"]
    for label, key in (("简历 DOCX", "resume_docx"), ("简历 PDF", "resume_pdf"), ("预览图", "resume_png"), ("速查卡", "interview_card"), ("报告", "report")):
        if art.get(key):
            print(f"  {label:<8} {art[key]}")
    metrics = manifest.get("metrics", {})
    print(f"要点 {metrics.get('bullets')} 条｜页数 {metrics.get('pages')}｜关键词覆盖 {metrics.get('keyword_coverage')}")
    print(f"token：{manifest['usage']['total_tokens']}（{manifest['usage']['calls']} 次调用）")
    print(f"工作目录：{result['root']}")
    return 0 if manifest["status"] == "done" else 1


def cmd_serve(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print("✗ 需要 Web 依赖：pip install 'resume-copilot[web]'", file=sys.stderr)
        return 2
    print(f"{BANNER}\nWeb 界面：http://{args.host}:{args.port}\n")
    uvicorn.run("resume_copilot.web.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resume-copilot", description=BANNER, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"resume-copilot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="自检环境与密钥")
    p_doctor.add_argument("--env", default=".env")
    p_doctor.set_defaults(func=cmd_doctor)

    p_agents = sub.add_parser("agents", help="列出 Agent 角色与权限")
    p_agents.set_defaults(func=cmd_agents)

    p_run = sub.add_parser("run", help="跑一次简历优化")
    p_run.add_argument("--jd", nargs="+", help="JD 文件（txt/md/docx/pdf/图片），可多份")
    p_run.add_argument("--resume", nargs="+", help="旧简历，可多份")
    p_run.add_argument("--info", nargs="*", help="补充信息（手写笔记、成绩单等）")
    p_run.add_argument("--dir", help="材料目录：按文件名自动分成 jd / 简历 / 其他")
    p_run.add_argument("--role", default="", help="岗位方向提示，如 '客户经理' / '后端开发'")
    p_run.add_argument("--photo", help="证件照路径（可选，不给就不放照片）")
    p_run.add_argument("--theme", help="主题：navy / teal / brick / mono")
    p_run.add_argument("--out", help="输出目录（默认 ./out）")
    p_run.add_argument("--env", default=".env")
    p_run.add_argument("--rounds", type=int, help="质检-修订最大轮数（默认 2）")
    p_run.add_argument("--no-research", action="store_true", help="强制关闭联网检索")
    p_run.add_argument("--mock", action="store_true", help="离线演示，不调用真实模型")
    p_run.add_argument("--mock-fixtures", default="examples/mock/fixtures.json", help="mock 用的预置输出")
    p_run.set_defaults(func=cmd_run)

    p_serve = sub.add_parser("serve", help="启动 Web 界面")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run" and not args.dir and not args.jd:
        parser.error("需要 --jd 或 --dir")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
