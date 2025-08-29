import os
import shutil
import subprocess
from typing import Type, Optional, ClassVar
import time # Make sure to import the time module at the top of your file
import difflib
# LangChain components
from dotenv import load_dotenv
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
# Removed unresolved import from langchain_community.tools.file_system
from langchain_community.agent_toolkits import FileManagementToolkit


from cowrie import CowrieDeployTool
from redis import RedisHoneyPotDeployTool 
from wordpress import WordPotDeployTool
from dionaea import DionaeaHoneyPotDeployTool
from lifecycle_tools import GetHoneypotLogsTool,GetHoneypotLogsTool,StartHoneypotTool,DestroyHoneypotTool,StopHoneypotTool,ListActiveHoneypotsTool
# --- Configuration ---
PROJECT_ROOT = os.path.abspath(os.getcwd())

def _is_path_safe(path: str) -> bool:
    """Checks if the given path is within the project's root directory."""
    requested_path = os.path.abspath(path)
    return os.path.commonprefix([requested_path, PROJECT_ROOT]) == PROJECT_ROOT


# --- General Purpose File System Tools ---

class RunShellCommandInput(BaseModel):
    command: str = Field(description="The shell command to execute.")
    retries: int = Field(default=3, description="The number of times to retry the command if it fails.")
    delay: int = Field(default=3, description="The delay in seconds between retries.")

