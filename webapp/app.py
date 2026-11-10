"""角色聊天 · DeepSeek 实时对话 + 可查看的长期记忆（基线版）。

当前是实验基线：用户消息全量写入长期记忆，简单召回注入；
不做写入门控，不做来源标识。记忆面板只读。
"""

from __future__ import annotations

import hashlib
import hmac
import html as html_lib
import json
import os
import re
import textwrap
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
import yaml
from openai import OpenAI

import memory_store

BASE = Path(__file__).resolve().parent.parent
CSS = (Path(__file__).resolve().parent / "style.css").read_text(encoding="utf-8")

st.set_page_config(
    page_title="角色聊天",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="auto",
)
st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

CHARACTERS = {
    "雾雨魔理沙": "characters/zh_cn/KirisameMarisa.yaml",
    "博丽灵梦": "characters/zh_cn/HakureiReimu.yaml",
}

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
CUSTOM_CARD_FILE = UPLOAD_DIR / "card.json"
WORLD_FILE = UPLOAD_DIR / "world.txt"


def _parse_character(raw: bytes, filename: str) -> dict:
    suffix = Path(filename).suffix.lower()
    text = raw.decode("utf-8", errors="ignore")
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        data = {"name": Path(filename).stem, "system_prompt": text}

    if not isinstance(data, dict):
        raise ValueError("角色卡必须是 YAML / JSON 对象")
    if isinstance(data.get("data"), dict):
        data = data["data"]

    name = str(data.get("name") or data.get("char_name") or Path(filename).stem)
    parts = []
    for key in ("system_prompt", "description", "personality", "scenario"):
        value = data.get(key)
        if value:
            parts.append(str(value).strip())
    if data.get("mes_example"):
        parts.append("【示例对话】\n" + str(data["mes_example"]).strip())
    system_prompt = "\n\n".join(parts) or "你是一个角色扮演助手。"

    greeting = data.get("greeting") or data.get("first_mes") or "……"
    return {"name": name, "system_prompt": system_prompt, "greeting": str(greeting)}


