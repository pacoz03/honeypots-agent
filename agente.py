import streamlit as st
import os
import shutil
import subprocess
import time
import difflib
from typing import Type, Dict, Any, List, Union

# --- NUOVO: Import per il Callback Handler ---
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.outputs import LLMResult

# LangChain components
from dotenv import load_dotenv
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.agent_toolkits import FileManagementToolkit
from langchain_deepseek import ChatDeepSeek
# Custom tools
from redis import RedisHoneyPotDeployTool
from cowrie import CowrieDeployTool
from dionaea import DionaeaHoneyPotDeployTool
from wordpress import WordPotDeployTool
from suricata import SuricataHoneyPotDeployTool
from lifecycle_tools import (
    GetHoneypotLogsTool, StartHoneypotTool, DestroyHoneypotTool, StopHoneypotTool, ListActiveHoneypotsTool
)
# --- Configuration ---
load_dotenv()
PROJECT_ROOT = os.path.abspath(os.getcwd())

def _is_path_safe(path: str) -> bool:
    """Checks if the given path is within the project's root directory."""
    requested_path = os.path.abspath(path)
    return os.path.commonprefix([requested_path, PROJECT_ROOT]) == PROJECT_ROOT

class StreamlitCallbackHandler(BaseCallbackHandler):
    """Callback Handler che scrive i passaggi dell'agente in uno Streamlit container."""

    def __init__(self, container):
        self.container = container
        self.tool_call_counter = 1

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> Any:
        """Stampato all'inizio della chiamata LLM."""
        self.container.info("🧠 L'agente sta pensando...")

    def on_agent_action(self, action: AgentAction, **kwargs: Any) -> Any:
        """Stampato quando l'agente decide di usare uno strumento."""
        tool_name = action.tool
        tool_input = action.tool_input
        self.container.info(f"▶️ **Azione #{self.tool_call_counter}:** Utilizzo dello strumento `{tool_name}`")
        self.container.code(f"Input: {tool_input}", language="json")
        self.tool_call_counter += 1

    def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        """Stampato al termine dell'esecuzione di uno strumento."""
        self.container.markdown("---")
        self.container.success("✅ **Risultato dello Strumento:**")
        # Mostra l'output in un blocco espandibile se è molto lungo
        if len(output) > 200:
            with self.container.expander("Mostra output completo"):
                st.code(output, language='text')
        else:
            self.container.code(output, language='text')
        self.container.markdown("---")
        
    def on_agent_finish(self, finish: AgentFinish, **kwargs: Any) -> Any:
        """Stampato quando l'agente ha terminato e restituisce la risposta finale."""
        self.container.success("🏁 L'agente ha completato il suo ragionamento.")
        self.tool_call_counter = 1


# --- Strumenti dell'Agente (Invariati) ---

class RunShellCommandInput(BaseModel):
    command: str = Field(description="The shell command to execute.")

class RunShellCommandTool(BaseTool):
    name: str = "run_shell_command"
    description: str = "Use this to execute any shell command on the host machine."
    args_schema: Type[BaseModel] = RunShellCommandInput

    def _run(self, command: str) -> str:
        st.info(f"Esecuzione del comando shell: `{command}`")
        try:
            process = subprocess.run(
                command, shell=True, check=True, capture_output=True,
                text=True, encoding='utf-8', errors='replace'
            )
            return f"Comando eseguito con successo.\n--- STDOUT ---\n{process.stdout.strip()}"
        except Exception as e:
            error_message = f"Errore imprevisto durante l'esecuzione del comando: {str(e)}"
            st.error(error_message)
            return error_message

class ReadFileHeadInput(BaseModel):
    path: str = Field(description="The path of the file to read.")
    lines: int = Field(default=10, description="The number of lines to read from the beginning of the file.")

