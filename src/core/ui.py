"""Reusable Streamlit UI widgets shared by every file-based feature."""

from __future__ import annotations

from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Iterator, List, Optional

import streamlit as st
from langchain_core.runnables import Runnable

from src.core.schemas import DataSource
from src.core.storage import StoredUpload, store_upload, upload_collection_name

if TYPE_CHECKING:
    from src.features import FeatureSpec


ASSISTANT_AVATAR = ":material/balance:"

# Colours are translucent greys so the same rules read well under both the
# light and dark themes in .streamlit/config.toml.
_CHAT_CSS = """
<style>
/* Hide Streamlit chrome / branding (footer, deploy, decoration bar). */
#MainMenu, footer, header a, .stDeployButton,
[data-testid="stDecoration"], [data-testid="stStatusWidget"],
[data-testid="stToolbar"], [data-testid="manageAppButton"],
[data-testid="stHeaderActionElements"] { display: none !important; visibility: hidden !important; }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] { padding-top: 2.5rem; padding-bottom: 7rem; }

[data-testid="stChatMessage"] { background: transparent; padding: 0.5rem 0; gap: 0.75rem; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    flex-direction: row-reverse;
}
[data-testid="stChatMessageAvatarUser"] { display: none; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
    [data-testid="stChatMessageContent"] {
    flex: 0 1 auto;
    max-width: 75%;
    margin-left: auto;
    margin-right: 0;
    padding: 0.6rem 1.1rem;
    border-radius: 1.5rem;
    background: rgba(128, 128, 128, 0.14);
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
    [data-testid="stChatMessageContent"] p:last-child { margin-bottom: 0; }

[data-testid="stChatInput"] { border-radius: 1.75rem; }
[data-testid="stChatInput"] textarea { padding-left: 0.5rem; }

.chat-welcome { text-align: center; margin: 6vh 0 1.5rem; }
.chat-welcome h2 { font-weight: 600; padding: 0; }
.chat-welcome p { opacity: 0.65; margin-top: 0.25rem; }

[class*="__suggestions"] button {
    justify-content: flex-start;
    text-align: left;
    min-height: 3.25rem;
    border-radius: 1rem;
}
[class*="__suggestions"] button p { font-size: 0.9rem; opacity: 0.85; }

[class*="st-key-new_chat"] button,
[class*="st-key-new_chat"] button > div { justify-content: flex-start; }
</style>
"""


def apply_chat_style() -> None:
    """Inject the ChatGPT-style CSS. Call once per run from the entry point."""
    st.html(_CHAT_CSS)


def page_header(spec: "FeatureSpec") -> None:
    st.markdown(f"#### {spec.title}")


def new_chat_button(*state_keys: str) -> None:
    """Sidebar "New chat" button that clears the given session-state keys."""
    if st.sidebar.button(
        "New chat",
        icon=":material/edit_square:",
        width="stretch",
        key=f"new_chat__{'_'.join(state_keys)}",
    ):
        for k in state_keys:
            st.session_state.pop(k, None)
            st.session_state.pop(f"{k}__pending", None)
        st.rerun()


def welcome(spec: "FeatureSpec", history_key: str, greeting: str = "What can I help with?") -> None:
    """Empty-chat landing view: greeting plus clickable starter prompts."""
    st.html(
        f'<div class="chat-welcome"><h2>{greeting}</h2>'
        f"<p>{spec.description}</p></div>"
    )
    if not spec.suggestions:
        return
    with st.container(key=f"{history_key}__suggestions"):
        cols = st.columns(2)
        for i, text in enumerate(spec.suggestions):
            cols[i % 2].button(
                text,
                key=f"{history_key}__suggest_{i}",
                width="stretch",
                on_click=st.session_state.__setitem__,
                args=(f"{history_key}__pending", text),
            )


def take_prompt(history_key: str, placeholder: str) -> Optional[str]:
    """Return the text typed into the chat box, or a clicked suggestion."""
    typed = st.chat_input(placeholder, key=f"{history_key}__input")
    return typed or st.session_state.pop(f"{history_key}__pending", None)


def _message_text(chunks: Iterable[Any]) -> Iterator[str]:
    for chunk in chunks:
        text = getattr(chunk, "content", chunk)
        if text:
            yield text


