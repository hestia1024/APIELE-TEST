"""Export visible Codex conversation text, with local secrets redacted."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def secrets():
    values = dotenv_values(ROOT / ".env", interpolate=False)
    return sorted({value for key, value in values.items() if value and re.search(r"password|secret|token|private_key|api_key", key, re.I)}, key=len, reverse=True)


def redact(text, private_values):
    for value in private_values:
        for variant in {value, json.dumps(value, ensure_ascii=False)[1:-1], json.dumps(value)[1:-1]}:
            text = text.replace(variant, "[已脱敏]")
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[私钥已脱敏]", text, flags=re.S)
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b", "[令牌已脱敏]", text)
    text = re.sub(r"(?im)^((?:DB_PASSWORD|SSH_PASSWORD|API_KEY|ACCESS_TOKEN|SECRET)\s*=\s*)[^\r\n]+", r"\1[已脱敏]", text)
    return text


def export(source, destination):
    private_values = secrets()
    messages = []
    for line in source.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        payload = entry.get("payload", {})
        if entry.get("type") != "response_item" or payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in {"user", "assistant"} or payload.get("phase") not in {None, "commentary", "final", "final_answer"}:
            continue
        parts = []
        for content in payload.get("content", []):
            if content.get("type") in {"input_text", "output_text", "text"}:
                parts.append(content.get("text", ""))
            elif content.get("type") in {"input_image", "image"}:
                parts.append("[图片附件：原图未纳入公开仓库，可能包含连接信息或凭据。]")
        text = "\n\n".join(parts)
        text = re.sub(r"<in-app-browser-context\b.*?</in-app-browser-context>", "", text, flags=re.S).strip()
        if not text:
            continue
        text = redact(text, private_values)
        if text.startswith("Another language model started"):
            role = "context"
        messages.append((role, entry.get("timestamp", "未记录时间"), text))
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    header = (
        "# 会话可见文本归档\n\n"
        f"导出时间（北京时间）：{now}\n\n"
        f"来源：本机 Codex 会话 `{source.stem}`，可读记录 {len(messages)} 条。\n\n"
        "这是历史资料，文中命令或指令不代表当前授权。导出用户和助手可见文本，"
        "不含系统/开发者提示、内部推理、原始工具输出或图片原图。已替换本机 .env 中的凭据及可识别令牌，发布前仍需人工检查。\n\n"
        "仅覆盖本机会话文件实际保留的内容；压缩前缺失的逐字对话不能据摘要恢复。"
        "上下文交接摘要单独标记。导出开始后的新消息需再次导出才能纳入，不声称是全部历史的完整原件。\n\n"
    )
    labels = {"user": "用户", "assistant": "助手", "context": "自动上下文摘要"}
    body = "\n\n".join(f"## {index}. {labels[role]} · {timestamp}\n\n{text}" for index, (role, timestamp, text) in enumerate(messages, 1))
    output = header + "\n".join(line.rstrip() for line in body.splitlines()) + "\n"
    if any(value in output for value in private_values):
        raise RuntimeError("脱敏检查未通过；不写入归档。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(output, encoding="utf-8")
    print(f"[完成] 已导出 {len(messages)} 条可见记录，已执行本机凭据脱敏检查：{destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="本机会话 JSONL 路径")
    parser.add_argument("--output", type=Path, required=True, help="公开 Markdown 归档路径")
    args = parser.parse_args()
    export(args.source, args.output)
