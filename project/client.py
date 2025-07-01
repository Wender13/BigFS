import grpc
import os
import sys
import cmd
import shlex
from concurrent.futures import ThreadPoolExecutor
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
            print(f"Erro fatal: Não foi possível conectar ao Gateway em {gateway_address}."); sys.exit(1)

    def _upload_generator(self, local_path, remote_path):
        try:
            yield bigfs_pb2.ChunkUploadRequest(metadata=bigfs_pb2.FileMetadata(remote_path=remote_path))
            with open(local_path, 'rb') as f:
                while True:
                    data = f.read(CHUNK_SIZE_BYTES)
                    if not data: break
                    yield bigfs_pb2.ChunkUploadRequest(data=data)
        except FileNotFoundError: return

    def _read_chunk(self, location):
        nodes = [location.primary_node_id] + list(location.replica_node_ids)
        for addr in nodes:
            try:
                with grpc.insecure_channel(addr) as channel:
                    stub = bigfs_pb2_grpc.StorageServiceStub(channel)
                    req = bigfs_pb2.ChunkRequest(chunk_id=location.chunk_id)
                    return location.chunk_index, stub.RetrieveChunk(req, timeout=10).data
            except grpc.RpcError: continue
        return location.chunk_index, None

    def copy_to_bigfs(self, local, remote):
        remote_name = remote.split("://")[-1].strip('/')
        if not os.path.exists(local):
            print(f"Erro: Arquivo local '{local}' não encontrado.")
            return

        print(f"--- Enviando [Local] {local} -> [BigFS] bfs://{remote_name} ---")
        try:
            resp = self.gateway_stub.UploadFile(self._upload_generator(local, remote_name))
            if resp.success: print(f"✅ Upload de '{remote_name}' concluído.")
            else: print(f"❌ Falha no upload: {resp.message}")
        except grpc.RpcError as e: print(f"❌ Erro no upload: {e.details()}")

    def get_from_bigfs(self, remote, local):
        remote_name = remote.split("://")[-1].strip('/')
        print(f"--- Baixando de [BigFS] bfs://{remote_name} -> [Local] {local} ---")
        try:
            plan = self.gateway_stub.GetDownloadMap(bigfs_pb2.FileRequest(filename=remote_name))
            if not plan.locations: print("Arquivo não encontrado no BigFS."); return
            
            chunks = {i: None for i in range(len(plan.locations))}
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(self._read_chunk, loc): loc for loc in plan.locations}
                for f in futures:
                    index, data = f.result()
                    chunks[index] = data
            
            if any(c is None for c in chunks.values()): print(f"❌ Falha ao baixar arquivo completo."); return
            with open(local, 'wb') as f:
                for i in sorted(chunks.keys()): f.write(chunks[i])
            print(f"✅ Arquivo '{remote_name}' salvo como '{local}'.")
        except grpc.RpcError as e: print(f"❌ Erro ao baixar: {e.details()}")

    def list_files(self, remote):
        path = remote.split("://")[-1].strip('/')
        print(f"--- Listando [BigFS] bfs://{path or '/'} ---")
        try:
            resp = self.gateway_stub.ListFiles(bigfs_pb2.PathRequest(path=path))
            if not resp.files: print("Nenhum arquivo encontrado."); return
            print(f"{'Nome':<40} {'Tamanho (aprox)'}"); print(f"{'----':<40} {'---------------'}")
            for info in sorted(resp.files, key=lambda f: f.filename):
                size_mb = info.size / (1024*1024); size_str = f"{size_mb:.2f} MB" if size_mb >= 1 else f"{info.size / 1024:.2f} KB"
                print(f"{info.filename:<40} {size_str}")
        except grpc.RpcError as e: print(f"❌ Erro ao listar: {e.details()}")

class BigFSShell(cmd.Cmd):
    intro = "Bem-vindo ao shell do BigFS. Digite 'help' ou '?' para listar os comandos."
    prompt = 'bigfs > '
    def __init__(self, client): super().__init__(); self.client = client
    def do_cp(self, arg):
        'Uso: cp <local> <remoto_bfs://>'
        try:
            args = shlex.split(arg)
            if len(args) == 2: self.client.copy_to_bigfs(args[0], args[1])
            else: print("Uso: cp <arquivo_local> <caminho_remoto_bfs://>")
        except Exception as e: print(f"Erro: {e}")
    def do_ls(self, arg):
        'Uso: ls <remoto_bfs://>'
        try:
            args = shlex.split(arg)
            if len(args) == 1: self.client.list_files(args[0])
            else: print("Uso: ls <caminho_remoto_bfs:// (use 'bfs:///' para a raiz)>")
        except Exception as e: print(f"Erro: {e}")
    def do_get(self, arg):
        'Uso: get <remoto_bfs://> <local>'
        try:
            args = shlex.split(arg)
            if len(args) == 2: self.client.get_from_bigfs(args[0], args[1])
            else: print("Uso: get <caminho_remoto_bfs://> <arquivo_local>")
        except Exception as e: print(f"Erro: {e}")
    def do_quit(self, arg): 'Sai do shell.'; print('Até logo!'); return True
    def do_EOF(self, arg): 'Sai do shell com Ctrl+D.'; print(); return self.do_quit(arg)

def main():
    if len(sys.argv) != 2: print("Uso: python3 project/client.py <gateway_address>"); sys.exit(1)
    try: BigFSShell(BigFSClient(sys.argv[1])).cmdloop()
    except KeyboardInterrupt: print("\nSaindo.")
if __name__ == '__main__': main()