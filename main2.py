import os
import io
import json
import time
import difflib
import subprocess
import uuid
from typing import List, Dict, Any, Optional, Type

import streamlit as st
from dotenv import load_dotenv

# LangChain / LLM
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain.callbacks.base import BaseCallbackHandler

# User's original filesystem safety helper
PROJECT_ROOT = os.path.abspath(os.getcwd())
def _is_path_safe(path: str) -> bool:
    requested_path = os.path.abspath(path)
    return os.path.commonprefix([requested_path, PROJECT_ROOT]) == PROJECT_ROOT

# ---------- Load environment (.env) ----------
load_dotenv()

# ============== Custom Streamlit-aware Tools ==============
# These replace the blocking input() flows with a "propose/approve" UX.

class ProposeAndApplyFileChangeInput(BaseModel):
    path: str = Field(description="The path of the file to modify.")
    content: str = Field(description="The new, full content to write to the file.")

class UIProposeAndApplyFileChangeTool(BaseTool):
    name: str = "propose_and_apply_file_change"
    description: str = (
        "Propose a file change by returning a diff. The UI will ask the user to approve "
        "before writing to disk. Provide the final full content."
    )
    args_schema: Type[BaseModel] = ProposeAndApplyFileChangeInput

    def _run(self, path: str, content: str) -> str:
        # Never write here; just compute a diff and return a JSON payload
        if not _is_path_safe(path):
            return json.dumps({
                "type": "file_change_proposal",
                "status": "ERROR",
                "error": "Access denied. Path is outside the allowed project directory.",
                "path": path
            }, ensure_ascii=False)

        original = ""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    original = f.read()
            except Exception as e:
                return json.dumps({
                    "type": "file_change_proposal",
                    "status": "ERROR",
                    "error": f"Failed to read existing file: {e}",
                    "path": path
                }, ensure_ascii=False)

        # Normalize newlines and compute diff
        new_content = content
        original_lines = original.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm=""
        ))

        # If no diff -> nothing to do
        if not diff:
            return json.dumps({
                "type": "file_change_proposal",
                "status": "NO_CHANGES",
                "message": f"No changes for '{path}'.",
                "path": path
            }, ensure_ascii=False)

        proposal_id = str(uuid.uuid4())
        payload = {
            "type": "file_change_proposal",
            "status": "NEEDS_APPROVAL",
            "proposal_id": proposal_id,
            "path": path,
            "diff": "".join(line if line.endswith("\\n") else f"{line}\\n" for line in diff),
            "new_content": new_content,
        }
        # Store to session for the UI
        if "pending_proposals" not in st.session_state:
            st.session_state.pending_proposals = {}
        st.session_state.pending_proposals[proposal_id] = payload
        return json.dumps(payload, ensure_ascii=False)

class RunInContainerInput(BaseModel):
    command: str = Field(description="The command to execute inside the Cowrie container.")

class UIRunInContainerTool(BaseTool):
    name: str = "run_in_container"
    description: str = (
        "Request to run a command inside the honeypot container. The UI will ask for approval "
        "and then execute docker exec if approved."
    )
    args_schema: Type[BaseModel] = RunInContainerInput

    def _run(self, command: str) -> str:
        container_name = "cowrie_honeypot_instance"
        request_id = str(uuid.uuid4())
        payload = {
            "type": "container_exec_request",
            "status": "NEEDS_APPROVAL",
            "request_id": request_id,
            "container": container_name,
            "command": command,
        }
        if "pending_execs" not in st.session_state:
            st.session_state.pending_execs = {}
        st.session_state.pending_execs[request_id] = payload
        return json.dumps(payload, ensure_ascii=False)