def _parse_world(raw: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    text = raw.decode("utf-8", errors="ignore").strip()
    if suffix == ".json":
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            chunks = []
            for entry in data["entries"].values():
                if isinstance(entry, dict):
                    content = entry.get("content") or "\n".join(entry.get("key", []))
                    if content:
                        chunks.append(str(content).strip())
            text = "\n\n".join(chunks) or text
    elif suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            chunks = []
            for entry in data["entries"].values():
                if isinstance(entry, dict):
                    content = entry.get("content") or "\n".join(entry.get("key", []))
                    if content:
                        chunks.append(str(content).strip())
            text = "\n\n".join(chunks) or text
    return text[:8000]


def _load_custom_card() -> dict | None:
    if not CUSTOM_CARD_FILE.exists():
        return None
    try:
        data = json.loads(CUSTOM_CARD_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _load_world() -> str:
    if not WORLD_FILE.exists():
        return ""
    try:
        return WORLD_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _clear_uploads() -> None:
    for path in (CUSTOM_CARD_FILE, WORLD_FILE):
        if path.exists():
            path.unlink()


CUSTOM_CARD = _load_custom_card()
WORLD_TEXT = _load_world()

CUSTOM_LABEL = None
if CUSTOM_CARD:
    CUSTOM_LABEL = str(CUSTOM_CARD.get("name") or "上传的角色")
    if CUSTOM_LABEL in CHARACTERS:
        CUSTOM_LABEL = f"{CUSTOM_LABEL}（上传）"


@st.cache_data(show_spinner=False)
def load_card(path: str) -> dict:
    data = yaml.safe_load((BASE / path).read_text(encoding="utf-8"))
    return {
        "name": data.get("name") or "角色",
        "system_prompt": data.get("system_prompt") or "你是一个角色扮演助手。",
        "greeting": data.get("greeting") or "……",
    }


@st.cache_resource(show_spinner=False)
def get_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=90.0)


def get_app_password() -> str | None:
    value = os.getenv("APP_PASSWORD")
    if value:
        return value
    try:
        if "APP_PASSWORD" in st.secrets:
            return str(st.secrets["APP_PASSWORD"])
    except Exception:
        pass
    return None


def get_api_key() -> str | None:
    for name in ("DEEPSEEK_API_KEY", "GENSOKYOAI_API_KEY"):
        value = os.getenv(name)
        if value:
            return value
    try:
        for name in ("DEEPSEEK_API_KEY", "GENSOKYOAI_API_KEY"):
            if name in st.secrets:
                return str(st.secrets[name])
    except Exception:
        pass
    return None


def format_text(text: str) -> str:
    escaped = html_lib.escape(text)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    return escaped.replace("\n", "<br>")


def user_html(text: str) -> str:
    return textwrap.dedent(
        f"""
        <div class="msg user">
          <div class="avatar">你</div>
          <div class="bubble"><div class="text">{format_text(text)}</div></div>
        </div>
        """
    )


def assistant_html(text: str, avatar: str, name: str, error: bool = False) -> str:
    meta = f"{name} · {'连接异常' if error else '实时回复'}"
    return textwrap.dedent(
        f"""
        <div class="msg assistant">
          <div class="avatar">{avatar}</div>
          <div class="bubble">
            <div class="meta">{meta}</div>
            <div class="text">{format_text(text)}</div>
          </div>
        </div>
        """
    )


def memory_html(memory: dict) -> str:
    created = str(memory.get("created_at", ""))[:16].replace("T", " ")
    return textwrap.dedent(
        f"""
        <div class="mem-head"><span class="chip active">已记住</span><span class="mem-src">第 {memory.get("turn", "?")} 轮 · {created}</span></div>
        <div class="mem-text">{html_lib.escape(str(memory.get("text", "")))}</div>
        """
    )


def stream_reply(card: dict, character: str, api_key: str) -> None:
    avatar = card["name"][0] if card["name"] else "角"
    placeholder = st.empty()
    placeholder.markdown(
        f'<div class="chat-wrap">{assistant_html("……", avatar, card["name"])}</div>',
        unsafe_allow_html=True,
    )

    components.html(
        """
        <script>
        const doc = window.parent.document;
        let n = 0;
        const timer = setInterval(() => {
          const wrap = doc.querySelector('.chat-wrap');
          let el = wrap;
          while (el && !(el.scrollHeight > el.clientHeight + 20 && getComputedStyle(el).overflowY !== 'visible')) el = el.parentElement;
          const target = el || doc.scrollingElement;
          if (target) target.scrollTop = target.scrollHeight;
          if (++n > 120) clearInterval(timer);
        }, 300);
        </script>
        """,
        height=0,
    )

    partial = ""
    user_text = ""
    try:
        memories = memory_store.load_memories(character)
        system_prompt = card["system_prompt"]
        if WORLD_TEXT:
            system_prompt += "\n\n【世界设定】\n" + WORLD_TEXT
        if memories:
            recent = [m["text"] for m in memories[-8:] if m.get("text")]
            if recent:
                system_prompt += "\n\n【你记得用户说过的事】\n" + "\n".join(
                    f"- {text}" for text in recent
                )

        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.chat
            if not m.get("error")
        ][-16:]
        if history and history[-1]["role"] == "user":
            user_text = history[-1]["content"]

        stream = get_client(api_key).chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system_prompt}, *history],
            temperature=0.85,
            top_p=0.95,
            max_tokens=800,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue
            partial += delta
            placeholder.markdown(
                f'<div class="chat-wrap">{assistant_html(partial + "▍", avatar, card["name"])}</div>',
                unsafe_allow_html=True,
            )

        reply = partial.strip() or "（没有回复）"
        st.session_state.chat.append({"role": "assistant", "content": reply})
        st.session_state.turn = st.session_state.get("turn", 0) + 1
        if user_text:
            memory_store.add_memory(character, user_text, st.session_state.turn)
    except Exception as error:  # noqa: BLE001
        st.session_state.chat.append(
            {
                "role": "assistant",
                "content": f"连接 DeepSeek 失败：{error}",
                "error": True,
            }
        )
    finally:
        st.session_state.pending = False
        placeholder.empty()
        st.rerun()


api_key = get_api_key()
st.session_state.setdefault("show_memory", True)
st.session_state.setdefault("pending", False)
st.session_state.setdefault("authed", False)

app_password = get_app_password()
if app_password and not st.session_state.authed:
    st.markdown('<h2 class="brand" style="margin-top:40px">角色聊天</h2>', unsafe_allow_html=True)
    st.markdown(
        '<div class="brand-sub">请输入访问口令后进入。</div>',
        unsafe_allow_html=True,
    )
    with st.form("login"):
        entered = st.text_input("访问口令", type="password", placeholder="输入访问口令")
        if st.form_submit_button("进入"):
            if hmac.compare_digest(entered, app_password):
                st.session_state.authed = True
                st.rerun()
            else:
                st.error("口令不正确。")
    st.stop()

