# lifecycle_tools.py

import os
import shutil
import subprocess
from typing import Type
from pydantic import BaseModel, Field
from langchain.tools import BaseTool

# --- Schemi di Input per i Tool ---

class HoneypotInstanceInput(BaseModel):
    """Input per i tool che operano su una specifica istanza di honeypot."""
    instance_name: str = Field(description="Il nome dell'istanza dell'honeypot, es. 'cowrie-test-1'. Corrisponde al nome della cartella in 'honeypots'.")

class HoneypotLogsInput(BaseModel):
    """Input per il tool che legge i log di un container."""
    container_name: str = Field(description="Il nome esatto del container Docker, es. 'cowrie-test-1-cowrie-1'.")
    tail: int = Field(default=50, description="Il numero di righe finali da mostrare.")


# --- Tool di Gestione del Ciclo di Vita ---

class ListActiveHoneypotsTool(BaseTool):
    """Tool per elencare tutti gli honeypot deployati e il loro stato."""
    name: str = "list_active_honeypots"
    description: str = (
        "Usa questo tool per ottenere una lista di tutti gli honeypot deployati (attivi e non). "
        "Restituisce nome, stato e porte dei container Docker gestiti tramite questo agente."
    )

    def _run(self) -> str:
        print("\n[TOOL] Esecuzione di 'docker ps -a' per elencare gli honeypot...")
        try:
            # Il flag -p assicura che docker-compose crei i container con un nome prevedibile.
            # Questo comando elenca tutti i container che sono parte di un progetto docker-compose.
            command = [
                "docker", "ps", "-a", 
                "--filter", "label=com.docker.compose.project",
                "--format", "table {{.Names}}\t{{.Label \"com.docker.compose.project\"}}\t{{.Status}}\t{{.Ports}}"
            ]
            process = subprocess.run(
                command, check=True, capture_output=True, text=True, encoding='utf-8'
            )
            output = process.stdout.strip()
            if not output:
                return "Nessun honeypot trovato. Potrebbe essere necessario deployarne uno prima."
            return f"Honeypot Trovati:\n{output}"
        except FileNotFoundError:
            return "Errore: Comando 'docker' non trovato. Docker è installato e nel PATH?"
        except subprocess.CalledProcessError as e:
            return f"Errore durante l'esecuzione di 'docker ps'.\n--- STDERR ---\n{e.stderr.strip()}"


class GetHoneypotLogsTool(BaseTool):
    """Tool per leggere i log di uno specifico container honeypot."""
    name: str = "get_honeypot_logs"
    description: str = "Usa questo tool per recuperare gli ultimi log di un container specifico."
    args_schema: Type[BaseModel] = HoneypotLogsInput

    def _run(self, container_name: str, tail: int = 50) -> str:
        print(f"\n[TOOL] Lettura degli ultimi {tail} log dal container '{container_name}'...")
        try:
            command = ["docker", "logs", f"--tail={tail}", container_name]
            process = subprocess.run(
                command, check=True, capture_output=True, text=True, encoding='utf-8'
            )
            # stdout e stderr vengono catturati insieme perché 'docker logs' scrive su entrambi
            logs = process.stdout.strip() + "\n" + process.stderr.strip()
            return f"Log per '{container_name}':\n---\n{logs.strip()}"
        except FileNotFoundError:
            return "Errore: Comando 'docker' non trovato. Docker è installato e nel PATH?"
        except subprocess.CalledProcessError as e:
            return f"Errore nel recuperare i log per '{container_name}'. Il container esiste?\n--- STDERR ---\n{e.stderr.strip()}"

class StopHoneypotTool(BaseTool):
    """Tool per fermare un'istanza di honeypot."""
    name: str = "stop_honeypot"
    description: str = "Usa questo tool per fermare i servizi di un'istanza honeypot (senza cancellare i dati)."
    args_schema: Type[BaseModel] = HoneypotInstanceInput

    def _run(self, instance_name: str) -> str:
        deploy_dir = os.path.join("honeypots", instance_name)
        print(f"\n[TOOL] Tentativo di fermare l'istanza '{instance_name}' in '{deploy_dir}'...")

        if not os.path.isdir(deploy_dir):
            return f"Errore: Directory di deploy '{deploy_dir}' per l'istanza '{instance_name}' non trovata."

        try:
            # Usiamo -p per specificare il nome del progetto, rendendo il comando più robusto
            command = ["docker-compose", "-p", instance_name, "stop"]
            subprocess.run(
                command, cwd=deploy_dir, check=True, capture_output=True, text=True, encoding='utf-8'
            )
            return f"Istanza '{instance_name}' fermata con successo."
        except FileNotFoundError:
            return "Errore: Comando 'docker-compose' non trovato. È installato?"
        except subprocess.CalledProcessError as e:
            return f"Errore nel fermare l'istanza '{instance_name}'.\n--- STDERR ---\n{e.stderr.strip()}"