# -------------- Action Logger via Callbacks --------------
class UIActionLogger(BaseCallbackHandler):
    """Collects tool and LLM events so we can render a timeline of the agent's actions."""
    def __init__(self, store_key: str = "action_log"):
        self.store_key = store_key
        if self.store_key not in st.session_state:
            st.session_state[self.store_key] = []

    def _push(self, item: Dict[str, Any]):
        st.session_state[self.store_key].append({**item, "ts": time.time()})

    ## Tool events
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> None:
        name = serialized.get("name") or serialized.get("tool") or "tool"
        self._push({"event": "tool_start", "name": name, "input": input_str})

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        # Try to parse JSON payloads to surface UI approvals
        try:
            parsed = json.loads(output)
        except Exception:
            parsed = None
        self._push({"event": "tool_end", "output": output, "parsed": parsed})

    ## LLM events (minimal so we don't leak tokens/keys)
    def on_llm_start(self, serialized, prompts, **kwargs):
        self._push({"event": "llm_start", "n_prompts": len(prompts)})

    def on_llm_end(self, response, **kwargs):
        self._push({"event": "llm_end"})

    def on_chain_start(self, serialized, inputs, **kwargs):
        name = serialized.get("name", "chain")
        self._push({"event": "chain_start", "name": name})

    def on_chain_end(self, outputs, **kwargs):
        self._push({"event": "chain_end"})

# ------------------ Utility renderers ------------------
def render_diff_block(diff_text: str):
    """Pretty-print a unified diff with minimal CSS."""
    if not diff_text:
        st.info("Nessuna differenza da mostrare.")
        return
    st.code(diff_text, language="diff")

def apply_file_change(proposal: Dict[str, Any]) -> str:
    """Write the approved file content to disk (path safety enforced)."""
    path = proposal["path"]
    content = proposal["new_content"]
    if not _is_path_safe(path):
        return "❌ Accesso negato: path fuori dalla project root."
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"✅ File aggiornato: {path}"
    except Exception as e:
        return f"❌ Errore in scrittura: {e}"

def execute_container_command(req: Dict[str, Any]) -> str:
    """Run 'docker exec' if Docker is available."""
    container = req["container"]
    command = req["command"]
    try:
        full_cmd = ["docker", "exec", container] + command.split()
        proc = subprocess.run(full_cmd, check=True, capture_output=True, text=True, encoding="utf-8")
        out = proc.stdout.strip()
        return f"✅ Eseguito in {container}:\n\n{out}"
    except FileNotFoundError:
        return "❌ 'docker' non trovato. Docker è installato ed in PATH?"
    except subprocess.CalledProcessError as e:
        return f"❌ Errore esecuzione:\n{e.stderr.strip()}"
    except Exception as e:
        return f"❌ Errore imprevisto: {e}"

