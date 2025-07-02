# BigFS: Simulação de um Sistema de Arquivos Distribuído

**Autor:** wender13
**Versão:** 2.2 (Arquitetura de 3 Camadas com Verificação de Integridade)

## 1. Introdução

O **BigFS** é um sistema de arquivos distribuído funcional, desenvolvido em Python, que simula os princípios fundamentais de arquiteturas de larga escala como o HDFS (Hadoop Distributed File System). O projeto implementa um modelo robusto de 3 camadas (Cliente-Gateway-Backend) para demonstrar na prática conceitos avançados como **replicação de dados**, **tolerância a falhas**, **particionamento de arquivos (sharding)**, **balanceamento de carga** e **verificação de integridade de dados com Checksums**.

A interação com o sistema é feita através de um cliente de shell interativo, inspirado na usabilidade e simplicidade de ferramentas modernas como o Minio Client (`mc`).

## 2. Arquitetura do Sistema

O BigFS opera com uma arquitetura de 3 camadas para desacoplar responsabilidades:

* **Cliente (`client.py`):** A interface de usuário interativa que traduz comandos (`cp`, `ls`, `get`, `rm`) em chamadas de API para o Gateway.
* **Gateway Server (`gateway_server.py`):** A camada intermediária que recebe os arquivos, os particiona em `chunks`, calcula seus checksums e orquestra a comunicação com o backend.
* **Backend Distribuído:**
    * **Metadata Server (`metadata_server.py`):** O cérebro do cluster. Gerencia o mapa de arquivos, a localização de todos os `chunks` e monitora a saúde dos nós de armazenamento via `heartbeats`.
    * **Storage Nodes (`storage_node.py`):** Os "músculos" do cluster. Armazenam os `chunks` e seus checksums, executam a replicação e validam a integridade dos dados em cada leitura.

## 3. Guia de Instalação e Configuração

Siga estes passos para configurar o ambiente e rodar o projeto. As instruções são compatíveis com Linux, macOS e Windows.

### Pré-requisitos

* Git
* Python 3.8 ou superior
* `pip` e `venv` (geralmente incluídos na instalação do Python)

### Passo 1: Clonar o Repositório

Abra seu terminal ou PowerShell e clone o projeto a partir do seu GitHub.

```bash
git clone [https://github.com/wender13/BigFS.git](https://github.com/wender13/BigFS.git)
cd BigFS/
```

### Passo 2: Criar e Ativar o Ambiente Virtual

É uma boa prática isolar as dependências do projeto. Na raiz do projeto (`/BigFS/`), execute:

* **No Linux ou macOS:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
* **No Windows (PowerShell):**
    ```bash
    python -m venv venv
    .\venv\Scripts\Activate.ps1
    ```
    Você saberá que o ambiente está ativo quando vir `(venv)` no início do seu prompt.

### Passo 3: Instalar as Dependências

Com o ambiente virtual ativado, instale as bibliotecas gRPC:

```bash
pip install grpcio grpcio-tools
```

### Passo 4: Compilar o Contrato gRPC

Este passo traduz a API do arquivo `.proto` em código Python utilizável. **Execute este comando na raiz do projeto (`/BigFS/`)**.

```bash
python3 -m grpc_tools.protoc -Iproject --python_out=project --grpc_python_out=project project/bigfs.proto
```

## 4. Guia de Execução e Uso

Para rodar o sistema, você precisará de múltiplos terminais abertos na raiz do projeto, todos com o ambiente virtual ativado.

### 4.1. Iniciando o Cluster Completo

Inicie os componentes na seguinte ordem exata:

1.  **Terminal 1 (Metadata Server):**
    ```bash
    python3 -m project.metadata_server
    ```
    *Aguarde a mensagem: `📡 Metadata Server escutando...`*

2.  **Terminais 2, 3 e 4 (Storage Nodes):**
    Inicie pelo menos 3 para satisfazer a política de replicação (`REPLICATION_FACTOR=3`).
    ```bash
    # Terminal 2
    python3 -m project.storage_node localhost 50052 localhost:50051

    # Terminal 3
    python3 -m project.storage_node localhost 50053 localhost:50051

    # Terminal 4
    python3 -m project.storage_node localhost 50054 localhost:50051
    ```
    *Observe o terminal do Metadata Server para ver as mensagens de `❤️ Heartbeat` chegando.*

3.  **Terminal 5 (Gateway):**
    ```bash
    python3 -m project.gateway_server
    ```
    *Aguarde a mensagem: `📡 Gateway Server escutando...`*

### 4.2. Utilizando o Cliente Interativo

1.  **Terminal 6 (Cliente):**
    Conecte o cliente ao **Gateway** na porta `50050`.
    ```bash
    python3 -m project.client localhost:50050
    ```
2.  **Comandos Disponíveis no Shell:**
    Você verá o prompt `bigfs >`. Os seguintes comandos estão disponíveis:

| Comando | Exemplo de Uso                          | Descrição                                        |
| :------ | :-------------------------------------- | :----------------------------------------------- |
| `ls`    | `ls bfs://`                             | Lista todos os arquivos armazenados no sistema.  |
| `cp`    | `cp arquivo.txt bfs://remoto.txt`       | Copia um arquivo local (`upload`) para o BigFS.  |
| `get`   | `get bfs://remoto.txt copia.txt`        | Baixa um arquivo do BigFS para a máquina local.  |
| `rm`    | `rm bfs://remoto.txt`                   | Apaga um arquivo do BigFS.                       |
| `quit`  | `quit` ou `Ctrl+D`                      | Encerra o shell interativo do cliente.           |
| `help`  | `help` ou `help cp`                     | Mostra a lista de comandos ou a ajuda para um comando. |

5.  **Terminal 7 (Performance) / (Opcional):**
    ```bash
    python3 -m project.performance_test localhost:50050
    ```