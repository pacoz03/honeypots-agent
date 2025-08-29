import os
import shutil
import subprocess
from typing import ClassVar
from langchain.tools import BaseTool

class WordPotDeployTool(BaseTool):
    """Un tool per deployare l'honeypot Wordpot."""
    name: str = "wordpot_deployer"
    description: str = (
        "Usa questo tool per deployare o aggiornare l'honeypot Wordpot. "
        "Questo tool prepara i file necessari da 'config_source/wordpot' nella directory 'honeypots/wordpot', "
        "esegue 'docker-compose build' e avvia il container. Il tool forza l'aggiornamento se il container esiste già."
    )

    # --- Costanti di classe per i percorsi ---
    HONEYPOT_TYPE: ClassVar[str] = "wordpot"
    CONTAINER_NAME: ClassVar[str] = "wordpot"
    
    SOURCE_DIR: ClassVar[str] = os.path.join("config_source", HONEYPOT_TYPE)
    SOURCE_CONFIG_DIR: ClassVar[str] = os.path.join(SOURCE_DIR, "dist") # Directory 'dist' per il build

    DEPLOY_DIR: ClassVar[str] = os.path.join("honeypots", HONEYPOT_TYPE)
    DEPLOY_LOG_DIR: ClassVar[str] = os.path.join(DEPLOY_DIR, "log") # Directory per i log
    DEPLOY_CONFIG_DIR: ClassVar[str] = os.path.join(DEPLOY_DIR, "dist")

    def _run(self, *args, **kwargs) -> str:
        """Logica centrale del tool."""
        try:
            print(f"\n[TOOL] Avvio deploy dell'honeypot '{self.HONEYPOT_TYPE}' in '{self.DEPLOY_DIR}'...")
            
            if not os.path.isdir(self.SOURCE_DIR):
                return f"Errore: Directory sorgente non trovata in '{self.SOURCE_DIR}'. Creala e aggiungi i file Docker necessari."

            self._check_docker_is_running()
            self._create_directory_structure()
            self._copy_files_to_deployment_dir()
            
            print(f"[TOOL] Esecuzione dei comandi Docker da '{self.DEPLOY_DIR}'...")
            
            self._run_command(["docker-compose", "pull"], self.DEPLOY_DIR)
            self._run_command(["docker-compose", "up", "-d", "--force-recreate", "--build"], self.DEPLOY_DIR)
            
            success_message = (
                f"'{self.HONEYPOT_TYPE}' deployato/aggiornato con successo. 🍯\n"
                f"Il servizio è esposto sulla porta 80. Per vedere i log, esegui: 'docker logs {self.CONTAINER_NAME}' "
                f"o controlla la directory '{self.DEPLOY_LOG_DIR}'."
            )
            print(f"[TOOL] {success_message}")
            return success_message
        
        except Exception as e:
            error_message = f"Failed to deploy honeypot. Error: {e}"
            print(f"[TOOL] [ERROR] {error_message}")
            return error_message

    def _check_docker_is_running(self):
        """Verifica che il demone Docker sia in esecuzione."""
        print(" - Verifica della connessione al demone Docker...")
        try:
            subprocess.run(["docker", "info"], check=True, capture_output=True, text=True)
            print(" - Connessione al demone Docker riuscita.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("Il demone Docker non è in esecuzione o non è stato trovato.")

    def _create_directory_structure(self):
        """Crea la struttura di directory per il deploy."""
        print(f" - Creazione della struttura di directory in '{self.DEPLOY_DIR}'...")
        os.makedirs(self.DEPLOY_DIR, exist_ok=True)
        os.makedirs(self.DEPLOY_LOG_DIR, exist_ok=True)
        os.makedirs(self.DEPLOY_CONFIG_DIR, exist_ok=True)

    def _copy_files_to_deployment_dir(self):
        """Copia i file necessari dalla sorgente alla directory di deploy."""
        print(f" - Copia dei file di configurazione da '{self.SOURCE_DIR}' a '{self.DEPLOY_DIR}'...")
        
        # Copia i file principali
        shutil.copy(os.path.join(self.SOURCE_DIR, "Dockerfile"), self.DEPLOY_DIR)
        shutil.copy(os.path.join(self.SOURCE_DIR, "docker-compose.yml"), self.DEPLOY_DIR)
        print(" - Dockerfile e docker-compose.yml copiati con successo.")

        # Copia la directory 'dist' e il suo contenuto, necessaria per il build
        if os.path.isdir(self.SOURCE_CONFIG_DIR):
            shutil.copytree(self.SOURCE_CONFIG_DIR, self.DEPLOY_CONFIG_DIR, dirs_exist_ok=True)
            print(f" - Directory '{self.SOURCE_CONFIG_DIR}' copiata con successo.")
        else:
             print(f" - Attenzione: Directory '{self.SOURCE_CONFIG_DIR}' non trovata. Il build potrebbe fallire se richiesta.")


    def _run_command(self, command: list[str], working_dir: str):
        """Esegue un comando nella directory di lavoro specificata."""
        print(f" - Esecuzione: {' '.join(command)} in '{working_dir}'")
        try:
            if not os.path.isdir(working_dir):
                raise FileNotFoundError(f"Directory di lavoro non trovata: {working_dir}")
            
            process = subprocess.run(
                command,
                cwd=working_dir,
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            print(" - Comando eseguito con successo.")
            if process.stdout:
                print(f" - STDOUT: {process.stdout.strip()}")

        except subprocess.CalledProcessError as e:
            error_msg = f"Comando fallito! STDERR: {e.stderr.strip() if e.stderr else 'Nessun output di errore.'}"
            print(f"[TOOL] [ERRORE] {error_msg}")
            raise RuntimeError(error_msg) from e