def stream_answer(runnable: Runnable, inputs: Dict[str, Any]) -> str:
    """Stream an LLM chain's reply into the current container, token by token."""
    stream = _message_text(runnable.stream(inputs))
    with st.spinner("Thinking..."):
        first = next(stream, "")
    return st.write_stream(chain([first], stream))


def chat(
    spec: "FeatureSpec",
    history_key: str,
    build_chain: Callable[[], Runnable],
    placeholder: str,
) -> None:
    """
    ChatGPT-style conversation: history, welcome screen when empty, and a
    streamed assistant reply. ``build_chain`` must return a runnable that
    takes ``{"question": ...}`` and streams message chunks.
    """
    history: List[Dict[str, str]] = st.session_state.setdefault(history_key, [])

    for msg in history:
        avatar = ASSISTANT_AVATAR if msg["role"] == "assistant" else None
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # Reserved above the input so new turns stay in order when the chat is
    # rendered inline (e.g. inside a tab) instead of pinned to the bottom.
    body = st.container()
    question = take_prompt(history_key, placeholder)

    if not question:
        if not history:
            with body:
                welcome(spec, history_key)
        return

    with body:
        history.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            try:
                answer = stream_answer(build_chain(), {"question": question})
            except Exception as exc:  # noqa: BLE001
                answer = f"Error: {exc}"
                st.error(answer)
        history.append({"role": "assistant", "content": answer})


def save_upload(feature_key: str, uploaded) -> tuple[StoredUpload, str]:
    """
    Store a Streamlit upload in Blob Storage once per session.

    Streamlit reruns the page on every interaction; without this the same
    file would be re-sent to the blob container each time.
    """
    data = uploaded.getvalue()
    collection = upload_collection_name(uploaded.name, data)
    cache: dict = st.session_state.setdefault("_stored_uploads", {})
    key = (feature_key, collection)
    stored = cache.get(key)
    if stored is None or not stored.local_path.exists():
        stored = store_upload(
            feature=feature_key,
            filename=uploaded.name,
            data=data,
            collection_name=collection,
            content_type=uploaded.type,
        )
        cache[key] = stored
    return stored, collection


def _list_existing(folder: Path, suffixes: List[str]) -> List[Path]:
    if not folder or not folder.exists():
        return []
    files: List[Path] = []
    for suffix in suffixes:
        files.extend(sorted(folder.glob(f"*.{suffix}")))
    return [f for f in files if f.is_file()]


def source_picker(spec: "FeatureSpec") -> Optional[DataSource]:
    """
    Sidebar document source: every stored document for the feature, or the
    user's own file once they upload one.

    Returns ``None`` only when there is nothing to search (an empty data
    folder and no upload). Pages should short-circuit on ``None``.
    """
    if not spec.data_folder:
        st.sidebar.info("This feature does not use local files.")
        return None

    spec.data_folder.mkdir(parents=True, exist_ok=True)

    source = _pick_source(spec)
    if source is not None and source.files:
        with st.sidebar.expander(f"Searching: {source.label}", expanded=False):
            for f in source.files[:50]:
                st.markdown(f"- `{f.name}`")
            if len(source.files) > 50:
                st.caption(f"... and {len(source.files) - 50} more.")
    return source


def _pick_source(spec: "FeatureSpec") -> Optional[DataSource]:
    st.sidebar.markdown("**Documents**")

    uploaded = st.sidebar.file_uploader(
        "Upload your own document (optional)",
        type=spec.supported_uploads or ["pdf"],
        accept_multiple_files=False,
        key=f"{spec.key}__upload",
        help="Without an upload, answers come from all stored documents.",
    )

    if uploaded is not None:
        try:
            stored, collection = save_upload(spec.key, uploaded)
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"Could not store the upload: {exc}")
        else:
            return DataSource(
                files=[stored.local_path],
                collection_name=collection,
                is_upload=True,
                label=f"your upload `{stored.filename}`",
            )

    existing = _list_existing(spec.data_folder, spec.supported_uploads or ["pdf"])
    if not existing:
        st.sidebar.warning("No stored documents yet. Upload one to get started.")
        return None

    return DataSource(
        files=existing,
        collection_name=spec.default_collection,
        is_upload=False,
        label=f"all {len(existing)} documents",
    )
