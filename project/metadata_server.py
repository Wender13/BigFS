import grpc
from concurrent import futures
import time
import threading
import random
from collections import defaultdict
import bigfs_pb2
import bigfs_pb2_grpc

HEARTBEAT_TIMEOUT = 15
REPLICATION_FACTOR = 3
CHUNK_SIZE_BYTES = 1 * 1024 * 1024

class MetadataService(bigfs_pb2_grpc.MetadataServiceServicer):
    def __init__(self):
        self.storage_nodes = {}
        self.file_to_chunks = defaultdict(list)
        self.lock = threading.Lock()
        print("✅ Metadata Server iniciado (Estratégia: Nó Mais Vazio).")
        threading.Thread(target=self._check_dead_nodes, daemon=True).start()

    def RegisterNode(self, request, context):
        with self.lock:
            self.storage_nodes[request.address] = {
                'last_seen': time.time(),
                'chunk_count': request.chunk_count
            }
            print(f"[Metadata] Heartbeat de: {request.address} (Chunks: {request.chunk_count})")
        return bigfs_pb2.SimpleResponse(success=True)

    def ListFiles(self, request, context):
        with self.lock:
            files = []
            for filename, chunks in self.file_to_chunks.items():
                size = (len(chunks) -1) * CHUNK_SIZE_BYTES + 1 if chunks else 0
                files.append(bigfs_pb2.FileListResponse.FileInfo(filename=filename, size=size))
            return bigfs_pb2.FileListResponse(files=files)

    def GetWritePlan(self, request, context):
        with self.lock:
            active_nodes_status = list(self.storage_nodes.items())
            if len(active_nodes_status) < REPLICATION_FACTOR:
                msg = f"Nós insuficientes. Precisa: {REPLICATION_FACTOR}, Tem: {len(active_nodes_status)}"
                context.set_code(grpc.StatusCode.UNAVAILABLE); context.set_details(msg)
                return bigfs_pb2.FileLocationResponse()

            sorted_nodes = sorted(active_nodes_status, key=lambda item: item[1]['chunk_count'])
            available_node_addrs = [node_id for node_id, status in sorted_nodes]

            num_chunks = (request.size + CHUNK_SIZE_BYTES - 1) // CHUNK_SIZE_BYTES if request.size > 0 else 1
            plan = []
            print(f"[Metadata] Gerando plano para '{request.filename}' ({num_chunks} chunks). Nós ordenados por carga.")

            for i in range(num_chunks):
                if len(available_node_addrs) < REPLICATION_FACTOR:
                    context.set_code(grpc.StatusCode.INTERNAL); context.set_details("Falha na lógica de alocação.")
                    return bigfs_pb2.FileLocationResponse()
                
                chosen_nodes = available_node_addrs[:REPLICATION_FACTOR]
                primary, replicas = chosen_nodes[0], chosen_nodes[1:]
                
                chunk_id = f"{request.filename}_chunk{i}_{int(time.time())}"
                plan.append(bigfs_pb2.ChunkLocation(chunk_index=i, chunk_id=chunk_id, primary_node_id=primary, replica_node_ids=replicas))
                
                # Rotaciona a lista de nós para que o mesmo nó não seja sempre o primário
                available_node_addrs = available_node_addrs[1:] + available_node_addrs[:1]

            self.file_to_chunks[request.filename] = plan
            return bigfs_pb2.FileLocationResponse(is_sharded=num_chunks > 1, locations=plan)
    
    def GetFileLocation(self, request, context):
        with self.lock:
            if request.filename not in self.file_to_chunks:
                context.set_code(grpc.StatusCode.NOT_FOUND); context.set_details("Arquivo não encontrado.")
                return bigfs_pb2.FileLocationResponse()
            
            locations = self.file_to_chunks[request.filename]
            for loc in locations:
                if loc.primary_node_id not in self.storage_nodes:
                    promoted = False
                    for replica in loc.replica_node_ids:
                        if replica in self.storage_nodes:
                            loc.primary_node_id = replica; promoted = True
                            print(f"[Metadata] Failover: {replica} promovido para primário.")
                            break
                    if not promoted:
                        context.set_code(grpc.StatusCode.UNAVAILABLE); context.set_details(f"Nenhum nó disponível para chunk {loc.chunk_id}")
                        return bigfs_pb2.FileLocationResponse()
            return bigfs_pb2.FileLocationResponse(is_sharded=len(locations) > 1, locations=locations)

    def _check_dead_nodes(self):
        while True:
            time.sleep(HEARTBEAT_TIMEOUT)
            with self.lock:
                now = time.time(); dead = [nid for nid, status in self.storage_nodes.items() if now - status['last_seen'] > HEARTBEAT_TIMEOUT]
                if dead:
                    print(f"[Metadata] Nós inativos detectados: {dead}")
                    for nid in dead:
                        if nid in self.storage_nodes:
                            del self.storage_nodes[nid]

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bigfs_pb2_grpc.add_MetadataServiceServicer_to_server(MetadataService(), server)
    server.add_insecure_port('[::]:50051'); server.start()
    print("📡 Metadata Server escutando na porta 50051.")
    server.wait_for_termination()

if __name__ == '__main__': serve()