# ---------------- Agent / Tools wiring ----------------
@st.cache_resource(show_spinner=False)
def build_agent() -> AgentExecutor:
    # Imports of user's other tools (must be in PYTHONPATH)
    from cowrie import CowrieDeployTool
    from redis import RedisHoneyPotDeployTool 
    from wordpress import WordPotDeployTool
    from dionaea import DionaeaHoneyPotDeployTool
    from lifecycle_tools import (
        GetHoneypotLogsTool, StartHoneypotTool, DestroyHoneypotTool, StopHoneypotTool, ListActiveHoneypotsTool
    )
    from langchain_community.agent_toolkits import FileManagementToolkit

    # LLM setup (DeepSeek via OpenAI-compatible endpoint)
    # You can also set OPENAI_API_KEY + base_url if you prefer.
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
    model = os.getenv("MODEL_NAME", "deepseek-coder")
    temperature = float(os.getenv("MODEL_TEMPERATURE", "0"))
    if not api_key:
        st.warning("Nessuna API key trovata. Imposta DEEPSEEK_API_KEY nel tuo .env.")

    llm = ChatOpenAI(model=model, temperature=temperature, api_key=api_key, base_url=base_url)

    # File tools
    fs_tools = FileManagementToolkit(
        root_dir=str(PROJECT_ROOT),
        selected_tools=['copy_file','file_delete','file_search','move_file','read_file','write_file','list_directory']
    ).get_tools()

    # Compose toolset (note: we replace propose/apply + run_in_container)
    custom_tools = [
        CowrieDeployTool(),
        RedisHoneyPotDeployTool(),
        UIProposeAndApplyFileChangeTool(),
        UIRunInContainerTool(),
        WordPotDeployTool(),
        DionaeaHoneyPotDeployTool(),
        GetHoneypotLogsTool(),
        StartHoneypotTool(),
        DestroyHoneypotTool(),
        StopHoneypotTool(),
        ListActiveHoneypotsTool(),
    ]
    tools = custom_tools + fs_tools

    # Prompt (kept close to the user's original intent)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system",
                "You are a helpful and secure DevOps assistant. Your file access is restricted to the project directory, on a Windows machine.\n"
                "To run a command inside the honeypot container, use the 'run_in_container' tool. The user will be asked to approve every command.\n"
                "IMPORTANT WORKFLOW FOR MODIFYING FILES:\n"
                "1. Use 'read_file' to read the content.\n"
                "2. Use 'propose_and_apply_file_change' to generate the differences and (via UI) apply them.\n"
                "3. The UI will show a diff and ask for approval.\n"
                "4. ONLY after approval, the UI writes the file.\n"
                "5. Before starting the container, check if the same honeypot is already running. If it is, ask whether to stop or change port."
            ),
            MessagesPlaceholder(variable_name="chat_history"),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    agent = create_openai_tools_agent(llm, tools, prompt)
    executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
    return executor

# --------------------- Streamlit UI ---------------------
st.set_page_config(page_title="Honeypot DevOps Agent", page_icon="🛡️", layout="wide")