class RunShellCommandTool(BaseTool):
    """A tool to execute shell commands with an automatic retry mechanism."""
    name: str = "run_shell_command"
    description: str = (
        "Use this to execute any shell command on the host machine. "
        "It can be used to check Docker logs (e.g., 'docker logs my_container') or "
        "run commands inside a container (e.g., 'docker exec my_container ls'). "
        "The tool will automatically retry the command if it fails."
    )
    args_schema: Type[BaseModel] = RunShellCommandInput

    def _run(self, command: str, retries: int = 3, delay: int = 5) -> str:
        print(f"\n[TOOL] Executing shell command: '{command}' (Retries: {retries}, Delay: {delay}s)")
        
        last_error = None
        for attempt in range(retries):
            try:
                process = subprocess.run(
                    command,
                    shell=True,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace' 
                )
                return f"Command executed successfully.\n--- STDOUT ---\n{process.stdout.strip()}"
            
            except subprocess.CalledProcessError as e:
                error_message = f"Attempt {attempt + 1} of {retries} failed.\n--- STDERR ---\n{e.stderr.strip()}"
                print(f"[TOOL] [ERROR] {error_message}")
                last_error = error_message
                if attempt < retries - 1:
                    print(f"[TOOL] Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    return f"Command failed after {retries} attempts. Final error:\n{error_message}"
            
            # MODIFICA 2: Aggiunto un blocco 'except' generico per catturare tutti gli altri errori
            # (come problemi di permessi, comandi non trovati, ecc.) e riportarli correttamente all'agente.
            except Exception as e:
                error_message = f"An unexpected error occurred on attempt {attempt + 1}: {str(e)}"
                print(f"[TOOL] [ERROR] {error_message}")
                last_error = error_message
                # In caso di errore imprevisto, di solito è inutile riprovare.
                # Interrompiamo il ciclo e restituiamo l'errore.
                return f"Command failed due to an unexpected error: {str(e)}"

        return f"Command failed after all retries. Last known error: {last_error}"

# ==============================================================================
# NUOVO TOOL MIGLIORATO
# ==============================================================================

class ProposeAndApplyFileChangeInput(BaseModel):
    path: str = Field(description="The path of the file to modify.")
    content: str = Field(description="The new, full content to write to the file.")
    
class ProposeAndApplyFileChangeTool(BaseTool):
    """
    A tool that proposes file changes, asks for user approval directly in the console,
    and applies the changes if approved. This is an atomic operation.
    """
    name: str = "propose_and_apply_file_change"
    description: str = (
        "Use this tool to modify a file. It will show the user a diff, ask for approval, "
        "and write the new content in a single step. Use it AFTER reading the file "
        "to construct the new content."
    )
    args_schema: Type[BaseModel] = ProposeAndApplyFileChangeInput

    def _run(self, path: str, content: str) -> str:
        """The core logic of the tool."""
        if not _is_path_safe(path):
            return "Error: Access denied. Path is outside the allowed project directory."

        print(f"\n[TOOL] Proposing changes for file '{path}'...")
        try:
            # 1. Read original content
            original_content_lines = []
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    original_content_lines = f.readlines()
            
            # 2. Prepare new content and generate diff
            new_content_lines = [line + '\n' for line in content.splitlines()]
            if not new_content_lines and original_content_lines:
                 new_content_lines.append('\n')

            diff = list(difflib.unified_diff(
                original_content_lines, new_content_lines, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""
            ))

            if not diff:
                return f"✅ No changes detected for '{path}'. The file is already up-to-date."

            # 3. Present the diff to the user for approval
            print("\n" + "="*60)
            print("### 📝 PROPOSTA DI MODIFICA FILE ###")
            print(f"**File:** `{path}`")
            print("L'agente propone le seguenti modifiche:")
            print("```diff")
            for line in diff:
                print(line)
            print("```")
            print("="*60)

            # --- KEY CHANGE 1: Ask for approval directly in the console ---
            # This pauses the tool and waits for the user to respond here.
            try:
                approval = input("Approvi queste modifiche? (sì/no): ").lower().strip()
            except EOFError:
                return "Error: Cannot get user approval in a non-interactive session. Modification cancelled."

            # 4. Apply changes if approved
            if approval in ['sì', 'si', 'y', 'yes', 's']:
                print(f"[TOOL] ✅ User approved. Applying changes to '{path}'...")
                try:
                    # --- KEY CHANGE 2: Write the file if approved ---
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    return f"File '{path}' updated successfully."
                except Exception as e:
                    return f"Error writing file after approval: {e}"
            else:
                print("[TOOL] ❌ User denied. File modification cancelled.")
                return "User denied the changes. The file was not modified."

        except Exception as e:
            return f"An error occurred during the file modification process: {e}"
        
class RunInContainerInput(BaseModel):
    command: str = Field(description="The command to execute inside the Cowrie container.")

class RunInContainerTool(BaseTool):
    """A tool to execute a command inside the container AFTER user approval."""
    name: str = "run_in_container"
    description: str = (
        "Use this tool to run a command inside the honeypot container. "
        "For security, it will ask for user confirmation before executing."
    )
    args_schema: Type[BaseModel] = RunInContainerInput

    def _run(self, command: str) -> str:
        container_name = "cowrie_honeypot_instance"
        
        # Present the command to the user for approval
        print("\n" + "="*50)
        print("### SECURITY APPROVAL REQUIRED ###")
        print(f"The agent is requesting to execute the following command inside the container '{container_name}':")
        print(f"\n  {command}\n")
        print("This action will be performed using 'docker exec'.")
        print("="*50)

        try:
            # The input() function will pause the agent and wait for your response in the terminal.
            approval = input("Do you approve this action? (y/n): ").lower().strip()
        except EOFError:
            # This handles cases where the script is run in a non-interactive environment.
            return "Error: Cannot get user approval in a non-interactive session. Execution denied."

        if approval == 'y':
            print(f"[TOOL] User approved. Executing command...")
            try:
                full_docker_command = ["docker", "exec", container_name] + command.split()
                process = subprocess.run(
                    full_docker_command,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding='utf-8'
                )
                return f"Command executed successfully.\n--- STDOUT ---\n{process.stdout.strip()}"
            except FileNotFoundError:
                 return "Error: 'docker' command not found. Is Docker installed and in your PATH?"
            except subprocess.CalledProcessError as e:
                return f"Command failed with an error.\n--- STDERR ---\n{e.stderr.strip()}"
        else:
            return "User denied execution. Command was not run."
# ==============================================================================
# AGENT SETUP AND EXECUTION
# ==============================================================================
def main():
    """Sets up and runs the LangChain agent in a conversational loop."""
    print("--- LangChain Secure DevOps Agent (Conversational) ---")
    print("Type 'exit' or 'quit' to end the session.")
    
    llm = ChatOpenAI(model="deepseek-coder", temperature=0, api_key="sk-4a7a12ba0d544f35aab545bee74e8cc5", base_url="https://api.deepseek.com/v1")


    fs_tools = FileManagementToolkit(
        root_dir=str(PROJECT_ROOT),
        selected_tools=[
            'copy_file', 'file_delete', 'file_search', 'move_file', 'read_file', 'write_file', 'list_directory'
        ]
    ).get_tools()
    

    your_custom_tools = [
        CowrieDeployTool(),
        RedisHoneyPotDeployTool(),
        ProposeAndApplyFileChangeTool(),
        RunInContainerTool(),
        RunShellCommandTool(),
        WordPotDeployTool(),
        DionaeaHoneyPotDeployTool(),
        GetHoneypotLogsTool(),
        StartHoneypotTool(),
        DestroyHoneypotTool(),
        StopHoneypotTool(),
        ListActiveHoneypotsTool()
    ]

    tools = your_custom_tools + fs_tools

    # Il prompt ora include il placeholder per 'chat_history'
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system",
             "You are a helpful and secure DevOps assistant. Your file access is restricted to the project directory, on a Windows machine.\n"
             "To run a command inside the honeypot container, use the 'run_in_container' tool. The user will be asked to approve every command.\n"
             "IMPORTANT WORKFLOW FOR MODIFYING FILES:\n"
             "1. Use 'read_file' to read the content.\n"
             "2. Use 'propose_and_apply_file_change' to generate the differences and apply them.\n"
             "3. Show the user the proposed changes and ASK for their approval.\n"
             "4. ONLY after approval, use 'write_file' to appropriately apply the changes.\n"
             "5. Before starting the container, check if the same honeypot is already running. If it is, ask the user if they want to stop or configure the same honeypot on a different port.\n"
             ),
            MessagesPlaceholder(variable_name="chat_history"),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    agent = create_openai_tools_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    # Inizializza la cronologia della chat
    chat_history = []

    # Ciclo conversazionale
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["exit", "quit"]:
                print("--- Session Ended ---")
                break

            # Invoca l'agente con l'input e la cronologia
            result = agent_executor.invoke({
                "input": user_input,
                "chat_history": chat_history
            })

            # Aggiungi il turno corrente alla cronologia
            chat_history.append(HumanMessage(content=user_input))
            chat_history.append(AIMessage(content=result['output']))

            # Stampa solo l'output finale dell'agente
            print(f"\nAgent: {result['output']}")

        except KeyboardInterrupt:
            print("\n--- Session Interrupted by user. Exiting. ---")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}")


if __name__ == "__main__":
    main()