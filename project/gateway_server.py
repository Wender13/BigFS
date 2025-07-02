import grpc
from concurrent import futures
import os
import sys
import uuid
import bigfs_pb2
import bigfs_pb2_grpc

CHUNK_SIZE_BYTES = 1 * 1024 * 1024
METADATA_SERVER_ADDRESS = '127.0.0.1:50051'

class GatewayService(bigfs_pb2_grpc.GatewayServiceServicer):
    def __init__(self):
        self.metadata_channel = grpc.insecure_channel(METADATA_SERVER_ADDRESS)
        self.metadata_stub = bigfs_pb2_grpc.MetadataServiceStub(self.metadata_channel)
        self.temp_dir = "gateway_temp"
        if not os.path.exists(self.temp_dir): 
            os.makedirs(self.temp_dir)

    def UploadFile(self, request_iterator, context):
        temp_filename = os.path.join(self.temp_dir, str(uuid.uuid4()))
        try:
            first_chunk = next(request_iterator)
            remote_path = first_chunk.metadata.remote_path
            file_size = 0
            
            with open(temp_filename, 'wb') as f:
                for chunk in request_iterator:
                    f.write(chunk.data)
                    file_size += len(chunk.data)
            
            file_req = bigfs_pb2.FileRequest(filename=remote_path, size=file_size)
            write_plan = self.metadata_stub.GetWritePlan(file_req)
            
            if not write_plan.locations:
                raise Exception(context.details() or "Falha ao obter plano de escrita.")
            
            with open(temp_filename, 'rb') as f:
                for loc in write_plan.locations:
                    chunk_data = f.read(CHUNK_SIZE_BYTES)
                    with grpc.insecure_channel(loc.primary_node_id) as channel:
                        stub = bigfs_pb2_grpc.StorageServiceStub(channel)
                        chunk_msg = bigfs_pb2.Chunk(
                            chunk_id=loc.chunk_id, 
                            data=chunk_data, 
                            replica_node_ids=loc.replica_node_ids
                        )
                        stub.StoreChunk(chunk_msg)
            
            return bigfs_pb2.SimpleResponse(success=True)
            
        except Exception as e:
            context.set_details(str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            return bigfs_pb2.SimpleResponse(success=False, message=str(e))
        finally:
            if os.path.exists(temp_filename): 
                os.remove(temp_filename)

    def DownloadFile(self, request, context):
        try:
            print(f"--- Gateway coordenando download de '{request.filename}' ---")
            
            # 1. Obter localização dos chunks do Metadata Server
            file_req = bigfs_pb2.FileRequest(filename=request.filename)
            locations_response = self.metadata_stub.GetFileLocation(file_req)
            
            if not locations_response.locations:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("Arquivo não encontrado")
                return
            
            # 2. Para cada chunk, buscar dados e fazer streaming
            total_chunks = len(locations_response.locations)
            
            for i, location in enumerate(locations_response.locations):
                # Buscar chunk com fallback automático
                chunk_data = self._fetch_chunk_with_fallback(location)
                
                if chunk_data is None:
                    context.set_code(grpc.StatusCode.INTERNAL)
                    context.set_details(f"Falha ao recuperar chunk {location.chunk_id}")
                    return
                
                # 3. Enviar chunk via streaming
                is_final = (i == total_chunks - 1)
                yield bigfs_pb2.ChunkDownloadResponse(
                    data=chunk_data,
                    is_final_chunk=is_final
                )
                
                print(f"Gateway: Chunk {i+1}/{total_chunks} enviado ao cliente")
            
            print(f"✅ Gateway: Download de '{request.filename}' concluído")
            
        except Exception as e:
            print(f"❌ Gateway: Erro no download - {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))

    def _fetch_chunk_with_fallback(self, location):
        # Tentar nó primário + réplicas
        nodes = [location.primary_node_id] + list(location.replica_node_ids)
        
        for node_addr in nodes:
            try:
                print(f"Gateway: Tentando buscar chunk {location.chunk_id} do nó {node_addr}")
                
                with grpc.insecure_channel(node_addr) as channel:
                    stub = bigfs_pb2_grpc.StorageServiceStub(channel)
                    req = bigfs_pb2.ChunkRequest(chunk_id=location.chunk_id)
                    response = stub.RetrieveChunk(req, timeout=10)
                    
                    print(f"Gateway: ✅ Chunk {location.chunk_id} recuperado de {node_addr}")
                    return response.data
                    
            except grpc.RpcError as e:
                print(f"Gateway: ❌ Falha ao buscar de {node_addr}: {e}")
                continue
        
        print(f"Gateway: ❌ Falha total - nenhum nó disponível para chunk {location.chunk_id}")
        return None

    def ListFiles(self, request, context):
        return self.metadata_stub.ListFiles(request)

    def RemoveFile(self, request, context):
        try:
            print(f"--- Gateway coordenando remoção de '{request.filename}' ---")
            
            # Delegar remoção ao Metadata Service
            response = self.metadata_stub.RemoveFile(request)
            
            if not response.success:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(response.message)
                return bigfs_pb2.SimpleResponse(success=False, message=response.message)
            
            # Log de estatísticas
            removed_count = len(response.removed_chunks)
            failed_count = len(response.failed_chunks)
            
            print(f"✅ Gateway: Arquivo '{request.filename}' removido")
            print(f"   Chunks removidos: {removed_count}")
            if failed_count > 0:
                print(f"   ⚠️  Falha na remoção de {failed_count} chunks: {response.failed_chunks}")
            
            # Retornar resposta simplificada para o cliente
            return bigfs_pb2.SimpleResponse(
                success=True, 
                message=f"Arquivo removido com sucesso. {removed_count} chunks removidos."
            )
            
        except grpc.RpcError as e:
            print(f"❌ Gateway: Erro na comunicação com Metadata Service - {e}")
            context.set_code(e.code())
            context.set_details(e.details())
            return bigfs_pb2.SimpleResponse(success=False, message=e.details())
            
        except Exception as e:
            print(f"❌ Gateway: Erro interno na remoção - {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return bigfs_pb2.SimpleResponse(success=False, message=str(e))

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bigfs_pb2_grpc.add_GatewayServiceServicer_to_server(GatewayService(), server)
    server.add_insecure_port('[::]:50050')
    server.start()
    print("📡 Gateway Server (COM RM) escutando na porta 50050.")
    server.wait_for_termination()

if __name__ == '__main__': 
    serve()