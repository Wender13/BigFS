import grpc
import os
import sys
import cmd
import shlex
import bigfs_pb2
import bigfs_pb2_grpc

CHUNK_SIZE_BYTES = 1 * 1024 * 1024

class BigFSClient:
    def __init__(self, gateway_address):
        try:
            self.gateway_channel = grpc.insecure_channel(gateway_address)
            grpc.channel_ready_future(self.gateway_channel).result(timeout=5)
            self.gateway_stub = bigfs_pb2_grpc.GatewayServiceStub(self.gateway_channel)
        except grpc.FutureTimeoutError:
            print(f"Erro fatal: Não foi possível conectar ao Gateway em {gateway_address}.")
            sys.exit(1)

    def _upload_generator(self, local_path, remote_path):
        try:
            yield bigfs_pb2.ChunkUploadRequest(
                metadata=bigfs_pb2.FileMetadata(remote_path=remote_path)
            )
            with open(local_path, 'rb') as f:
                while True:
                    data = f.read(CHUNK_SIZE_BYTES)
                    if not data: 
                        break
                    yield bigfs_pb2.ChunkUploadRequest(data=data)
        except FileNotFoundError: 
            return

    def copy_to_bigfs(self, local, remote):
        remote_name = remote.split("://")[-1].strip('/')
        if not os.path.exists(local):
            print(f"Erro: Arquivo local '{local}' não encontrado.")
            return

        print(f"--- Enviando [Local] {local} -> [BigFS] bfs://{remote_name} ---")
        try:
            resp = self.gateway_stub.UploadFile(self._upload_generator(local, remote_name))
            if resp.success: 
                print(f"✅ Upload de '{remote_name}' concluído.")
            else: 
                print(f"❌ Falha no upload: {resp.message}")
        except grpc.RpcError as e: 
            print(f"❌ Erro no upload: {e.details()}")

    def get_from_bigfs(self, remote, local):
        remote_name = remote.split("://")[-1].strip('/')
        print(f"--- Baixando de [BigFS] bfs://{remote_name} -> [Local] {local} ---")
        
        try:
            # Simples: apenas solicita download ao Gateway
            file_req = bigfs_pb2.FileRequest(filename=remote_name)
            response_stream = self.gateway_stub.DownloadFile(file_req)
            
            # Recebe chunks via streaming e salva
            with open(local, 'wb') as f:
                chunk_count = 0
                for chunk_response in response_stream:
                    f.write(chunk_response.data)
                    chunk_count += 1
                    print(f"Cliente: Chunk {chunk_count} recebido e salvo")
                    
                    if chunk_response.is_final_chunk:
                        print(f"Cliente: ✅ Último chunk recebido")
                        break
            
            print(f"✅ Arquivo '{remote_name}' salvo como '{local}'.")
            
        except grpc.RpcError as e:
            print(f"❌ Erro ao baixar: {e.details()}")

    def list_files(self, remote):
        path = remote.split("://")[-1].strip('/')
        print(f"--- Listando [BigFS] bfs://{path or '/'} ---")
        
        try:
            resp = self.gateway_stub.ListFiles(bigfs_pb2.PathRequest(path=path))
            if not resp.files: 
                print("Nenhum arquivo encontrado.")
                return
                
            print(f"{'Nome':<40} {'Tamanho (aprox)'}") 
            print(f"{'----':<40} {'---------------'}")
            
            for info in sorted(resp.files, key=lambda f: f.filename):
                size_mb = info.size / (1024*1024)
                size_str = f"{size_mb:.2f} MB" if size_mb >= 1 else f"{info.size / 1024:.2f} KB"
                print(f"{info.filename:<40} {size_str}")
                
        except grpc.RpcError as e: 
            print(f"❌ Erro ao listar: {e.details()}")

    def remove_from_bigfs(self, remote):
        remote_name = remote.split("://")[-1].strip('/')
        print(f"--- Removendo [BigFS] bfs://{remote_name} ---")
        
        try:
            file_req = bigfs_pb2.FileRequest(filename=remote_name)
            response = self.gateway_stub.RemoveFile(file_req)
            
            if response.success:
                print(f"✅ Arquivo '{remote_name}' removido com sucesso.")
                print(f"   Mensagem: {response.message}")
            else:
                print(f"❌ Falha na remoção: {response.message}")
                
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                print(f"❌ Arquivo '{remote_name}' não encontrado.")
            else:
                print(f"❌ Erro ao remover: {e.details()}")

class BigFSShell(cmd.Cmd):
    intro = "Bem-vindo ao shell do BigFS (COM RM). Digite 'help' ou '?' para listar os comandos."
    prompt = 'bigfs > '
    
    def __init__(self, client): 
        super().__init__()
        self.client = client
    
    def do_cp(self, arg):
        'Uso: cp <local> <remoto_bfs://>'
        try:
            args = shlex.split(arg)
            if len(args) == 2: 
                self.client.copy_to_bigfs(args[0], args[1])
            else: 
                print("Uso: cp <arquivo_local> <caminho_remoto_bfs://>")
        except Exception as e: 
            print(f"Erro: {e}")
    
    def do_ls(self, arg):
        'Uso: ls <remoto_bfs://>'
        try:
            args = shlex.split(arg)
            if len(args) == 1: 
                self.client.list_files(args[0])
            else: 
                print("Uso: ls <caminho_remoto_bfs:// (use 'bfs:///' para a raiz)>")
        except Exception as e: 
            print(f"Erro: {e}")
    
    def do_get(self, arg):
        'Uso: get <remoto_bfs://> <local>'
        try:
            args = shlex.split(arg)
            if len(args) == 2: 
                self.client.get_from_bigfs(args[0], args[1])
            else: 
                print("Uso: get <caminho_remoto_bfs://> <arquivo_local>")
        except Exception as e: 
            print(f"Erro: {e}")
    
    def do_rm(self, arg):
        'Uso: rm <remoto_bfs://>'
        try:
            args = shlex.split(arg)
            if len(args) == 1:
                # Confirmação de segurança
                confirm = input(f"Tem certeza que deseja remover '{args[0]}'? (s/N): ")
                if confirm.lower() in ['s', 'sim', 'y', 'yes']:
                    self.client.remove_from_bigfs(args[0])
                else:
                    print("Operação cancelada.")
            else:
                print("Uso: rm <caminho_remoto_bfs://>")
        except Exception as e:
            print(f"Erro: {e}")
    
    def do_quit(self, arg): 
        'Sai do shell.'
        print('Até logo!')
        return True
    
    def do_EOF(self, arg): 
        'Sai do shell com Ctrl+D.'
        print()
        return self.do_quit(arg)

def main():
    if len(sys.argv) != 2: 
        print("Uso: python3 project/client.py <gateway_address>")
        sys.exit(1)
    
    try: 
        BigFSShell(BigFSClient(sys.argv[1])).cmdloop()
    except KeyboardInterrupt: 
        print("\nSaindo.")

if __name__ == '__main__': 
    main()