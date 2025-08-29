# Inserisci questo codice nel tuo file cowrie.py, sostituendo la vecchia classe

import os
import shutil
import subprocess
from typing import Type, ClassVar
from pydantic import BaseModel, Field
from langchain.tools import BaseTool

# --- Schema per gli input del tool ---
class CowrieDeployToolInput(BaseModel):
    """Input per il CowrieDeployTool."""
    instance_name: str = Field(description="Un nome unico per questa istanza di honeypot, es. 'cowrie1'. Verrà usato per creare la cartella di deploy.")
    ssh_port: int = Field(description="La porta SSH esterna da mappare alla porta 2222 del container.")
    telnet_port: int = Field(description="La porta Telnet esterna da mappare alla porta 2223 del container.")

class CowrieDeployTool(BaseTool):
    """
    Un tool per deployare una nuova istanza configurabile dell'honeypot Cowrie.
    Richiede un nome di istanza e le porte per creare un ambiente isolato.
    """
    name: str = "cowrie_deployer"
    description: str = (
        "Usa questo tool per deployare una NUOVA o aggiornare una specifica istanza di Cowrie. "
        "Devi fornire un 'instance_name' unico, una 'ssh_port' e una 'telnet_port'. "
        "Il tool creerà una cartella dedicata per l'istanza e configurerà le porte di conseguenza."
    )
    args_schema: Type[BaseModel] = CowrieDeployToolInput

    # --- Percorsi di base (rimangono utili) ---
    HONEYPOT_TYPE: ClassVar[str] = "cowrie"
    SOURCE_DIR: ClassVar[str] = os.path.join("config_source", HONEYPOT_TYPE)
    HONEYPOTS_DIR: ClassVar[str] = "honeypots"

    def _run(self, instance_name: str, ssh_port: int, telnet_port: int) -> str:
        """Logica centrale e dinamica del tool."""
        
        # <<< MODIFICA CHIAVE 1: I percorsi di deploy ora sono dinamici >>>
        deploy_dir = os.path.join(self.HONEYPOTS_DIR, instance_name)
        config_dest_dir = os.path.join(deploy_dir, "dist")

        print(f"\n[TOOL] Avvio deploy per l'istanza '{instance_name}' in '{deploy_dir}'...")

        try:
            if not os.path.isdir(self.SOURCE_DIR):
                return f"Errore: La cartella sorgente non è stata trovata in '{self.SOURCE_DIR}'."

            self._check_docker_is_running()
            
            # Crea la struttura di cartelle specifica per l'istanza
            print(f"  - Creazione struttura cartelle in '{deploy_dir}'...")
            os.makedirs(config_dest_dir, exist_ok=True)

            # Copia i file di configurazione statici
            self._copy_static_files(config_dest_dir)
            
            # <<< MODIFICA CHIAVE 2: Crea il docker-compose.yml dinamicamente >>>
            self._create_dynamic_docker_compose(deploy_dir, instance_name, ssh_port, telnet_port)

            # Esegui docker-compose dalla cartella specifica dell'istanza
            print(f"[TOOL] Esecuzione di docker-compose da '{deploy_dir}'...")
            self._run_command(["docker-compose", "pull"], deploy_dir)
            # Aggiunto il flag -p per dare al progetto docker un nome univoco
            self._run_command(["docker-compose", "-p", instance_name, "up", "-d", "--force-recreate", "--build"], deploy_dir)
            
            # Copia il file da dist a src
            shutil.copy(os.path.join(config_dest_dir, "userdb.txt"), os.path.join(deploy_dir, "etc", "userdb.txt"))

            success_message = (
                f"Honeypot '{instance_name}' deployato con successo in '{deploy_dir}'.\n"
                f"SSH in ascolto sulla porta {ssh_port}, Telnet sulla porta {telnet_port}.\n"
            )
            print(f"[TOOL] {success_message}")
            return success_message

        except Exception as e:
            error_message = f"Fallimento nel deploy dell'istanza '{instance_name}'. Errore: {e}"
            print(f"[TOOL] [ERROR] {error_message}")
            return error_message

    def _create_dynamic_docker_compose(self, deploy_dir: str, instance_name: str, ssh_port: int, telnet_port: int):
        """Legge il template, sostituisce i segnaposto e scrive il file di configurazione finale."""
        print("  - Creazione del file docker-compose.yml dinamico...")
        template_path = os.path.join(self.SOURCE_DIR, "docker-compose.yml")
        final_path = os.path.join(deploy_dir, "docker-compose.yml")

        with open(template_path, 'r') as f:
            content = f.read()

        # Sostituzione dei segnaposto
        content = content.replace("${SSH_PORT}", str(ssh_port))
        content = content.replace("${TELNET_PORT}", str(telnet_port))
        content = content.replace("${INSTANCE_NAME}", instance_name) # Sostituisce anche il nome del container

        with open(final_path, 'w') as f:
            f.write(content)
        
        # Copia anche il Dockerfile
        shutil.copy(os.path.join(self.SOURCE_DIR, "Dockerfile"), deploy_dir)

        print("  - File docker-compose.yml personalizzato creato con successo.")

    def _copy_static_files(self, config_dest_dir: str):
        """Copia i file che non necessitano di modifiche."""
        print(f"  - Copia dei file di configurazione statici...")
        source_dist_dir = os.path.join(self.SOURCE_DIR, "dist")
        shutil.copy(os.path.join(source_dist_dir, "cowrie.cfg"), config_dest_dir)
        shutil.copy(os.path.join(source_dist_dir, "requirements.txt"), config_dest_dir)
        shutil.copy(os.path.join(source_dist_dir, "userdb.txt"), config_dest_dir)
        print("  - File statici copiati.")

    def _check_docker_is_running(self):
        # (Questa funzione rimane identica)
        print("  - Verifica della connessione al demone Docker...")
        try:
            subprocess.run(["docker", "info"], check=True, capture_output=True, text=True)
            print("  - Connessione a Docker riuscita.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("Il demone Docker non è in esecuzione o non è stato trovato.")

    def _run_command(self, command, working_dir):
        # (Questa funzione rimane identica)
        print(f"  - Esecuzione: {' '.join(command)} in '{working_dir}'")
        try:
            if not os.path.isdir(working_dir):
                raise FileNotFoundError(f"La cartella di lavoro non esiste: {working_dir}")
            
            process = subprocess.run(
                command, cwd=working_dir, check=True, capture_output=True, text=True, encoding='utf-8'
            )
            print("  - Comando eseguito con successo.")
            if process.stdout:
                print(f"  - STDOUT: {process.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            error_msg = f"Comando fallito! STDERR: {e.stderr.strip()}"
            print(f"[TOOL] [ERROR] {error_msg}")
            raise e