# ---------------------------------------------------------------------------
# 侧边栏
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown('<h2 class="brand">角色聊天</h2>', unsafe_allow_html=True)
    st.markdown(
        '<div class="brand-sub">DeepSeek 实时对话 · 角色卡驱动</div>',
        unsafe_allow_html=True,
    )

    options = list(CHARACTERS)
    if CUSTOM_LABEL:
        options.append(CUSTOM_LABEL)

    if st.session_state.pop("switch_to_custom", False) and CUSTOM_LABEL:
        st.session_state.character = CUSTOM_LABEL
    if st.session_state.pop("switch_to_default", False):
        st.session_state.character = options[0]

    if st.session_state.get("character") not in options:
        st.session_state.character = CUSTOM_LABEL or options[0]

    character = st.selectbox("角色", options, key="character")
    card = CUSTOM_CARD if character == CUSTOM_LABEL else load_card(CHARACTERS[character])

    if st.session_state.get("chat_character") != character:
        st.session_state.chat = [{"role": "assistant", "content": card["greeting"]}]
        st.session_state.chat_character = character
        st.session_state.turn = 0

    st.markdown(
        f'<div class="cond-pill">{MODEL}</div>'
        f'<div class="cond-note">DeepSeek · {"API 已配置" if api_key else "API 未配置"}</div>',
        unsafe_allow_html=True,
    )

    memories = memory_store.load_memories(character)
    st.markdown(
        f'<div class="stat-grid" style="margin-top:12px">'
        f'<div class="stat"><div class="num">{len(memories)}</div><div class="label">长期记忆</div></div>'
        f'<div class="stat"><div class="num">{st.session_state.get("turn", 0)}</div><div class="label">本轮轮次</div></div>'
        f"</div>",
        unsafe_allow_html=True,
    )

    with st.popover("上传角色卡 / 世界书", use_container_width=True):
        st.caption("角色卡：YAML / JSON；世界书：TXT / MD / JSON / YAML。选好文件后点「确认上传」。")
        card_file = st.file_uploader(
            "角色卡", type=["yaml", "yml", "json"], key="upload_card"
        )
        world_file = st.file_uploader(
            "世界书", type=["txt", "md", "json", "yaml", "yml"], key="upload_world"
        )

        has_file = card_file is not None or world_file is not None
        if st.button(
            "确认上传",
            key="confirm_upload",
            type="primary",
            use_container_width=True,
            disabled=not has_file,
        ):
            uploaded_card = False
            if card_file is not None:
                try:
                    parsed = _parse_character(card_file.getvalue(), card_file.name)
                    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                    CUSTOM_CARD_FILE.write_text(
                        json.dumps(parsed, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    uploaded_card = True
                except Exception as error:
                    st.error(f"角色卡解析失败：{error}")

            if world_file is not None:
                try:
                    text = _parse_world(world_file.getvalue(), world_file.name)
                    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                    WORLD_FILE.write_text(text, encoding="utf-8")
                except Exception as error:
                    st.error(f"世界书解析失败：{error}")

            if uploaded_card:
                st.session_state.switch_to_custom = True
            if uploaded_card or world_file is not None:
                st.rerun()

        if CUSTOM_CARD or WORLD_TEXT:
            if st.button("移除上传内容", key="clear_uploads", use_container_width=True):
                _clear_uploads()
                st.session_state.switch_to_default = True
                st.rerun()

    st.markdown(
        f'<div class="cond-note" style="margin-top:10px">'
        f'角色卡：{"上传 · " + CUSTOM_CARD["name"] if CUSTOM_CARD else "内置"}<br>'
        f'世界书：{"已加载 · " + str(len(WORLD_TEXT)) + " 字" if WORLD_TEXT else "未加载"}</div>',
        unsafe_allow_html=True,
    )

    with st.popover("清空对话", use_container_width=True):
        st.caption("只清空当前聊天，不清空长期记忆。")
        if st.button("确认清空对话", key="confirm_clear_chat", use_container_width=True):
            st.session_state.chat = [{"role": "assistant", "content": card["greeting"]}]
            st.session_state.turn = 0
            st.rerun()

    with st.popover("清空记忆", use_container_width=True):
        st.caption("删除这个角色的全部长期记忆，不可恢复。")
        if st.button("确认清空记忆", key="confirm_clear_memory", use_container_width=True):
            memory_store.clear_memories(character)
            st.rerun()

    st.markdown(
        '<div class="cond-note" style="margin-top:18px">'
        '当前为实验基线：用户消息全量写入，简单召回注入。<br>'
        '未接入写入门控与来源标识。</div>',
        unsafe_allow_html=True,
    )

if not api_key:
    st.warning(
        "没有找到 DeepSeek API key。请在 `.streamlit/secrets.toml` 或环境变量里配置。",
        icon="⚠️",
    )

# ---------------------------------------------------------------------------
# 主区域
# ---------------------------------------------------------------------------

head_left, head_right = st.columns([6, 1])

with head_left:
    st.markdown(
        textwrap.dedent(
            f"""
            <div class="char-header">
              <h1 class="char-name">{card["name"]}</h1>
              <div class="cond-pill">在线</div>
              <div style="font-size:12px;color:var(--muted)">{MODEL} · 实时回复</div>
            </div>
            <div style="font-size:13px;color:var(--muted);margin-bottom:16px">
              和角色聊天；长期记忆面板可查看它记住了什么。
            </div>
            """
        ),
        unsafe_allow_html=True,
    )

with head_right:
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    toggle_label = "隐藏记忆面板" if st.session_state.show_memory else "显示记忆面板"
    if st.button(toggle_label, key="toggle_memory", use_container_width=True):
        st.session_state.show_memory = not st.session_state.show_memory
        st.rerun()

if st.session_state.show_memory:
    chat_col, mem_col = st.columns([2, 1], gap="large")
else:
    chat_col = st.container()
    mem_col = None

with chat_col:
    avatar = card["name"][0] if card["name"] else "角"
    parts = ['<div class="chat-wrap">']
    for message in st.session_state.chat:
        if message["role"] == "user":
            parts.append(user_html(message["content"]))
        else:
            parts.append(
                assistant_html(
                    message["content"],
                    avatar,
                    card["name"],
                    error=bool(message.get("error")),
                )
            )
    parts.append("</div>")

    st.markdown("".join(parts), unsafe_allow_html=True)

    if st.session_state.get("pending"):
        stream_reply(card, character, api_key)

    components.html(
        """
        <script>
        const doc = window.parent.document;
        doc.documentElement.lang = 'zh-CN';
        const wrap = doc.querySelector('.chat-wrap');
        if (wrap) {
          let el = wrap.parentElement;
          while (el && !(el.scrollHeight > el.clientHeight + 20 && getComputedStyle(el).overflowY !== 'visible')) el = el.parentElement;
          const target = el || doc.scrollingElement;
          if (target) target.scrollTop = target.scrollHeight;
        }
        </script>
        """,
        height=0,
    )

    with st.form("composer", clear_on_submit=True, border=False):
        input_col, send_col = st.columns([6, 1])
        prompt = input_col.text_input(
            "消息",
            placeholder=f"和{card['name']}说点什么……",
            label_visibility="collapsed",
            disabled=not api_key,
        )
        submitted = send_col.form_submit_button(
            "发送", use_container_width=True, disabled=not api_key
        )

    if submitted and prompt.strip():
        st.session_state.chat.append({"role": "user", "content": prompt.strip()})
        st.session_state.pending = True
        st.rerun()


# ---------------------------------------------------------------------------
# 记忆面板（只读，基线：无门控、无来源）
# ---------------------------------------------------------------------------

if st.session_state.show_memory and mem_col is not None:
    with mem_col:
        st.markdown('<h2 class="section-title">长期记忆</h2>', unsafe_allow_html=True)
        st.markdown(
            '<div class="section-sub">全量写入 · 简单召回 · 无门控 · 无来源</div>',
            unsafe_allow_html=True,
        )

        memories = memory_store.load_memories(character)
        if not memories:
            st.markdown(
                '<div class="empty">还没有记忆。聊几句后，用户消息会被全量写入这里。</div>',
                unsafe_allow_html=True,
            )
        else:
            for memory in reversed(memories[-20:]):
                with st.container(border=True):
                    st.markdown(memory_html(memory), unsafe_allow_html=True)
            st.caption("只读视图：当前版本不提供确认 / 纠正 / 来源追溯。")
