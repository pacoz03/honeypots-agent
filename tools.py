import os
import shutil
import subprocess
import time
import difflib
from typing import Type, ClassVar

from pydantic import BaseModel, Field
from langchain.tools import BaseTool

# --- Configuration & Safety ---
PROJECT_ROOT = os.path.abspath(os.getcwd())

def _is_path_safe(path: str) -> bool:
    """Checks if the given path is within the project's root directory."""
    requested_path = os.path.abspath(path)
    return os.path.commonprefix([requested_path, PROJECT_ROOT]) == PROJECT_ROOT

# --- Tool 1: Generic Honeypot Instance Setup ---

class HoneypotSetupInput(BaseModel):
    honeypot_type: str = Field(description="The type of honeypot to set up, e.g., 'cowrie', 'dionaea'. This must match a directory name in 'config_source'.")
    instance_name: str = Field(description="A unique name for the new honeypot instance, e.g., 'cowrie-prod' or 'dionaea-test-2'.")

class HoneypotSetupTool(BaseTool):
    """
    A tool to prepare the directory structure for a new honeypot instance.
    It copies the base configuration from the 'config_source' directory to a new
    directory in the 'honeypots' folder. This is the first step before
    configuring and deploying a new honeypot.
    """
    name: str = "setup_new_honeypot_instance"
    description: str = (
        "Use this tool to create the initial files for a new honeypot instance. "
        "It copies the base configuration into a new directory, which you can then "
        "modify before deployment. You must provide the 'honeypot_type' and a unique 'instance_name'."
    )
    args_schema: Type[BaseModel] = HoneypotSetupInput

    SOURCE_BASE_DIR: ClassVar[str] = "config_source"
    DEPLOY_BASE_DIR: ClassVar[str] = "honeypots"

    def _run(self, honeypot_type: str, instance_name: str) -> str:
        """The core logic of the tool."""
        source_dir = os.path.join(self.SOURCE_BASE_DIR, honeypot_type)
        deploy_dir = os.path.join(self.DEPLOY_BASE_DIR, instance_name)

        print(f"\n[TOOL] Setting up new honeypot instance '{instance_name}' of type '{honeypot_type}'...")

        # --- Validation ---
        if not os.path.isdir(source_dir):
            return f"Error: Source directory for honeypot type '{honeypot_type}' not found at '{source_dir}'. Cannot create instance."
        
        if os.path.exists(deploy_dir):
            return f"Error: An instance named '{instance_name}' already exists at '{deploy_dir}'. Please choose a unique name."

        # --- Scaffolding ---
        try:
            print(f" - Copying files from '{source_dir}' to '{deploy_dir}'...")
            shutil.copytree(source_dir, deploy_dir)
            
            success_message = (
                f"✅ Successfully created a new honeypot instance setup named '{instance_name}' at '{deploy_dir}'.\n"
                f"Next steps for the agent: \n"
                f"1. Read the configuration files (especially 'docker-compose.yml') in '{deploy_dir}'.\n"
                f"2. Propose necessary changes to the user (e.g., ports, container names) using 'propose_and_apply_file_change'.\n"
                f"3. After approval, use 'run_shell_command' to deploy."
            )
            print(f"[TOOL] {success_message}")
            return success_message
        except Exception as e:
            error_message = f"Failed to create instance directory. Error: {e}"
            print(f"[TOOL] [ERROR] {error_message}")
            if os.path.exists(deploy_dir):
                shutil.rmtree(deploy_dir)
            return error_message

# --- Tool 2: Propose and Apply File Changes ---

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
            original_content_lines = []
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    original_content_lines = f.readlines()
            
            new_content_lines = [line + '\n' for line in content.splitlines()]
            if not new_content_lines and content:
                 new_content_lines.append(content)

            diff = list(difflib.unified_diff(
                original_content_lines, new_content_lines, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""
            ))

            if not diff:
                return f"✅ No changes detected for '{path}'. The file is already up-to-date."

            print("\n" + "="*60)
            print("### 📝 FILE CHANGE PROPOSAL ###")
            print(f"**File:** `{path}`")
            print("The agent proposes the following changes:")
            print("```diff")
            for line in diff:
                print(line, end="")
            print("\n```")
            print("="*60)

            try:
                approval = input("Approve these changes? (yes/no): ").lower().strip()
            except EOFError:
                return "Error: Cannot get user approval in a non-interactive session. Modification cancelled."

            if approval in ['sì', 'si', 'y', 'yes', 's']:
                print(f"[TOOL] ✅ User approved. Applying changes to '{path}'...")
                try:
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

# --- Tool 3: General Shell Command Execution ---

class RunShellCommandInput(BaseModel):
    command: str = Field(description="The shell command to execute.")
    retries: int = Field(default=3, description="The number of times to retry the command if it fails.")
    delay: int = Field(default=3, description="The delay in seconds between retries.")

class RunShellCommandTool(BaseTool):
    """A tool to execute shell commands with an automatic retry mechanism."""
    name: str = "run_shell_command"
    description: str = (
        "Use this to execute any shell command on the host machine. "
        "It can be used to check Docker logs (e.g., 'docker logs my_container'), "
        "run docker-compose, or list files. The tool will automatically retry if it fails."
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
            
            except Exception as e:
                error_message = f"An unexpected error occurred on attempt {attempt + 1}: {str(e)}"
                print(f"[TOOL] [ERROR] {error_message}")
                return f"Command failed due to an unexpected error: {str(e)}"

        return f"Command failed after all retries. Last known error: {last_error}"

# --- Tool 4: Run Command Inside a Container ---

class RunInContainerInput(BaseModel):
    container_name: str = Field(description="The name of the container to run the command in.")
    command: str = Field(description="The command to execute inside the container.")

class RunInContainerTool(BaseTool):
    """A tool to execute a command inside a specific container AFTER user approval."""
    name: str = "run_in_container"
    description: str = (
        "Use this tool to run a command inside a specific honeypot container. "
        "For security, it will ask for user confirmation before executing."
    )
    args_schema: Type[BaseModel] = RunInContainerInput

    def _run(self, container_name: str, command: str) -> str:
        print("\n" + "="*50)
        print("### SECURITY APPROVAL REQUIRED ###")
        print(f"The agent is requesting to execute the following command inside container '{container_name}':")
        print(f"\n  $ {command}\n")
        print("This action will be performed using 'docker exec'.")
        print("="*50)

        try:
            approval = input("Do you approve this action? (y/n): ").lower().strip()
        except EOFError:
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