class StartHoneypotTool(BaseTool):
    """Tool per avviare un'istanza di honeypot precedentemente fermata."""
    name: str = "start_honeypot"
    description: str = "Usa questo tool per avviare i servizi di un'istanza honeypot precedentemente fermata."
    args_schema: Type[BaseModel] = HoneypotInstanceInput

    def _run(self, instance_name: str) -> str:
        deploy_dir = os.path.join("honeypots", instance_name)
        print(f"\n[TOOL] Tentativo di avviare l'istanza '{instance_name}' in '{deploy_dir}'...")

        if not os.path.isdir(deploy_dir):
            return f"Errore: Directory di deploy '{deploy_dir}' per l'istanza '{instance_name}' non trovata."

        try:
            command = ["docker-compose", "-p", instance_name, "start"]
            subprocess.run(
                command, cwd=deploy_dir, check=True, capture_output=True, text=True, encoding='utf-8'
            )
            return f"Istanza '{instance_name}' avviata con successo."
        except FileNotFoundError:
            return "Errore: Comando 'docker-compose' non trovato. È installato?"
        except subprocess.CalledProcessError as e:
            return f"Errore nell'avviare l'istanza '{instance_name}'.\n--- STDERR ---\n{e.stderr.strip()}"


class DestroyHoneypotTool(BaseTool):
    """Tool per distruggere permanentemente un'istanza di honeypot."""
    name: str = "destroy_honeypot"
    description: str = (
        "ATTENZIONE: Operazione distruttiva. Usa questo tool per fermare, rimuovere i container "
        "e CANCELLARE PERMANENTEMENTE la directory di configurazione e tutti i dati di un'istanza honeypot."
    )
    args_schema: Type[BaseModel] = HoneypotInstanceInput

    def _run(self, instance_name: str) -> str:
        deploy_dir = os.path.join("honeypots", instance_name)
        print(f"\n[TOOL] [!!] Richiesta di distruzione per l'istanza '{instance_name}' in '{deploy_dir}'...")
        
        if not os.path.isdir(deploy_dir):
            return f"Errore: Directory di deploy '{deploy_dir}' non trovata. Impossibile distruggere."

        # --- MECCANISMO DI SICUREZZA ---
        print("\n" + "="*60)
        print("### 💀 RICHIESTA DI APPROVAZIONE PER AZIONE DISTRUTTIVA ###")
        print(f"L'agente sta per cancellare PERMANENTEMENTE l'istanza '{instance_name}'.")
        print("Questo include i container, i volumi (dati, log) e i file di configurazione.")
        print("Questa azione non può essere annullata.")
        print("="*60)
        
        try:
            confirmation = input(f"Per confermare, scrivi il nome dell'istanza ('{instance_name}'): ").strip()
        except EOFError:
            return "Errore: Sessione non interattiva. Distruzione annullata."

        if confirmation != instance_name:
            return "Conferma non valida. Operazione di distruzione annullata."
        
        print(f"[TOOL] Conferma ricevuta. Procedo con la distruzione di '{instance_name}'...")
        try:
            # 1. Esegui docker-compose down -v per rimuovere container e volumi
            command = ["docker-compose", "-p", instance_name, "down", "-v"]
            subprocess.run(
                command, cwd=deploy_dir, check=True, capture_output=True, text=True, encoding='utf-8'
            )
            print(f"[TOOL] Container e volumi di '{instance_name}' rimossi.")
            
            # 2. Rimuovi la directory di deploy
            shutil.rmtree(deploy_dir)
            print(f"[TOOL] Directory '{deploy_dir}' rimossa.")

            return f"Istanza '{instance_name}' distrutta con successo."
        except Exception as e:
            return f"Si è verificato un errore imprevisto durante la distruzione: {e}"