st.markdown(
    """
    <style>
    .msg-user {background:#0d6efd22;border:1px solid #0d6efd44;border-radius:10px;padding:0.6rem 0.8rem;margin-bottom:0.4rem;}
    .msg-ai {background:#19875422;border:1px solid #19875444;border-radius:10px;padding:0.6rem 0.8rem;margin-bottom:0.4rem;}
    .small-muted {font-size:0.8rem;color:#6c757d;}
    .action-card {border:1px solid #e5e7eb;border-radius:8px;padding:0.6rem 0.8rem;margin:0.4rem 0;background:#f8fafc;}
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🛡️ Honeypot DevOps Agent — Console & GUI")
st.caption("Chat con l'agente, osserva tutte le azioni e approva le modifiche ai file con un diff grafico.")

# Session state
if "chat" not in st.session_state:
    st.session_state.chat: List[Dict[str, str]] = []
if "pending_proposals" not in st.session_state:
    st.session_state.pending_proposals: Dict[str, Dict[str, Any]] = {}
if "pending_execs" not in st.session_state:
    st.session_state.pending_execs: Dict[str, Dict[str, Any]] = {}
if "action_log" not in st.session_state:
    st.session_state.action_log: List[Dict[str, Any]] = []

# Sidebar: System / inspector
with st.sidebar:
    st.subheader("⚙️ Config")
    st.write(f"Project root: `{PROJECT_ROOT}`")
    st.write("Le azioni che richiedono approvazione appariranno qui sotto.")

    # Pending file proposals
    if st.session_state.pending_proposals:
        st.markdown("### ✍️ Proposte di modifica")
        for pid, proposal in list(st.session_state.pending_proposals.items()):
            with st.container(border=True):
                st.markdown(f"**File:** `{proposal['path']}`")
                render_diff_block(proposal.get("diff", ""))
                c1, c2 = st.columns(2)
                if c1.button("✅ Approva & Applica", key=f"approve_{pid}"):
                    msg = apply_file_change(proposal)
                    st.success(msg)
                    # Drop from pending
                    st.session_state.pending_proposals.pop(pid, None)
                    # Echo to chat so the agent can be aware on next turn
                    st.session_state.chat.append({"role":"assistant","content":f"Modifica approvata ed applicata su `{proposal['path']}`."})
                if c2.button("❌ Rifiuta", key=f"reject_{pid}"):
                    st.info(f"Modifica rifiutata: {proposal['path']}")
                    st.session_state.pending_proposals.pop(pid, None)
                    st.session_state.chat.append({"role":"assistant","content":f"Modifica rifiutata per `{proposal['path']}`."})
    else:
        st.markdown("**Nessuna proposta di modifica in sospeso.**")

    # Pending container execs
    st.markdown("### 🧰 Esecuzioni in container")
    if st.session_state.pending_execs:
        for rid, req in list(st.session_state.pending_execs.items()):
            with st.container(border=True):
                st.markdown(f"**Container:** `{req['container']}`")
                st.code(req["command"])
                c1, c2 = st.columns(2)
                if c1.button("▶️ Esegui (approva)", key=f"exec_{rid}"):
                    msg = execute_container_command(req)
                    st.session_state.pending_execs.pop(rid, None)
                    st.success(msg)
                    st.session_state.chat.append({"role":"assistant","content":f"Comando eseguito in `{req['container']}`:\n\n```\n{req['command']}\n```"})
                if c2.button("🛑 Annulla", key=f"exec_cancel_{rid}"):
                    st.info("Richiesta esecuzione annullata.")
                    st.session_state.pending_execs.pop(rid, None)
    else:
        st.caption("Nessuna esecuzione in sospeso.")

    # Actions timeline
    st.markdown("### 🧭 Timeline azioni")
    if st.session_state.action_log:
        for i, e in enumerate(st.session_state.action_log[-200:]):
            with st.container():
                if e["event"] == "tool_start":
                    st.markdown(f"**Tool**: `{e['name']}` → *start*")
                    with st.expander("Input"):
                        st.code(e.get("input",""))
                elif e["event"] == "tool_end":
                    st.markdown("**Tool**: *end*")
                    parsed = e.get("parsed")
                    if parsed and isinstance(parsed, dict) and parsed.get("type") in ("file_change_proposal","container_exec_request"):
                        st.json(parsed)
                    else:
                        with st.expander("Output"):
                            st.code(e.get("output",""))
                elif e["event"].startswith("llm_"):
                    st.caption(f"LLM event: {e['event']}")
                elif e["event"].startswith("chain_"):
                    st.caption(f"Chain event: {e['event']}")
    else:
        st.caption("La timeline verrà popolata durante le esecuzioni.")

# Main column: Chat
agent = build_agent()
action_logger = UIActionLogger()

# Render chat messages
for m in st.session_state.chat:
    if m["role"] == "user":
        st.markdown(f"<div class='msg-user'>👤 {m['content']}</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='msg-ai'>🤖 {m['content']}</div>", unsafe_allow_html=True)

# Chat input
with st.form("chat_form", clear_on_submit=True):
    user_text = st.text_area("Scrivi un messaggio", height=100, placeholder="Es: Avvia Cowrie su porta 2222 e mostrami i log...")
    submitted = st.form_submit_button("Invia")

if submitted and user_text.strip():
    st.session_state.chat.append({"role":"user","content":user_text.strip()})
    # Build LC chat_history
    chat_history = []
    for m in st.session_state.chat:
        if m["role"] == "user":
            chat_history.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            chat_history.append(AIMessage(content=m["content"]))

    with st.spinner("L'agente sta ragionando..."):
        try:
            result = agent.invoke(
                {"input": user_text.strip(), "chat_history": chat_history},
                config={"callbacks":[action_logger]}
            )
            out = result.get("output","")
        except Exception as e:
            out = f"Si è verificato un errore durante l'invocazione dell'agente: {e}"

    st.session_state.chat.append({"role":"assistant","content":out})
    st.rerun()