class ReadFileHeadTool(BaseTool):
    name: str = "read_file_head"
    description: str = "Use this tool to read the first N lines of a file. It's much more efficient than reading the whole file."
    args_schema: Type[BaseModel] = ReadFileHeadInput

    def _run(self, path: str, lines: int = 10) -> str:
        if not _is_path_safe(path):
            return "Error: Access denied. Path is outside the allowed project directory."
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                head_lines = [next(f) for _ in range(lines)]
            return "".join(head_lines)
        except FileNotFoundError:
            return f"Error: File not found at path '{path}'."
        except StopIteration:
            return "Successfully read all lines (file is shorter than requested number of lines)."
        except Exception as e:
            return f"An unexpected error occurred: {str(e)}"
            
class ProposeFileChangeInput(BaseModel):
    path: str = Field(description="The path of the file to modify.")
    content: str = Field(description="The new, full content to write to the file.")

class ProposeAndApplyFileChangeTool(BaseTool):
    name: str = "propose_and_apply_file_change"
    description: str = (
        "Use this tool to modify a file. It will show the user a diff and ask for approval "
        "via UI buttons. Use it AFTER reading the file to construct the new content."
    )
    args_schema: Type[BaseModel] = ProposeFileChangeInput

    def _run(self, path: str, content: str) -> str:
        if not _is_path_safe(path):
            return "Error: Access denied. Path is outside the allowed project directory."

        original_content_lines = []
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                original_content_lines = f.readlines()

        new_content_lines = [line + '\n' for line in content.splitlines()]
        if not new_content_lines and original_content_lines:
            new_content_lines.append('\n')

        diff = list(difflib.unified_diff(
            original_content_lines, new_content_lines, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""
        ))

        if not diff:
            return f"✅ Nessuna modifica rilevata per '{path}'. Il file è già aggiornato."

        st.session_state.pending_action = {
            "type": "file_change",
            "path": path,
            "new_content": content,
            "diff": "\n".join(diff)
        }
        return "Azione proposta all'utente per l'approvazione. Attendo la risposta dall'interfaccia."

class RunInContainerInput(BaseModel):
    command: str = Field(description="The command to execute inside the Cowrie container.")

class RunInContainerTool(BaseTool):
    name: str = "run_in_container"
    description: str = "Use this tool to run a command inside the honeypot container. It will ask for user confirmation."
    args_schema: Type[BaseModel] = RunInContainerInput

    def _run(self, command: str) -> str:
        st.session_state.pending_action = {
            "type": "container_command",
            "command": command,
            "container_name": "cowrie_honeypot_instance"
        }
        return "Comando proposto all'utente per l'approvazione. Attendo la risposta dall'interfaccia."

class CreateDashboardPageInput(BaseModel):
    filename: str = Field(description="The Python filename for the new page (e.g., 'dashboard_name.py'). Must end with .py and contain no spaces or special characters.")
    page_code: str = Field(description="The full, valid Python code to write to the file. This code will be executed as a Streamlit page and should be self-contained.")

class CreateDashboardPageTool(BaseTool):
    name: str = "create_dashboard_page"
    description: str = (
        "Use this tool to create a new Streamlit dashboard page to visualize data, typically from logs. "
        "You must provide a valid filename (e.g., 'my_dashboard.py') and the full, complete Python code for the Streamlit page. "
        "The code must be self-contained and perform all necessary actions like importing libraries (e.g., pandas, streamlit), reading files, and generating plots. "
        "Inform the user that the new page will be available in the sidebar after creation."
    )
    args_schema: Type[BaseModel] = CreateDashboardPageInput

    def _run(self, filename: str, page_code: str) -> str:
        pages_dir = os.path.join(PROJECT_ROOT, "pages")
        
        if not filename.endswith(".py") or " " in filename or "/" in filename or "\\" in filename:
            return "Error: Invalid filename. It must end with .py and contain no spaces or slashes."

        try:
            os.makedirs(pages_dir, exist_ok=True)
            file_path = os.path.join(pages_dir, filename)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(page_code)
            
            time.sleep(1) 
            st.success(f"Nuova pagina dashboard '{filename}' creata! Controlla la barra laterale per vederla.")
            return f"Dashboard page '{filename}' created successfully. The user can now navigate to it from the sidebar."
            
        except Exception as e:
            error_message = f"Failed to create dashboard page: {str(e)}"
            st.error(error_message)
            return error_message

