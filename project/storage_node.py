import grpc
from concurrent import futures
import time
import os
import sys
import threading
import bigfs_pb2
import bigfs_pb2_grpc

class StorageService(bigfs_pb2_grpc.StorageServiceServicer):
    def __init__(self, storage_dir):
        self.storage_dir = storage_dir
        if not os.path.exists(storage_dir): os.makedirs(storage_dir)

    def _replicate_chunk(self, replica_address, chunk):
        try:
            with grpc.insecure_channel(replica_address) as channel:
                stub = bigfs_pb2_grpc.StorageServiceStub(channel)
                replica_chunk = bigfs_pb2.Chunk(chunk_id=chunk.chunk_id, data=chunk.data)
                stub.StoreChunk(replica_chunk, timeout=15)
        except grpc.RpcError: pass

    def StoreChunk(self, request, context):
        chunk_path = os.path.join(self.storage_dir, request.chunk_id)
        try:
            with open(chunk_path, 'wb') as f: f.write(request.data)
            if request.replica_node_ids:
                for replica_addr in request.replica_node_ids:
                    threading.Thread(target=self._replicate_chunk, args=(replica_addr, request), daemon=True).start()
            return bigfs_pb2.SimpleResponse(success=True)
        except IOError: return bigfs_pb2.SimpleResponse(success=False)

    def RetrieveChunk(self, request, context):
        chunk_path = os.path.join(self.storage_dir, request.chunk_id)
        try:
            with open(chunk_path, 'rb') as f: data = f.read()
            return bigfs_pb2.Chunk(chunk_id=request.chunk_id, data=data)
        except FileNotFoundError:
            context.set_code(grpc.StatusCode.NOT_FOUND); context.set_details("Chunk não encontrado")
            return bigfs_pb2.Chunk()

def send_heartbeats(node_id, storage_dir, metadata_address):
    while True:
        try:
            chunk_count = len(os.listdir(storage_dir))
            with grpc.insecure_channel(metadata_address) as channel:
                stub = bigfs_pb2_grpc.MetadataServiceStub(channel)
                node_info = bigfs_pb2.NodeInfo(address=node_id, chunk_count=chunk_count)
                stub.RegisterNode(node_info)
        except Exception: pass
        time.sleep(5)

def RemoveChunk(self, request, context):
    """
    Remove chunk físico do disco
    """
    chunk_path = os.path.join(self.storage_dir, request.chunk_id)
    
    try:
        if os.path.exists(chunk_path):
            os.remove(chunk_path)
            print(f"[Storage] ✅ Chunk {request.chunk_id} removido do disco")
            return bigfs_pb2.SimpleResponse(success=True, message="Chunk removido")
        else:
            print(f"[Storage] ⚠️  Chunk {request.chunk_id} não encontrado no disco")
            return bigfs_pb2.SimpleResponse(success=False, message="Chunk não encontrado")
            
    except OSError as e:
        print(f"[Storage] ❌ Erro ao remover chunk {request.chunk_id}: {e}")
        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details(str(e))
        return bigfs_pb2.SimpleResponse(success=False, message=str(e))

def serve(port, metadata_address, my_ip):
    node_id = f"{my_ip}:{port}"; storage_dir = f"storage_{port}"
    if not os.path.exists(storage_dir): os.makedirs(storage_dir)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bigfs_pb2_grpc.add_StorageServiceServicer_to_server(StorageService(storage_dir), server)
    server.add_insecure_port(f'[::]:{port}'); server.start()
    print(f"📡 Storage Node '{node_id}' escutando na porta {port}.")
    threading.Thread(target=send_heartbeats, args=(node_id, storage_dir, metadata_address), daemon=True).start()
    server.wait_for_termination()

if __name__ == '__main__':
    if len(sys.argv) != 4: print("Uso: python3 project/storage_node.py <IP> <PORTA> <IP_METADATA:PORTA>"); sys.exit(1)
    serve(sys.argv[2], sys.argv[3], sys.argv[1])