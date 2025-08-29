# Honeypot Deployment and Management System

This project is a **Honeypot Deployment and Management System**. It allows a user to deploy, manage, and monitor various types of honeypots using Docker. The system is designed to be controlled via a conversational AI agent (powered by LangChain and OpenAI).

## Core Components

- **`main.py`**: The main entry point for the conversational agent. It initializes the LangChain agent, defines the available tools, and handles the user interaction loop.
- **Honeypot Deployment Tools (`cowrie.py`, `redis.py`, `wordpress.py`, `dionaea.py`, `galah.py`)**: Each of these files defines a `BaseTool` for deploying a specific honeypot. They handle the creation of necessary configuration files and the execution of `docker-compose` to start the honeypot.
- **Lifecycle Management Tools (`lifecycle_tools.py`)**: These tools provide functionalities to manage the lifecycle of the honeypots, such as starting, stopping, destroying, and retrieving logs.
- **`config_source/`**: This directory contains the source Dockerfiles, `docker-compose.yml` files, and other configuration templates for each honeypot.
- **`honeypots/`**: This directory is the destination where the honeypot configurations are copied and customized before being deployed. Each deployed honeypot instance will have its own subdirectory here.

## Technologies Used

- **Python**: The core language of the project.
- **LangChain**: The framework used to build the conversational agent.
- **OpenAI**: The LLM provider for the agent.
- **Docker**: Used for containerizing and running the honeypots.
- **Pydantic**: Used for data validation in the tool inputs.

## Available Honeypots

*   **Cowrie:** A medium-interaction SSH and Telnet honeypot designed to log brute force attacks and the shell interaction performed by the attacker.
*   **Dionaea:** A low-interaction honeypot designed to trap malware by emulating services that are commonly targeted by attackers, such as SMB, HTTP, FTP, and VoIP.
*   **WordPot:** A WordPress honeypot that detects probes for plugins, themes, and other common WordPress vulnerabilities.
*   **RedisHoneyPot:** A Redis honeypot that logs all interactions with a fake Redis server.
*   **Galah:** An email honeypot that can be configured to receive and store emails sent to a specific domain.

## Building and Running

### Prerequisites

- Python 3.x
- Docker installed and running.
- An OpenAI API key.

### Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Set up Environment Variables:**
    Create a `.env` file in the root directory and add your OpenAI API key:
    ```
    OPENAI_API_KEY="your_api_key_here"
    ```

### Running the Agent

To start the conversational agent, run:
```bash
python main.py
```

## Development Conventions

- **Tool-Based Architecture**: The agent's capabilities are extended by creating new `BaseTool` classes. Each tool should have a clear purpose and a well-defined input schema using Pydantic.
- **File System Safety**: The agent has built-in checks (`_is_path_safe`) to prevent it from accessing files outside of the project directory.
- **User Approval for Sensitive Operations**: For actions like modifying files or running commands in containers, the agent is designed to ask for explicit user approval via the console.
- **Configuration Management**: Honeypot configurations are managed by copying templates from `config_source` to a new directory in `honeypots` for each instance. This keeps the original templates clean.
- **State Management**: The state of active honeypots (e.g., running instances, their ports) should be tracked to avoid conflicts. (This is a potential area for improvement, as the current implementation might not have a robust state tracking mechanism).