# --- Funzioni Helper (Invariate) ---

def execute_approved_file_change(action: Dict[str, Any]):
    """Scrive il file dopo che l'utente ha cliccato 'Approva'."""
    try:
        with open(action["path"], 'w', encoding='utf-8') as f:
            f.write(action["new_content"])
        st.success(f"File '{action['path']}' aggiornato con successo!")
        return f"User approved. File '{action['path']}' updated."
    except Exception as e:
        st.error(f"Errore durante la scrittura del file dopo l'approvazione: {e}")
        return f"Error writing file after approval: {e}"

def execute_approved_container_command(action: Dict[str, Any]):
    """Esegue il comando docker dopo che l'utente ha cliccato 'Approva'."""
    try:
        full_docker_command = ["docker", "exec", action["container_name"]] + action["command"].split()
        st.info(f"Esecuzione comando approvato: `{' '.join(full_docker_command)}`")
        process = subprocess.run(
            full_docker_command, check=True, capture_output=True,
            text=True, encoding='utf-8'
        )
        st.code(process.stdout.strip(), language="bash")
        return f"User approved. Command executed successfully.\n--- STDOUT ---\n{process.stdout.strip()}"
    except Exception as e:
        st.error(f"Errore durante l'esecuzione del comando docker: {e}")
        return f"Command failed with an error: {e}"

# --- Interfaccia Grafica con Streamlit (Invariata fino al loop principale) ---

st.set_page_config(page_title="🤖 Agente DevOps Interattivo", layout="wide")
st.title("🤖 Agente DevOps Interattivo")
st.caption("Un assistente per aiutarti a gestire e deployare i tuoi honeypot.")

# Inizializzazione dello stato della sessione
if "messages" not in st.session_state:
    st.session_state.messages = []
