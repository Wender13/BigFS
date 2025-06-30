# BigFS: Simulação de um Sistema de Arquivos Distribuído

**Autor:** wender13
**Versão:** 1.0 (Arquitetura de 3 Camadas com Gateway)

## 1. Introdução

O **BigFS** é um sistema de arquivos distribuído funcional, desenvolvido em Python, que simula os princípios fundamentais de arquiteturas de larga escala como o HDFS (Hadoop Distributed File System). O projeto implementa um modelo robusto de 3 camadas (Cliente-Gateway-Backend) para demonstrar na prática conceitos avançados como **replicação de dados**, **tolerância a falhas**, **particionamento de arquivos (sharding)** e **balanceamento de carga** na alocação de dados.

A interação com o sistema é feita através de um cliente de shell interativo, inspirado na usabilidade e simplicidade de ferramentas modernas como o Minio Client (`mc`).

## 2. Arquitetura do Sistema

O BigFS opera com uma arquitetura de 3 camadas para desacoplar responsabilidades:

* **Cliente (`client.py`):** A interface de usuário. Um shell interativo que traduz comandos simples (`cp`, `ls`, etc.) em chamadas de API para o Gateway.
* **Gateway Server (`gateway_server.py`):** A camada intermediária. Recebe os arquivos completos do cliente, assume o trabalho pesado de particioná-los em `chunks` e orquestra a comunicação com o backend para o armazenamento distribuído.
* **Backend Distribuído:**
    * **Metadata Server (`metadata_server.py`):** O cérebro do cluster. Gerencia o mapa de arquivos e a localização de todos os `chunks`, além de monitorar a saúde dos nós de armazenamento via `heartbeats`.
    * **Storage Nodes (`storage_node.py`):** Os "músculos" do cluster. Armazenam os `chunks` de dados físicos e executam a replicação entre si para garantir a durabilidade dos dados.

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