import os
import shutil
import subprocess
from typing import ClassVar
from langchain.tools import BaseTool

class DionaeaHoneyPotDeployTool(BaseTool):
    """Un tool per deployare l'honeypot Dionaea da un Dockerfile."""
    name: str = "dionaea_deployer"
    description: str = (
        "Usa questo tool per deployare o aggiornare l'honeypot Dionaea. "
        "Prepara i file da 'config_source/dionaea' nella directory 'honeypots/dionaea', "
        "crea la struttura di directory necessaria per i volumi Docker "
        "ed esegue 'docker-compose up'. Questo tool forza l'aggiornamento del container."
    )

    # --- Costanti di classe per i percorsi ---
    HONEYPOT_TYPE: ClassVar[str] = "dionaea"
    CONTAINER_NAME: ClassVar[str] = "dionaea"
    
    SOURCE_DIR: ClassVar[str] = os.path.join("config_source", HONEYPOT_TYPE)
    # La directory 'dist' contiene il Dockerfile, docker-compose.yml e le configurazioni
    SOURCE_DIST_DIR: ClassVar[str] = os.path.join(SOURCE_DIR, "dist")

    DEPLOY_DIR: ClassVar[str] = os.path.join("honeypots", HONEYPOT_TYPE)
    DEPLOY_DIST_DIR: ClassVar[str] = os.path.join(DEPLOY_DIR, "dist")
    
    def _run(self, *args, **kwargs) -> str:
        """Logica centrale del tool."""
        try:
            print(f"\n[TOOL] Avvio deploy dell'honeypot '{self.HONEYPOT_TYPE}' in '{self.DEPLOY_DIR}'...")
            
            if not os.path.isdir(self.SOURCE_DIR):
                return f"Errore: Directory sorgente non trovata in '{self.SOURCE_DIR}'. Creala e aggiungi i file necessari."

            self._check_docker_is_running()
            self._create_directory_structure()
            self._copy_files_to_deployment_dir()
            
            print(f"[TOOL] Esecuzione dei comandi Docker da '{self.DEPLOY_DIR}'...")
            
            # Eseguiamo i comandi dalla directory di deploy
            self._run_command(["docker-compose", "pull"], self.DEPLOY_DIR)
            self._run_command(["docker-compose", "up", "-d", "--force-recreate", "--build"], self.DEPLOY_DIR)
            
            success_message = (
                f"'{self.HONEYPOT_TYPE}' deployato/aggiornato con successo.\n"
                f"Il servizio emula diverse porte tra cui 21 (FTP), 42 (WINS), 135 (RPC), 443 (HTTPS), 1433 (MSSQL).\n"
                f"Per vedere i log, esegui: 'docker logs {self.CONTAINER_NAME}'."
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
        """Crea la struttura di directory necessaria per i volumi di Dionaea."""
        print(f" - Creazione della struttura di directory in '{self.DEPLOY_DIR}'...")
        # Directory di base
        os.makedirs(self.DEPLOY_DIR, exist_ok=True)
        
        # Directory per i file di build e configurazione
        os.makedirs(self.DEPLOY_DIST_DIR, exist_ok=True)
        
        print(" - Struttura di directory creata con successo.")


    def _copy_files_to_deployment_dir(self):
        """Copia i file necessari dalla sorgente alla directory di deploy."""
        print(f" - Copia dei file di configurazione da '{self.SOURCE_DIR}' a '{self.DEPLOY_DIR}'...")
        
        # Copia Dockerfile e docker-compose.yml nella directory principale di deploy
        shutil.copy(os.path.join(self.SOURCE_DIR, "Dockerfile"), self.DEPLOY_DIR)
        shutil.copy(os.path.join(self.SOURCE_DIR, "docker-compose.yml"), self.DEPLOY_DIR)
        print(" - Dockerfile e docker-compose.yml copiati con successo.")

        # Copia l'intera directory 'dist' che contiene le configurazioni
        if os.path.exists(self.SOURCE_DIST_DIR):
            # Usiamo copytree per copiare ricorsivamente tutti i file di configurazione
            shutil.copytree(self.SOURCE_DIST_DIR, self.DEPLOY_DIST_DIR, dirs_exist_ok=True)
            print(" - Directory 'dist' con le configurazioni copiata con successo.")
        
        print(" - File copiati con successo.")

    def _run_command(self, command, working_dir):
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
            # Aggiunto lo STDOUT all'errore, può essere utile per il debug
            error_msg = f"Comando fallito! STDERR: {e.stderr.strip()} STDOUT: {e.stdout.strip()}"
            print(f"[TOOL] [ERRORE] {error_msg}")
            raise RuntimeError(error_msg)