if "agent_executor" not in st.session_state:
    llm = ChatDeepSeek(model="deepseek-reasoner", temperature=0, api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com/v1")
    fs_tools = FileManagementToolkit(root_dir=str(PROJECT_ROOT)).get_tools()
    custom_tools = [
        CowrieDeployTool(), RedisHoneyPotDeployTool(), ProposeAndApplyFileChangeTool(),
        RunInContainerTool(), RunShellCommandTool(), WordPotDeployTool(), DionaeaHoneyPotDeployTool(),
        CreateDashboardPageTool(), SuricataHoneyPotDeployTool(),
        GetHoneypotLogsTool(), StartHoneypotTool(), StopHoneypotTool(), DestroyHoneypotTool(), ListActiveHoneypotsTool(),
        ReadFileHeadTool()
    ]
    tools = custom_tools + fs_tools
    
    prompt = ChatPromptTemplate.from_messages([
        ("system",
        "You are a helpful and secure DevOps assistant. Your file access is restricted to the project directory, on a Windows machine.\n"
        "To run a command inside the honeypot container, use the 'run_in_container' tool. The user will be asked to approve every command.\n"
        "IMPORTANT WORKFLOW FOR MODIFYING FILES:\n"
        "1. Use 'read_file' to read the content.\n"
        "2. Use 'propose_and_apply_file_change' to generate the differences and apply them.\n"
        "3. Show the user the proposed changes and ASK for their approval.\n"
        "4. ONLY after approval, use 'write_file' to appropriately apply the changes.\n"
        "5. Before starting the container, check if the same honeypot is already running. If it is, ask the user if they want to stop or configure the same honeypot on a different port.\n"

        "IMPORTANT CAPABILITY: You can create new dynamic dashboard pages in the UI to visualize data using the 'create_dashboard_page' tool. "
        "When asked to create a dashboard, follow these steps:\n"
        "1. To understand the structure of a data source (like a log file) for a dashboard, **DO NOT read the entire file** as it can be very large. Instead, read only a small sample (e.g., the first 50 lines) to analyze its format. Use the `run_shell_command` tool for this. Since the system is Windows, a good command is `Get-Content -Path 'path\\to\\your\\file.log' -Head 50`.\n"
        "2. Then, generate the complete Python code for the Streamlit page.\n"
        "3. For all visualizations and plots, you MUST use the 'plotly' library (e.g., 'import plotly.express as px').\n"
        "4. Do NOT use other plotting libraries like Matplotlib or Seaborn, as they are not available in the environment.\n"
        "5. The generated code must be self-contained and include all necessary imports (e.g., 'import streamlit as st', 'import pandas as pd', 'import plotly.express as px').\n"
        "6. Finally, use the 'create_dashboard_page' tool with the correct filename and the generated code."
        ),
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    agent = create_openai_tools_agent(llm, tools, prompt)
    st.session_state.agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)

# Mostra la cronologia della chat
for message in st.session_state.messages:
    with st.chat_message(message.type):
        st.markdown(message.content)

# Gestione delle azioni pendenti (logica di approvazione)
if "pending_action" in st.session_state and st.session_state.pending_action:
    action = st.session_state.pending_action
    
    with st.chat_message("assistant"):
        st.write("L'agente richiede la tua approvazione per la seguente azione:")
        
        if action["type"] == "file_change":
            st.write(f"**Modifica proposta per il file:** `{action['path']}`")
            st.code(action['diff'], language='diff')
        elif action["type"] == "container_command":
            st.write(f"**Comando da eseguire nel container** `{action['container_name']}`:")
            st.code(action['command'], language='bash')

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Approva", use_container_width=True, key="approve"):
                result = ""
                if action["type"] == "file_change":
                    result = execute_approved_file_change(action)
                elif action["type"] == "container_command":
                    result = execute_approved_container_command(action)
                
                st.session_state.pending_action = None
                st.session_state.messages.append(HumanMessage(content=f"Azione approvata dall'utente. Risultato: {result}"))
                st.rerun()

        with col2:
            if st.button("❌ Nega", use_container_width=True, key="deny"):
                st.warning("Azione negata dall'utente.")
                result = "User denied the action."
                st.session_state.pending_action = None
                st.session_state.messages.append(HumanMessage(content=result))
                st.rerun()
else:
    # Input della chat standard
    if user_input := st.chat_input("Cosa vuoi fare?"):
        st.session_state.messages.append(HumanMessage(content=user_input))
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            # 1. Creiamo un'area espandibile solo per i log del ragionamento
            expander = st.expander("🔎 **Ragionamento dell'Agente**")
            log_container = expander.container()
            callback = StreamlitCallbackHandler(log_container)

            # 2. Eseguiamo l'agente. Il callback scriverà i suoi log DENTRO l'expander.
            try:
                response = st.session_state.agent_executor.invoke(
                    {
                        "input": user_input,
                        "chat_history": st.session_state.messages
                    },
                    config={"callbacks": [callback]}
                )
                
                # 3. Controlliamo se è necessaria un'azione o se abbiamo una risposta finale.
                if not st.session_state.get("pending_action"):
                    # 4. Scriviamo la risposta finale QUI, nel corpo principale del messaggio dell'assistente.
                    st.markdown(response['output'])
                    st.session_state.messages.append(AIMessage(content=response['output']))
                else:
                    # Se è stata proposta un'azione, la UI ha bisogno di un refresh per mostrare
                    # i pulsanti di approvazione. La logica di gestione `pending_action` all'inizio
                    # della pagina si occuperà di visualizzarla.
                    st.rerun()

            except Exception as e:
                st.error(f"Si è verificato un errore: {e}")
                st.session_state.messages.append(AIMessage(content=f"Errore: {e}"))