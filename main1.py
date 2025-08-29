
import streamlit as st
import os
import shutil
import subprocess
import time
import difflib
from typing import Type, Dict, Any

# LangChain components
from dotenv import load_dotenv
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.agent_toolkits import FileManagementToolkit

# Custom tools
from redis import RedisHoneyPotDeployTool
from cowrie import CowrieDeployTool
from dionaea import DionaeaHoneyPotDeployTool
from wordpress import WordPotDeployTool

# --- Configuration ---
load_dotenv()
PROJECT_ROOT = os.path.abspath(os.getcwd())

def _is_path_safe(path: str) -> bool:
    """Checks if the given path is within the project's root directory."""
    requested_path = os.path.abspath(path)
    return os.path.commonprefix([requested_path, PROJECT_ROOT]) == PROJECT_ROOT

# --- Strumenti dell'Agente (Modificati per Streamlit) ---

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

# ==============================================================================
# TOOL DI MODIFICA FILE (RIADATTATO PER LA GUI)
# ==============================================================================
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

        # Salva l'azione pendente nello stato della sessione per l'approvazione
        st.session_state.pending_action = {
            "type": "file_change",
            "path": path,
            "new_content": content,
            "diff": "\n".join(diff)
        }
        return "Azione proposta all'utente per l'approvazione. Attendo la risposta dall'interfaccia."


# ==============================================================================
# TOOL ESECUZIONE IN CONTAINER (RIADATTATO PER LA GUI)
# ==============================================================================
class RunInContainerInput(BaseModel):
    command: str = Field(description="The command to execute inside the Cowrie container.")

class RunInContainerTool(BaseTool):
    name: str = "run_in_container"
    description: str = "Use this tool to run a command inside the honeypot container. It will ask for user confirmation."
    args_schema: Type[BaseModel] = RunInContainerInput

    def _run(self, command: str) -> str:
        # Salva l'azione pendente nello stato della sessione per l'approvazione
        st.session_state.pending_action = {
            "type": "container_command",
            "command": command,
            "container_name": "cowrie_honeypot_instance"
        }
        return "Comando proposto all'utente per l'approvazione. Attendo la risposta dall'interfaccia."

# --- Funzioni Helper per l'esecuzione post-approvazione ---

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


# --- Interfaccia Grafica con Streamlit ---

st.set_page_config(page_title="🤖 Agente DevOps Interattivo", layout="wide")
st.title("🤖 Agente DevOps Interattivo")
st.caption("Un assistente per aiutarti a gestire e deployare i tuoi honeypot.")

# Inizializzazione dello stato della sessione
if "messages" not in st.session_state:
    st.session_state.messages = []
if "agent_executor" not in st.session_state:
    # Setup dell'agente una sola volta
    llm = ChatOpenAI(model="deepseek-coder", temperature=0, api_key="sk-4a7a12ba0d544f35aab545bee74e8cc5", base_url="https://api.deepseek.com/v1")
    fs_tools = FileManagementToolkit(root_dir=str(PROJECT_ROOT)).get_tools()
    custom_tools = [
        CowrieDeployTool(), RedisHoneyPotDeployTool(), ProposeAndApplyFileChangeTool(),
        RunInContainerTool(), RunShellCommandTool(), WordPotDeployTool(), DionaeaHoneyPotDeployTool()
    ]
    tools = custom_tools + fs_tools
    
    # Prompt corretto e semplificato
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a helpful and secure DevOps assistant. Your file access is restricted to the project directory.\n"
         "IMPORTANT WORKFLOW FOR MODIFYING FILES:\n"
         "1. First, use 'read_file' to get the current content of the file.\n"
         "2. Then, use the 'propose_and_apply_file_change' tool to handle the entire modification process. This single tool will show the changes to the user and ask for their approval. Do NOT use 'write_file' separately.\n"
         "Before starting a container, check if a honeypot of the same type is already running."
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
                # Esegui l'azione approvata
                result = ""
                if action["type"] == "file_change":
                    result = execute_approved_file_change(action)
                elif action["type"] == "container_command":
                    result = execute_approved_container_command(action)
                
                # Pulisci l'azione e continua la conversazione
                st.session_state.pending_action = None
                st.session_state.messages.append(HumanMessage(content=f"Azione approvata dall'utente. Risultato: {result}"))
                st.rerun()

        with col2:
            if st.button("❌ Nega", use_container_width=True, key="deny"):
                st.warning("Azione negata dall'utente.")
                result = "User denied the action."
                # Pulisci l'azione e continua la conversazione
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
            with st.spinner("L'agente sta pensando..."):
                try:
                    response = st.session_state.agent_executor.invoke({
                        "input": user_input,
                        "chat_history": st.session_state.messages
                    })
                    # Se l'agente non ha proposto un'azione, mostra la sua risposta
                    if not st.session_state.get("pending_action"):
                        st.markdown(response['output'])
                        st.session_state.messages.append(AIMessage(content=response['output']))
                    else:
                        # Se è stata proposta un'azione, la UI si aggiornerà da sola
                        st.rerun()

                except Exception as e:
                    st.error(f"Si è verificato un errore: {e}")
                    st.session_state.messages.append(AIMessage(content=f"Errore: {e}"))
